"""Tests for setup, the charging switch and token persistence."""

from datetime import timedelta

import pytest
from helpers import FakeResponse, make_jwt
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.dkv_at_home.const import CLIENT_ID, DOMAIN

USER = "100000000001"
FAR_FUTURE = 4102444800


def make_entry(access_token="valid", refresh_token="refresh-0"):
    if access_token == "valid":
        access_token = make_jwt(FAR_FUTURE)
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=USER,
        title=f"DKV@Home ({USER})",
        data={
            "preferred_username": USER,
            "refresh_token": refresh_token,
            "access_token": access_token,
            "client_id": CLIENT_ID,
        },
    )


class FakeCharger:
    """A charge point whose state the fake DKV server reports and changes."""

    def __init__(self, http, session=None):
        self.session = session
        self.start_bodies = []
        self.stop_bodies = []
        http.add("GET", "charge-points", self._charge_point)
        http.add("GET", "service-card", FakeResponse(200, [{"id": "card-1"}]))
        http.add("POST", "session/start", self._start)
        http.add("POST", "session/stop", self._stop)

    def _charge_point(self):
        return FakeResponse(
            200,
            [
                {
                    "evseUid": "EVSE-1",
                    "locationIdCa": "LOC-1",
                    "status": "CHARGING" if self.session else "AVAILABLE",
                    "activeSessionId": self.session,
                    "name": "Wallbox",
                }
            ],
        )

    def _start(self):
        self.session = "SESSION-1"
        return FakeResponse(200, {"chargeSessionId": "SESSION-1"})

    def _stop(self):
        self.session = None
        return FakeResponse(204)


async def setup_entry(hass, entry):
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def let_refresh_run(hass):
    """Home Assistant delays a requested refresh by its cooldown (10 s)."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=30))
    await hass.async_block_till_done()


def switch_id(hass):
    return er.async_get(hass).async_get_entity_id(
        "switch", DOMAIN, f"dkv_at_home_{USER}"
    )


# ----------------------------------------------------------------------
# Switch state
# ----------------------------------------------------------------------


async def test_switch_is_off_without_session(hass, http):
    FakeCharger(http)
    entry = make_entry()
    await setup_entry(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    state = hass.states.get(switch_id(hass))
    assert state.state == "off"
    assert state.attributes["charge_point_status"] == "AVAILABLE"
    assert state.attributes["active_session_id"] is None


async def test_switch_is_on_with_active_session(hass, http):
    FakeCharger(http, session="SESSION-9")
    await setup_entry(hass, make_entry())

    state = hass.states.get(switch_id(hass))
    assert state.state == "on"
    assert state.attributes["active_session_id"] == "SESSION-9"


# ----------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------


async def test_turn_on_starts_session(hass, http):
    charger = FakeCharger(http)
    await setup_entry(hass, make_entry())
    entity_id = switch_id(hass)

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": entity_id}, blocking=True
    )
    await let_refresh_run(hass)

    body = http.calls_to("POST", "session/start")[0]["json"]
    assert body["isHomeCharger"] is True
    assert charger.session == "SESSION-1"
    assert hass.states.get(entity_id).state == "on"


async def test_turn_off_stops_session(hass, http):
    charger = FakeCharger(http, session="SESSION-1")
    await setup_entry(hass, make_entry())
    entity_id = switch_id(hass)

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": entity_id}, blocking=True
    )
    await let_refresh_run(hass)

    call = http.calls_to("POST", "session/stop")[0]
    assert call["json"] == {"chargeSessionId": "SESSION-1"}
    assert charger.session is None
    assert hass.states.get(entity_id).state == "off"


async def test_rejected_start_raises_error(hass, http):
    # the first matching route wins, so register the rejection first
    http.add("POST", "session/start", FakeResponse(400, text="bad request"))
    FakeCharger(http)
    await setup_entry(hass, make_entry())

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": switch_id(hass)},
            blocking=True,
        )


# ----------------------------------------------------------------------
# Tokens
# ----------------------------------------------------------------------


def rotating_token_route(http, refresh="refresh-NEW"):
    http.add(
        "POST",
        "openid-connect/token",
        FakeResponse(
            200,
            {
                "access_token": make_jwt(FAR_FUTURE),
                "refresh_token": refresh,
            },
        ),
    )


async def test_rotated_refresh_token_is_stored(hass, http):
    """A reused refresh token is rejected by DKV, so it must be saved."""
    FakeCharger(http)
    rotating_token_route(http)
    entry = make_entry(access_token=None)

    await setup_entry(hass, entry)

    assert entry.data["refresh_token"] == "refresh-NEW"
    assert entry.data["access_token"]


async def test_rotated_token_is_stored_even_if_status_fails(hass, http):
    rotating_token_route(http)
    http.add("GET", "charge-points", FakeResponse(503))
    entry = make_entry(access_token=None)

    await setup_entry(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.data["refresh_token"] == "refresh-NEW"


async def test_dead_refresh_token_starts_reauth(hass, http):
    http.add(
        "POST",
        "openid-connect/token",
        FakeResponse(400, text='{"error":"invalid_grant"}'),
    )
    entry = make_entry(access_token=None)

    await setup_entry(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == [
        config_entries.SOURCE_REAUTH
    ]


async def test_reauth_with_new_login_reloads_entry(hass, http):
    http.add(
        "POST",
        "openid-connect/token",
        FakeResponse(400, text='{"error":"invalid_grant"}'),
    )
    entry = make_entry(access_token=None)
    await setup_entry(hass, entry)
    flow = hass.config_entries.flow.async_progress_by_handler(DOMAIN)[0]

    # DKV now accepts the new code
    http.reset_routes()
    FakeCharger(http)
    rotating_token_route(http, refresh="refresh-after-login")
    http.add("GET", "userinfo", FakeResponse(200, {"preferred_username": USER}))

    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        {
            "token_input": (
                "com.dkv-mobility.app://oauth2redirect?state=s&code=new-code"
            )
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["refresh_token"] == "refresh-after-login"
    assert entry.state is ConfigEntryState.LOADED
