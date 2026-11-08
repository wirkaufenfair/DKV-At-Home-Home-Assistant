"""Tests for the diagnostics download."""

import json

from helpers import FakeResponse, make_jwt
from test_integration import FakeCharger, make_entry, setup_entry

from custom_components.dkv_at_home.diagnostics import (
    async_get_config_entry_diagnostics,
)

SECRETS = ["refresh-0", "100000000001", "EVSE-1", "LOC-1"]


async def test_diagnostics_show_state_and_structure(hass, http):
    FakeCharger(http, session="SESSION-1")
    entry = make_entry(refresh_token="refresh-0")
    await setup_entry(hass, entry)

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["integration_version"]
    assert result["coordinator"]["last_update_success"] is True
    assert result["coordinator"]["update_interval_seconds"] == 30
    assert result["charge_point"]["status"] == "CHARGING"
    assert result["charge_point"]["has_active_session"] is True
    assert result["charge_point"]["remote_start_stop_capable"] is False
    # the structure is there: keys and types
    structure = result["charge_point"]["structure"]
    assert structure["hardwareInfo"]["evseUid"] == "str"
    assert structure["chargePointId"] == "str"


async def test_diagnostics_never_contain_secrets(hass, http):
    """Tokens, the account number and the ids from the answers stay out."""
    FakeCharger(http, session="SESSION-1")
    access = make_jwt(4102444800)
    entry = make_entry(access_token=access, refresh_token="refresh-0")
    await setup_entry(hass, entry)

    text = json.dumps(await async_get_config_entry_diagnostics(hass, entry))

    for secret in [*SECRETS, access, "SESSION-1"]:
        assert secret not in text, secret
    assert "**REDACTED**" in text


async def test_diagnostics_describe_the_tokens(hass, http):
    FakeCharger(http)
    entry = make_entry(refresh_token=make_jwt(1, typ="Offline"))
    await setup_entry(hass, entry)

    tokens = (await async_get_config_entry_diagnostics(hass, entry))["tokens"]

    assert tokens["refresh_token_type"] == "Offline"
    assert tokens["access_token_seconds_left"] > 0


async def test_diagnostics_list_the_payment_cards_without_ids(hass, http):
    """The kinds of cards show (e.g. a partner card); ids and hints never."""
    FakeCharger(http)
    entry = make_entry()
    await setup_entry(hass, entry)

    result = await async_get_config_entry_diagnostics(hass, entry)

    cards = result["payment_cards"]
    assert len(cards) == 1
    assert set(cards[0]) == {
        "type",
        "chargeCardIssuer",
        "verificationStatus",
        "default",
        "compatible",
        "accountPaymentMethod",
        "vidMapped",
    }
    text = json.dumps(result)
    assert "card-1" not in text  # the id
    assert "cardHint" not in text and "cardShortHint" not in text


async def test_diagnostics_survive_a_failing_card_request(hass, http):
    http.add("GET", "service-card", FakeResponse(503))
    FakeCharger(http)
    entry = make_entry()
    await setup_entry(hass, entry)

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert str(result["payment_cards"]).startswith("not available")
