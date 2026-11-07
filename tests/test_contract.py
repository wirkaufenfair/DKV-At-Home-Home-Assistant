"""Contract tests against the real DKV login servers (no credentials).

The mocked tests in ``test_api.py`` only protect our own code. These tests
ask DKV's Keycloak whether it still accepts what the integration sends
(client id, redirect URI, scopes, PKCE) and whether it still answers the
way the integration expects. They fail when DKV changes the login.

Run with ``pytest -m contract``; they are skipped in a normal run.
"""

import re

import pytest
import requests

pytestmark = pytest.mark.contract

REDIRECT_URI = "com.dkv-mobility.app://oauth2redirect"


def with_retry(call, attempts=3):
    """DKV occasionally resets a connection; retry before failing."""
    for _ in range(attempts - 1):
        try:
            return call()
        except requests.ConnectionError:
            continue
    return call()


def authorize(api_module, **replace):
    """GET the authorize URL the integration builds, without following."""
    _, challenge = api_module.DkvApiClient.generate_pkce_pair()
    url = api_module.DkvApiClient.build_authorize_url(
        "contract-test", REDIRECT_URI, challenge
    )
    for key, value in replace.items():
        url = re.sub(rf"{key}=[^&]*", f"{key}={value}", url)
    return with_retry(
        lambda: requests.get(url, allow_redirects=False, timeout=30)
    )


def token_post(consts, **data):
    return with_retry(
        lambda: requests.post(consts.TOKEN_URL, data=data, timeout=30)
    )


class TestAuthorizeEndpoint:
    def test_login_page_is_served(self, api_module):
        """Client, redirect URI, scopes and PKCE are all accepted."""
        r = authorize(api_module)
        assert r.status_code == 200, (
            f"DKV rejects the login request: HTTP {r.status_code} "
            f"{r.headers.get('location', '')[:200]}"
        )
        # The form posts to this endpoint; the README names it too.
        assert "login-actions/authenticate" in r.text

    def test_unknown_client_is_rejected(self, api_module):
        """Control: proves the check above can fail."""
        assert authorize(api_module, client_id="no-such-client").status_code == 400

    def test_unknown_redirect_is_rejected(self, api_module):
        _, challenge = api_module.DkvApiClient.generate_pkce_pair()
        url = api_module.DkvApiClient.build_authorize_url(
            "s", "https://example.invalid/cb", challenge
        )
        r = with_retry(
            lambda: requests.get(url, allow_redirects=False, timeout=30)
        )
        assert r.status_code == 400


class TestTokenEndpoint:
    def test_client_is_known_for_code_exchange(self, consts):
        r = token_post(
            consts,
            grant_type="authorization_code",
            client_id=consts.CLIENT_ID,
            code="not-a-real-code",
            redirect_uri=REDIRECT_URI,
            code_verifier="v" * 50,
        )
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_grant"

    def test_unknown_client_is_rejected(self, consts):
        """Control: a wrong client id must give a different error."""
        r = token_post(
            consts,
            grant_type="authorization_code",
            client_id="no-such-client",
            code="x",
            redirect_uri=REDIRECT_URI,
            code_verifier="v" * 50,
        )
        assert r.json()["error"] == "invalid_client"

    def test_exchange_code_reports_invalid_grant(self, api_module):
        """The config flow relies on this text to ask for a new login."""
        client = api_module.DkvApiClient("", "")
        with pytest.raises(api_module.DkvApiError, match="invalid_grant"):
            with_retry(
                lambda: client.exchange_code(
                    code="not-a-real-code",
                    redirect_uri=REDIRECT_URI,
                    code_verifier="v" * 50,
                )
            )

    def test_dead_refresh_token_means_reauth(self, api_module):
        """A rejected refresh token must raise DkvAuthError (reauth flow)."""
        client = api_module.DkvApiClient("not-a-real-token", "user")
        with pytest.raises(api_module.DkvAuthError):
            with_retry(client._refresh)
