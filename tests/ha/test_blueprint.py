"""Tests for the auto-unlock blueprint against the fake DKV server.

The blueprint is loaded from the repository into the test configuration,
instantiated like a user does it, and run with a fake charge point that
only confirms the start from a given attempt on.
"""

import shutil
from datetime import timedelta
from pathlib import Path

import pytest
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)
from test_integration import FakeCharger, make_entry, setup_entry, switch_id

ROOT = Path(__file__).resolve().parent.parent.parent
BLUEPRINT = ROOT / "blueprints" / "automation" / "dkv_at_home" / "auto_unlock.yaml"

CAR = "binary_sensor.car_connected"
FAILED_EVENT = "dkv_test_unlock_failed"
DELAY = 30


@pytest.fixture(autouse=True)
def blueprint_installed(hass):
    """Put the blueprint where Home Assistant looks for it."""
    target = Path(hass.config.path("blueprints/automation/dkv_at_home/auto_unlock.yaml"))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(BLUEPRINT, target)


async def setup_blueprint(hass, attempts=3):
    """Create an automation from the blueprint, as the UI does."""
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                {
                    "alias": "DKV unlock",
                    "use_blueprint": {
                        "path": "dkv_at_home/auto_unlock.yaml",
                        "input": {
                            "vehicle_connected": CAR,
                            "dkv_switch": switch_id(hass),
                            "max_attempts": attempts,
                            "retry_delay": DELAY,
                            "on_failure": [{"event": FAILED_EVENT}],
                        },
                    },
                }
            ]
        },
    )
    await hass.async_block_till_done()


async def wait_between_attempts(hass):
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=DELAY + 1)
    )
    await hass.async_block_till_done()


async def connect_car(hass):
    hass.states.async_set(CAR, "on")
    await hass.async_block_till_done()


async def test_unlocks_when_the_car_connects(hass, http):
    charger = FakeCharger(http)
    hass.states.async_set(CAR, "off")
    await setup_entry(hass, make_entry())
    await setup_blueprint(hass)

    await connect_car(hass)
    await wait_between_attempts(hass)  # lets the state catch up

    assert charger.start_calls == 1
    assert charger.session == "SESSION-1"
    assert hass.states.get(switch_id(hass)).state == "on"


async def test_does_not_start_a_second_session(hass, http):
    charger = FakeCharger(http, session="SESSION-1")
    hass.states.async_set(CAR, "off")
    await setup_entry(hass, make_entry())
    await setup_blueprint(hass)

    await connect_car(hass)

    assert charger.start_calls == 0


async def test_retries_until_the_wallbox_confirms(hass, http):
    """DKV only confirms while the wallbox may charge; keep trying."""
    charger = FakeCharger(http, confirm_from=3)
    hass.states.async_set(CAR, "off")
    await setup_entry(hass, make_entry())
    await setup_blueprint(hass, attempts=5)
    failed = async_capture_events(hass, FAILED_EVENT)

    await connect_car(hass)
    assert charger.start_calls == 1
    await wait_between_attempts(hass)
    assert charger.start_calls == 2
    await wait_between_attempts(hass)
    await wait_between_attempts(hass)  # lets the state catch up

    assert charger.start_calls == 3
    assert charger.session == "SESSION-1"
    assert failed == []


async def test_gives_up_and_runs_the_failure_actions(hass, http):
    charger = FakeCharger(http, confirms=False)
    hass.states.async_set(CAR, "off")
    await setup_entry(hass, make_entry())
    await setup_blueprint(hass, attempts=3)
    failed = async_capture_events(hass, FAILED_EVENT)

    await connect_car(hass)
    for _ in range(2):
        await wait_between_attempts(hass)

    assert charger.start_calls == 3
    assert len(failed) == 1


async def test_unplugging_the_car_ends_the_attempts(hass, http):
    charger = FakeCharger(http, confirms=False)
    hass.states.async_set(CAR, "off")
    await setup_entry(hass, make_entry())
    await setup_blueprint(hass, attempts=5)
    failed = async_capture_events(hass, FAILED_EVENT)

    await connect_car(hass)
    assert charger.start_calls == 1
    hass.states.async_set(CAR, "off")
    await hass.async_block_till_done()
    await wait_between_attempts(hass)
    await wait_between_attempts(hass)

    assert charger.start_calls == 1
    assert failed == []


async def test_nothing_happens_while_no_car_is_connected(hass, http):
    charger = FakeCharger(http)
    hass.states.async_set(CAR, "off")
    await setup_entry(hass, make_entry())
    await setup_blueprint(hass)

    hass.states.async_set(CAR, "unavailable")
    await hass.async_block_till_done()
    await wait_between_attempts(hass)

    assert charger.start_calls == 0
