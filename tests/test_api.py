"""Tests for the DKV@Home API client (no Home Assistant required)."""

import base64
import hashlib
import time
from urllib.parse import parse_qs, urlparse

import pytest
from helpers import FakeResponse, make_jwt

CP_IDLE = {
    "evseUid": "EVSE-1",
    "locationIdCa": "LOC-1",
    "status": "AVAILABLE",
    "activeSessionId": None,
    "name": "Wallbox",
}
CP_ACTIVE = {**CP_IDLE, "status": "CHARGING", "activeSessionId": "SESSION-1"}
CARDS = [{"id": "card-1"}]


def token_response(refresh="refresh-1", exp_in=3600):
    return FakeResponse(
        200,
        {
            "access_token": make_jwt(int(time.time()) + exp_in),
            "refresh_token": refresh,
        },
    )


# ----------------------------------------------------------------------
# JWT helpers
# ----------------------------------------------------------------------


class TestJwt:
    def test_decodes_exp(self, api_module):
        assert api_module.DkvApiClient._decode_jwt_exp(make_jwt(1234)) == 1234

    @pytest.mark.parametrize("token", [None, "", "abc", "a.b", "a.!!!.c"])
    def test_invalid_token_has_no_exp(self, api_module, token):
        assert api_module.DkvApiClient._decode_jwt_exp(token) is None

    def test_non_integer_exp_is_ignored(self, api_module):
        token = make_jwt("soon")
        assert api_module.DkvApiClient._decode_jwt_exp(token) is None

    def test_claims_of_invalid_token_are_empty(self, api_module):
        assert api_module.DkvApiClient._decode_jwt_claims("nope") == {}

    def test_decodes_claims(self, api_module):
        token = make_jwt(1234, typ="Offline")
        claims = api_module.DkvApiClient._decode_jwt_claims(token)
        assert claims == {"typ": "Offline", "exp": 1234}

    def test_undecodable_payload_gives_no_claims(self, api_module):
        assert api_module.DkvApiClient._decode_jwt_claims("a.bm90IGpzb24.c") == {}


# ----------------------------------------------------------------------
# Token handling
# ----------------------------------------------------------------------


class TestTokenRefresh:
    def test_refresh_rotates_both_tokens(self, http, client, consts):
        http.add("POST", "openid-connect/token", token_response("refresh-1"))

        client._refresh()

        assert client.refresh_token == "refresh-1"
        call = http.calls_to("POST", "openid-connect/token")[0]
        assert call["url"] == consts.TOKEN_URL
        assert call["data"] == {
            "grant_type": "refresh_token",
            "client_id": consts.CLIENT_ID,
            "refresh_token": "refresh-0",
        }

    def test_invalid_grant_means_reauth(self, http, client, api_module):
        http.add(
            "POST",
            "openid-connect/token",
            FakeResponse(400, text='{"error":"invalid_grant"}'),
        )
        with pytest.raises(api_module.DkvAuthError):
            client._refresh()

    def test_other_refresh_errors_are_not_auth_errors(
        self, http, client, api_module
    ):
        http.add("POST", "openid-connect/token", FakeResponse(500, text="boom"))
        with pytest.raises(api_module.DkvApiError) as err:
            client._refresh()
        assert not isinstance(err.value, api_module.DkvAuthError)

    @pytest.mark.parametrize(
        "answer",
        [
            FakeResponse(200, {"access_token": "a"}),  # refresh_token missing
            FakeResponse(200, {"refresh_token": "r"}),  # access_token missing
            FakeResponse(200, {}),
            FakeResponse(200),  # not JSON
        ],
    )
    def test_unexpected_token_answer_is_a_clear_error(
        self, http, client, api_module, answer
    ):
        """If DKV renames a field we want a message, not a KeyError."""
        http.add("POST", "openid-connect/token", answer)
        with pytest.raises(api_module.DkvApiError, match="Token-Antwort"):
            client._refresh()

    def test_no_refresh_while_token_is_valid(self, http, client):
        client._ensure_access_token()
        assert http.calls == []

    def test_refresh_when_token_missing(self, http, api_module):
        http.add("POST", "openid-connect/token", token_response())
        c = api_module.DkvApiClient("refresh-0", "user")
        c._ensure_access_token()
        assert c.access_token

    def test_refresh_shortly_before_expiry(self, http, api_module):
        http.add("POST", "openid-connect/token", token_response())
        soon = make_jwt(int(time.time()) + 30)
        c = api_module.DkvApiClient("refresh-0", "user", access_token=soon)
        c._ensure_access_token()
        assert c.access_token != soon

    def test_unknown_token_shape_is_kept(self, http, api_module):
        c = api_module.DkvApiClient("refresh-0", "user", access_token="opaque")
        c._ensure_access_token()
        assert http.calls == []
        assert c.access_token == "opaque"


