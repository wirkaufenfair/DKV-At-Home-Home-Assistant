"""Guard: the log must stay safe to paste into a bug report.

Users copy the debug log into issues. Tokens, the ids DKV returns (charge
point, location, session, card) and contract data must never appear in it,
whatever the integration does. Only structure (keys and types) may be logged.
"""

import logging

import pytest
from helpers import FakeResponse, charge_point_answer, make_jwt

SECRET_EVSE = "EVSE-SECRET-1"
SECRET_LOCATION = "LOC-SECRET-2"
SECRET_SESSION = "SESSION-SECRET-3"
SECRET_CARD = "CARD-SECRET-4"
SECRET_REFRESH = "REFRESH-SECRET-5"
SECRET_REFRESH_NEW = "REFRESH-SECRET-6"
SECRET_CODE_TAIL = "CODE-SECRET-TAIL-7"  # only the first 8 characters are logged
SECRET_USER = "100000SECRET8"
SECRET_VALUE = "CONTRACT-SECRET-9"  # inside nested objects of the charge point

ALL_SECRETS = [
    SECRET_EVSE,
    SECRET_LOCATION,
    SECRET_SESSION,
    SECRET_CARD,
    SECRET_REFRESH,
    SECRET_REFRESH_NEW,
    SECRET_CODE_TAIL,
    SECRET_USER,
    SECRET_VALUE,
]


def answer(session=None):
    data = charge_point_answer(
        session=session, evse_uid=SECRET_EVSE, location_id=SECRET_LOCATION
    )
    cp = data["chargePoints"][0]
    cp["currentMonthActiveContracts"][0]["contractId"] = SECRET_VALUE
    cp["currentMonthActiveContracts"][0]["assignedTo"] = SECRET_VALUE
    cp["payments"] = [{"cardNumber": SECRET_VALUE}]
    return data


@pytest.fixture
def secret_client(api_module):
    return api_module.DkvApiClient(
        refresh_token=SECRET_REFRESH,
        app_token=SECRET_USER,
        access_token=make_jwt(4102444800, sub=SECRET_USER),
    )


def test_log_never_contains_tokens_ids_or_contract_data(
    http, secret_client, api_module, caplog
):
    new_access = make_jwt(4102444800, sub=SECRET_USER)
    http.add(
        "POST",
        "openid-connect/token",
        FakeResponse(
            200, {"access_token": new_access, "refresh_token": SECRET_REFRESH_NEW}
        ),
    )
    http.add("GET", "userinfo", FakeResponse(200, {"preferred_username": SECRET_USER}))
    http.add(
        "GET",
        "charge-points",
        FakeResponse(200, answer()),  # status
        FakeResponse(200, answer()),  # lookup before start
        FakeResponse(200, answer(SECRET_SESSION)),  # confirmed
        FakeResponse(200, answer(SECRET_SESSION)),  # lookup before stop
        FakeResponse(200, answer()),  # stopped
    )
    http.add("GET", "service-card", FakeResponse(200, [{"id": SECRET_CARD}]))
    http.add(
        "POST", "session/start", FakeResponse(200, {"chargeSessionId": SECRET_SESSION})
    )
    http.add("POST", "session/stop", FakeResponse(204))

    with caplog.at_level(logging.DEBUG):
        secret_client.fetch_status()
        secret_client.start()
        secret_client.stop()
        secret_client._refresh()
        secret_client.fetch_preferred_username()
        exchange = api_module.DkvApiClient("", "")
        exchange.exchange_code(
            code="ZZZZZZZZ" + SECRET_CODE_TAIL,
            redirect_uri="com.dkv-mobility.app://oauth2redirect",
            code_verifier="verifier-secret",
        )

    log = caplog.text
    assert "API-Struktur" in log, "the structure logging should have run"
    leaked = [secret for secret in ALL_SECRETS if secret in log]
    assert not leaked, f"the log leaks: {leaked}"
    assert "verifier-secret" not in log
