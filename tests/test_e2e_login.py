"""End-to-end test of the login with a real DKV account.

This is the only test that sends a real authorization code to the token
endpoint, so it is the one that notices when DKV requires new parameters
there. It logs in like the browser flow in the README, exchanges the code,
and makes read-only API calls. It never starts or stops a charging session.

Needs ``DKV_USERNAME`` and ``DKV_PASSWORD``; skipped otherwise. Run with
``pytest -m e2e``. Each run creates one login session at DKV and ends it
again at the end.
"""

import html
import os
import re
from urllib.parse import parse_qs, urlparse

import pytest
import requests

USERNAME = os.environ.get("DKV_USERNAME")
PASSWORD = os.environ.get("DKV_PASSWORD")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not (USERNAME and PASSWORD),
        reason="DKV_USERNAME and DKV_PASSWORD not set",
    ),
]

REDIRECT_URI = "com.dkv-mobility.app://oauth2redirect"
LOGOUT_URL = (
    "https://my.dkv-mobility.com/auth/realms/dkv/"
    "protocol/openid-connect/logout"
)


def login_for_code(api_module):
    """Log in through the HTML form and return (code, code_verifier)."""
    verifier, challenge = api_module.DkvApiClient.generate_pkce_pair()
    url = api_module.DkvApiClient.build_authorize_url(
        "e2e-test", REDIRECT_URI, challenge
    )
    session = requests.Session()
    page = session.get(url, timeout=30)
    assert page.status_code == 200, f"login page: HTTP {page.status_code}"

    form = re.search(
        r'<form[^>]*action="([^"]*login-actions/authenticate[^"]*)"[^>]*>(.*?)</form>',
        page.text,
        re.DOTALL,
    )
    assert form, "login form not found; DKV changed the login page"
    action = html.unescape(form.group(1))

    fields = {}
    for tag in re.findall(r"<input[^>]*>", form.group(2)):
        name = re.search(r'name="([^"]+)"', tag)
        value = re.search(r'value="([^"]*)"', tag)
        if name and re.search(r'type="hidden"', tag):
            fields[name.group(1)] = html.unescape(value.group(1)) if value else ""
    fields.update({"username": USERNAME, "password": PASSWORD})

    response = session.post(
        action, data=fields, allow_redirects=False, timeout=30
    )
    location = response.headers.get("location", "")
    assert response.status_code == 302 and location.startswith(REDIRECT_URI), (
        "login did not redirect to the app URL "
        f"(HTTP {response.status_code}); wrong credentials, a new login "
        "step or a captcha?"
    )
    code = parse_qs(urlparse(location).query)["code"][0]
    return code, verifier


@pytest.fixture(scope="module")
def logged_in(request):
    """A client logged in through the real flow; ends the session after."""
    import sys

    api_module = sys.modules["dkv_at_home.api"]
    code, verifier = login_for_code(api_module)
    client = api_module.DkvApiClient(refresh_token="", app_token="")
    client.exchange_code(
        code=code, redirect_uri=REDIRECT_URI, code_verifier=verifier
    )
    yield client
    requests.post(
        LOGOUT_URL,
        data={
            "client_id": client.client_id,
            "refresh_token": client.refresh_token,
        },
        timeout=30,
    )


def test_code_exchange_gives_long_lived_token(logged_in, api_module):
    """offline_access must still give an Offline token (no 30 minute limit)."""
    claims = api_module.DkvApiClient._decode_jwt_claims(logged_in.refresh_token)
    assert claims.get("typ") == "Offline"


def test_userinfo_gives_username(logged_in):
    assert logged_in.fetch_preferred_username()


def test_refresh_token_rotation_works(logged_in):
    logged_in._refresh()
    assert logged_in.access_token
    assert logged_in.refresh_token


def test_charge_point_has_what_start_needs(logged_in):
    """start() reads these fields; DKV renaming them would break it."""
    cp = logged_in.fetch_status()
    hardware = cp.get("hardwareInfo", {})
    assert cp.get("evseUid") or hardware.get("evseUid")
    assert cp.get("locationIdCa") or hardware.get("locationIdCa")
    assert "activeSessionId" in cp or "status" in cp


def test_payment_card_is_available(logged_in):
    assert logged_in._get_card_id()