# ----------------------------------------------------------------------
# Charge point / card lookups
# ----------------------------------------------------------------------


class TestChargePoint:
    @pytest.mark.parametrize(
        "payload", [[CP_IDLE], {"chargePoints": [CP_IDLE]}, CP_IDLE]
    )
    def test_accepts_known_response_shapes(self, http, client, payload):
        http.add("GET", "charge-points", FakeResponse(200, payload))
        assert client._get_charge_point()["evseUid"] == "EVSE-1"

    def test_sends_bearer_token(self, http, client):
        http.add("GET", "charge-points", FakeResponse(200, [CP_IDLE]))
        client._get_charge_point()
        auth = http.calls[0]["headers"]["Authorization"]
        assert auth == f"Bearer {client.access_token}"

    def test_401_triggers_refresh_and_retry(self, http, client):
        http.add(
            "GET",
            "charge-points",
            FakeResponse(401),
            FakeResponse(200, [CP_IDLE]),
        )
        http.add("POST", "openid-connect/token", token_response())
        assert client._get_charge_point()["name"] == "Wallbox"
        assert len(http.calls_to("POST", "openid-connect/token")) == 1

    def test_second_401_is_auth_error(self, http, client, api_module):
        http.add("GET", "charge-points", FakeResponse(401))
        http.add("POST", "openid-connect/token", token_response())
        with pytest.raises(api_module.DkvAuthError):
            client._get_charge_point()

    def test_5xx_is_transient(self, http, client, api_module):
        http.add("GET", "charge-points", FakeResponse(503))
        with pytest.raises(api_module.DkvTransientError):
            client._get_charge_point()

    def test_empty_list_is_error(self, http, client, api_module):
        http.add("GET", "charge-points", FakeResponse(200, []))
        with pytest.raises(api_module.DkvApiError):
            client._get_charge_point()

    def test_fetch_status_returns_charge_point(self, http, client):
        http.add("GET", "charge-points", FakeResponse(200, [CP_ACTIVE]))
        assert client.fetch_status()["activeSessionId"] == "SESSION-1"


class TestCard:
    @pytest.mark.parametrize(
        "payload", [CARDS, {"cards": CARDS}, {"data": CARDS}, CARDS[0]]
    )
    def test_accepts_known_response_shapes(self, http, client, payload):
        http.add("GET", "service-card", FakeResponse(200, payload))
        assert client._get_card_id() == "card-1"

    def test_missing_id_is_error(self, http, client, api_module):
        http.add("GET", "service-card", FakeResponse(200, [{"name": "x"}]))
        with pytest.raises(api_module.DkvApiError):
            client._get_card_id()

    def test_no_cards_is_error(self, http, client, api_module):
        http.add("GET", "service-card", FakeResponse(200, {"cards": []}))
        with pytest.raises(api_module.DkvApiError):
            client._get_card_id()

    def test_5xx_is_transient(self, http, client, api_module):
        http.add("GET", "service-card", FakeResponse(500))
        with pytest.raises(api_module.DkvTransientError):
            client._get_card_id()

    def test_empty_list_is_error(self, http, client, api_module):
        http.add("GET", "service-card", FakeResponse(200, []))
        with pytest.raises(api_module.DkvApiError, match="Ladekarten"):
            client._get_card_id()

    def test_401_triggers_refresh_and_retry(self, http, client):
        http.add(
            "GET", "service-card", FakeResponse(401), FakeResponse(200, CARDS)
        )
        http.add("POST", "openid-connect/token", token_response())
        assert client._get_card_id() == "card-1"
        assert len(http.calls_to("POST", "openid-connect/token")) == 1

    def test_second_401_is_auth_error(self, http, client, api_module):
        http.add("GET", "service-card", FakeResponse(401))
        http.add("POST", "openid-connect/token", token_response())
        with pytest.raises(api_module.DkvAuthError):
            client._get_card_id()


# ----------------------------------------------------------------------
# Login (PKCE)
# ----------------------------------------------------------------------


