"""Tests for the connection sensor and the repair notice for a lasting block."""

from datetime import timedelta

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
)
from test_integration import FakeCharger, make_entry, next_poll, setup_entry

from custom_components.dkv_at_home.const import DOMAIN

USER = "100000000001"
ISSUE = "dkv_blocked"


def connection_id(hass):
    return er.async_get(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, f"dkv_at_home_{USER}_connection"
    )


async def poll_after(hass, delta):
    """Let the poll run that is due ``delta`` from now."""
    async_fire_time_changed(hass, dt_util.utcnow() + delta)
    await hass.async_block_till_done()


async def test_connection_is_on_after_a_good_poll(hass, http):
    FakeCharger(http)
    await setup_entry(hass, make_entry())

    state = hass.states.get(connection_id(hass))
    assert state.state == "on"
    assert state.attributes["device_class"] == "connectivity"
    assert state.attributes["last_success"]
    assert state.attributes["last_error"] is None


async def test_connection_names_the_error_and_never_turns_unavailable(
    hass, http
):
    charger = FakeCharger(http)
    await setup_entry(hass, make_entry())
    good_time = hass.states.get(connection_id(hass)).attributes["last_success"]

    charger.status_error = "blocked"
    await next_poll(hass)

    state = hass.states.get(connection_id(hass))
    # "off" with the reason: the information must not vanish with the failure
    assert state.state == "off"
    assert state.attributes["last_error"] == "blocked"
    assert state.attributes["last_success"] == good_time


async def test_connection_error_class_never_holds_secrets(hass, http):
    charger = FakeCharger(http)
    await setup_entry(hass, make_entry())

    charger.status_error = "blocked"
    await next_poll(hass)

    attributes = hass.states.get(connection_id(hass)).attributes
    text = str(dict(attributes))
    for secret in ("http", "Reference", "Bearer", USER):
        assert secret not in text, secret


async def test_a_lasting_block_creates_a_repair_notice_and_recovery_removes_it(
    hass, http
):
    charger = FakeCharger(http, session="SESSION-1")
    await setup_entry(hass, make_entry())
    registry = ir.async_get(hass)

    charger.status_error = "blocked"
    await next_poll(hass)  # block 1 (next poll in 5 minutes)
    assert registry.async_get_issue(DOMAIN, ISSUE) is None
    await poll_after(hass, timedelta(minutes=6))  # block 2 (then 15 minutes)
    assert registry.async_get_issue(DOMAIN, ISSUE) is None

    await poll_after(hass, timedelta(minutes=22))  # block 3: through all steps
    issue = registry.async_get_issue(DOMAIN, ISSUE)
    assert issue is not None
    assert issue.translation_key == ISSUE
    assert issue.is_fixable is False

    charger.status_error = None
    await poll_after(hass, timedelta(minutes=90))  # the hourly poll
    assert registry.async_get_issue(DOMAIN, ISSUE) is None
    state = hass.states.get(connection_id(hass))
    assert state.state == "on"
    assert state.attributes["last_error"] is None
