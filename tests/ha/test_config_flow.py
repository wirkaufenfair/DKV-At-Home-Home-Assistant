"""Tests for the setup dialog: how the login token is obtained.

The flow shows a login link, the user pastes the redirect URL, and the
integration exchanges the code for tokens. These tests run the whole flow
against a fake DKV server and check that what the dialog sends in the two
steps belongs together (same PKCE verifier, same client, same redirect).
"""

import base64
import hashlib
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from helpers import FakeResponse, make_jwt
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dkv_at_home.config_flow import _parse_user_input
from custom_components.dkv_at_home.const import CLIENT_ID, DOMAIN, TOKEN_URL

pytestmark = pytest.mark.asyncio

REDIRECT = "com.dkv-mobility.app://oauth2redirect"
USER = "100000000001"


def redirect_url(code="the-code", state="s1"):
    return f"{REDIRECT}?state={state}&session_state=ss&code={code}"


def tokens(refresh="refresh-1"):
    return FakeResponse(
        200,
        {"access_token": make_jwt(4102444800), "refresh_token": refresh},
    )


def login_routes(http, refresh="refresh-1"):
    http.add("POST", "openid-connect/token", tokens(refresh))
    http.add("GET", "userinfo", FakeResponse(200, {"preferred_username": USER}))


def challenge_of(auth_url):
    return parse_qs(urlparse(auth_url).query)["code_challenge"][0]


def s256(verifier):
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


# ----------------------------------------------------------------------
# Input recognition
# ----------------------------------------------------------------------


class TestParseInput:
    def test_redirect_url(self):
        parsed = _parse_user_input(redirect_url("abc", "st"))
        assert parsed == {
            "mode": "pkce_url",
            "code": "abc",
            "state": "st",
            "redirect_uri": REDIRECT,
        }

    def test_redirect_url_with_surrounding_whitespace(self):
        assert _parse_user_input(f"  {redirect_url('abc')}\n")["code"] == "abc"

    def test_https_redirect_is_accepted(self):
        url = "https://my.dkv-mobility.com/auth/callback?code=c1"
        parsed = _parse_user_input(url)
        assert parsed["mode"] == "pkce_url"
        assert parsed["redirect_uri"] == "https://my.dkv-mobility.com/auth/callback"

    def test_bare_code(self):
        assert _parse_user_input("abc-123") == {
            "mode": "pkce_code",
            "code": "abc-123",
        }

    def test_refresh_token(self):
        token = make_jwt(1) + ".more"
        assert _parse_user_input(token)["mode"] == "refresh_token"

    @pytest.mark.parametrize("text", ["", "   ", None])
    def test_empty_is_invalid(self, text):
        assert _parse_user_input(text)["mode"] == "invalid"

    def test_url_without_code_is_invalid(self):
        assert _parse_user_input(f"{REDIRECT}?code=")["mode"] == "invalid"


# ----------------------------------------------------------------------
# Full flow
# ----------------------------------------------------------------------


async def start_flow(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "auth"
    return result


async def test_shows_login_link(hass):
    result = await start_flow(hass)
    q = parse_qs(urlparse(result["description_placeholders"]["auth_url"]).query)
    assert q["client_id"] == [CLIENT_ID]
    assert q["redirect_uri"] == [REDIRECT]
    assert q["code_challenge_method"] == ["S256"]
    assert "offline_access" in q["scope"][0].split()


async def test_code_is_exchanged_with_matching_verifier(hass, http):
    """The verifier sent at the token step must match the link's challenge."""
    login_routes(http)
    result = await start_flow(hass)
    challenge = challenge_of(result["description_placeholders"]["auth_url"])

    with patch(
        "custom_components.dkv_at_home.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"token_input": redirect_url("the-code")}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    exchange = http.calls_to("POST", "openid-connect/token")[0]
    assert exchange["url"] == TOKEN_URL
    assert exchange["data"]["grant_type"] == "authorization_code"
    assert exchange["data"]["code"] == "the-code"
    assert exchange["data"]["client_id"] == CLIENT_ID
    assert exchange["data"]["redirect_uri"] == REDIRECT
    assert s256(exchange["data"]["code_verifier"]) == challenge


async def test_entry_is_created_with_tokens(hass, http):
    login_routes(http, refresh="refresh-9")
    result = await start_flow(hass)

    with patch(
        "custom_components.dkv_at_home.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"token_input": redirect_url()}
        )

    assert result["title"] == f"DKV@Home ({USER})"
    assert result["data"]["preferred_username"] == USER
    assert result["data"]["refresh_token"] == "refresh-9"
    assert result["data"]["access_token"]
    assert result["data"]["client_id"] == CLIENT_ID


async def test_pasted_refresh_token_is_accepted(hass, http):
    login_routes(http, refresh="refresh-rotated")
    result = await start_flow(hass)

    with patch(
        "custom_components.dkv_at_home.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"token_input": make_jwt(1) + ".x"}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    sent = http.calls_to("POST", "openid-connect/token")[0]["data"]
    assert sent["grant_type"] == "refresh_token"
    assert result["data"]["refresh_token"] == "refresh-rotated"


async def test_same_account_cannot_be_added_twice(hass, http):
    MockConfigEntry(domain=DOMAIN, unique_id=USER, data={}).add_to_hass(hass)
    login_routes(http)
    result = await start_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"token_input": redirect_url()}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# ----------------------------------------------------------------------
# Errors
# ----------------------------------------------------------------------


async def test_garbage_input_shows_error(hass):
    result = await start_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"token_input": "   "}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_input"}


async def test_used_code_creates_new_login_link(hass, http):
    """DKV answers invalid_grant for used or expired codes."""
    http.add(
        "POST",
        "openid-connect/token",
        FakeResponse(400, text='{"error":"invalid_grant"}'),
    )
    result = await start_flow(hass)
    old_url = result["description_placeholders"]["auth_url"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"token_input": redirect_url()}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "code_expired"}
    new_url = result["description_placeholders"]["auth_url"]
    assert challenge_of(new_url) != challenge_of(old_url)


async def test_server_error_is_reported(hass, http):
    http.add("POST", "openid-connect/token", FakeResponse(500, text="boom"))
    result = await start_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"token_input": redirect_url()}
    )

    assert result["errors"] == {"base": "cannot_connect"}