class TestLogin:
    def test_pkce_challenge_matches_verifier(self, api_module):
        verifier, challenge = api_module.DkvApiClient.generate_pkce_pair()
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        assert challenge == expected
        assert 43 <= len(verifier) <= 128

    def test_pkce_pairs_are_unique(self, api_module):
        a = api_module.DkvApiClient.generate_pkce_pair()
        b = api_module.DkvApiClient.generate_pkce_pair()
        assert a != b

    def test_authorize_url(self, api_module, consts):
        url = api_module.DkvApiClient.build_authorize_url(
            "state-1", "com.dkv-mobility.app://oauth2redirect", "challenge-1"
        )
        parts = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(parts.query).items()}
        assert parts.path.endswith("/protocol/openid-connect/auth")
        assert q["client_id"] == consts.CLIENT_ID
        assert q["response_type"] == "code"
        assert q["redirect_uri"] == "com.dkv-mobility.app://oauth2redirect"
        assert q["state"] == "state-1"
        assert q["code_challenge"] == "challenge-1"
        assert q["code_challenge_method"] == "S256"
        # offline_access gives the long-lived refresh token
        assert "offline_access" in q["scope"].split()

    def test_exchange_code(self, http, api_module, consts):
        http.add("POST", "openid-connect/token", token_response("refresh-9"))
        c = api_module.DkvApiClient("", "")
        c.exchange_code(
            code="abc",
            redirect_uri="com.dkv-mobility.app://oauth2redirect",
            code_verifier="verifier",
        )
        assert c.refresh_token == "refresh-9"
        assert c.access_token
        data = http.calls[0]["data"]
        assert data["grant_type"] == "authorization_code"
        assert data["code"] == "abc"
        assert data["code_verifier"] == "verifier"
        assert data["client_id"] == consts.CLIENT_ID

    @pytest.mark.parametrize(
        "answer",
        [FakeResponse(200, {"access_token": "a"}), FakeResponse(200, {}), FakeResponse(200)],
    )
    def test_exchange_code_unexpected_answer_is_a_clear_error(
        self, http, api_module, answer
    ):
        http.add("POST", "openid-connect/token", answer)
        c = api_module.DkvApiClient("", "")
        with pytest.raises(api_module.DkvApiError, match="Token-Antwort"):
            c.exchange_code(code="x", redirect_uri="r", code_verifier="v")

    def test_exchange_code_failure(self, http, api_module):
        http.add(
            "POST",
            "openid-connect/token",
            FakeResponse(400, text='{"error":"invalid_grant"}'),
        )
        c = api_module.DkvApiClient("", "")
        with pytest.raises(api_module.DkvApiError, match="invalid_grant"):
            c.exchange_code(code="x", redirect_uri="r", code_verifier="v")

    def test_preferred_username(self, http, client):
        http.add(
            "GET",
            "userinfo",
            FakeResponse(200, {"preferred_username": "100000000001"}),
        )
        assert client.fetch_preferred_username() == "100000000001"

    def test_preferred_username_missing(self, http, client, api_module):
        http.add("GET", "userinfo", FakeResponse(200, {}))
        with pytest.raises(api_module.DkvApiError):
            client.fetch_preferred_username()

    def test_userinfo_needs_an_access_token(self, http, api_module):
        client = api_module.DkvApiClient("refresh-0", "user")
        with pytest.raises(api_module.DkvApiError, match="Access Token"):
            client.fetch_preferred_username()
        assert http.calls == []

    def test_userinfo_error_is_reported(self, http, client, api_module):
        http.add("GET", "userinfo", FakeResponse(401, text="expired"))
        with pytest.raises(api_module.DkvApiError, match="HTTP 401"):
            client.fetch_preferred_username()

    def test_validate_refreshes_the_token(self, http, client):
        http.add("POST", "openid-connect/token", token_response("refresh-7"))
        client.validate()
        assert client.refresh_token == "refresh-7"


# ----------------------------------------------------------------------
# Start
# ----------------------------------------------------------------------


def start_routes(http, charge_points, start_response=None):
    http.add("GET", "charge-points", *charge_points)
    http.add("GET", "service-card", FakeResponse(200, CARDS))
    http.add(
        "POST",
        "session/start",
        start_response or FakeResponse(200, {"chargeSessionId": "SESSION-1"}),
    )


class TestStart:
    def test_returns_confirmed_session_id(self, http, client):
        start_routes(
            http,
            [
                FakeResponse(200, [CP_IDLE]),  # lookup before the request
                FakeResponse(200, [CP_IDLE]),  # first confirmation poll
                FakeResponse(200, [CP_ACTIVE]),
            ],
        )
        assert client.start() == "SESSION-1"

    def test_request_body(self, http, client, consts):
        """isHomeCharger was missing in 1.0.27 and caused HTTP 400."""
        start_routes(
            http, [FakeResponse(200, [CP_IDLE]), FakeResponse(200, [CP_ACTIVE])]
        )
        client.start()
        call = http.calls_to("POST", "session/start")[0]
        assert call["url"].startswith(consts.BASE_URL)
        assert call["json"] == {
            "evseUid": "EVSE-1",
            "locationId": "LOC-1",
            "paymentMethodId": "card-1",
            "isHomeCharger": True,
        }

    def test_ids_from_hardware_info(self, http, client):
        cp = {
            "hardwareInfo": {"evseUid": "EVSE-2", "locationIdCa": "LOC-2"},
            "activeSessionId": None,
        }
        active = {**cp, "activeSessionId": "S"}
        start_routes(http, [FakeResponse(200, [cp]), FakeResponse(200, [active])])
        client.start()
        body = http.calls_to("POST", "session/start")[0]["json"]
        assert (body["evseUid"], body["locationId"]) == ("EVSE-2", "LOC-2")

    def test_missing_ids_is_error(self, http, client, api_module):
        http.add("GET", "charge-points", FakeResponse(200, [{"name": "x"}]))
        with pytest.raises(api_module.DkvApiError, match="evseUid"):
            client.start()
        assert http.calls_to("POST", "session/start") == []

    def test_rejected_start_is_error(self, http, client, api_module):
        start_routes(
            http,
            [FakeResponse(200, [CP_IDLE])],
            FakeResponse(400, text="bad request"),
        )
        with pytest.raises(api_module.DkvApiError, match="HTTP 400"):
            client.start()

    def test_unconfirmed_start_returns_none(self, http, client, consts):
        start_routes(http, [FakeResponse(200, [CP_IDLE])])
        assert client.start() is None
        polls = consts.CONFIRM_TIMEOUT_SECONDS // consts.CONFIRM_INTERVAL_SECONDS
        # one lookup before the request plus every confirmation poll
        assert len(http.calls_to("GET", "charge-points")) == 1 + polls

    def test_start_response_without_json_is_tolerated(self, http, client):
        start_routes(
            http,
            [FakeResponse(200, [CP_IDLE]), FakeResponse(200, [CP_ACTIVE])],
            FakeResponse(202),
        )
        assert client.start() == "SESSION-1"


# ----------------------------------------------------------------------
# Stop
# ----------------------------------------------------------------------


class TestStop:
    def test_nothing_to_stop(self, http, client):
        http.add("GET", "charge-points", FakeResponse(200, [CP_IDLE]))
        assert client.stop() is True
        assert http.calls_to("POST", "session/stop") == []

    def test_stops_active_session(self, http, client, consts):
        http.add(
            "GET",
            "charge-points",
            FakeResponse(200, [CP_ACTIVE]),  # lookup
            FakeResponse(200, [CP_IDLE]),  # confirmation
        )
        http.add("POST", "session/stop", FakeResponse(204))
        assert client.stop() is True
        call = http.calls_to("POST", "session/stop")[0]
        assert call["url"] == consts.STOP_URL
        assert call["params"] == {"appToken": consts.STOP_APP_TOKEN}
        assert call["json"] == {"chargeSessionId": "SESSION-1"}

    def test_rejected_stop_is_error(self, http, client, api_module):
        http.add("GET", "charge-points", FakeResponse(200, [CP_ACTIVE]))
        http.add("POST", "session/stop", FakeResponse(403, text="no"))
        with pytest.raises(api_module.DkvApiError, match="HTTP 403"):
            client.stop()

    def test_unconfirmed_stop_returns_false(self, http, client):
        http.add("GET", "charge-points", FakeResponse(200, [CP_ACTIVE]))
        http.add("POST", "session/stop", FakeResponse(200))
        assert client.stop() is False


# ----------------------------------------------------------------------
# Concurrency
# ----------------------------------------------------------------------


class TestConcurrentUse:
    """The poll (every 30 s) and a start/stop run in separate threads.

    DKV rotates the refresh token: it works once. If both threads refresh
    at the same moment, the second one is rejected with ``invalid_grant``
    and the integration asks for a new login.
    """

    def test_parallel_refresh_uses_the_token_only_once(self, http, api_module):
        import threading

        state = {"valid": "refresh-0", "uses": 0}
        lock = threading.Lock()
        meeting = threading.Barrier(2, timeout=1)

        def token_endpoint():
            # Make a second thread that is also refreshing arrive here at the
            # same time; without a lock in the client both get this far.
            try:
                meeting.wait()
            except threading.BrokenBarrierError:
                pass
            with lock:
                state["uses"] += 1
                posts = http.calls_to("POST", "openid-connect/token")
                presented = posts[-1]["data"]["refresh_token"]
                if presented != state["valid"]:
                    return FakeResponse(400, text='{"error":"invalid_grant"}')
                state["valid"] = "refresh-1"
                return token_response("refresh-1")

        http.add("POST", "openid-connect/token", token_endpoint)
        http.add("GET", "charge-points", FakeResponse(200, [CP_IDLE]))

        expired = make_jwt(int(time.time()) - 10)
        client = api_module.DkvApiClient("refresh-0", "user", access_token=expired)
        errors = []

        def poll():
            try:
                client.fetch_status()
            except Exception as err:  # noqa: BLE001
                errors.append(err)

        threads = [threading.Thread(target=poll) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == []
        assert state["uses"] == 1
        assert client.refresh_token == "refresh-1"
