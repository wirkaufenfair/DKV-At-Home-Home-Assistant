"""Tests for the auto-unlock blueprint against the fake DKV server.

The blueprint is loaded from the repository into the test configuration,
instantiated like a user does it, and run with a fake charge point that
only confirms the start from a given attempt on.

The blueprint really waits between two attempts, and the automation keeps
running while it waits. So the tests must not wait for it to finish; they
trigger it, let the pause pass by moving the clock, and look at the result.
"""

import asyncio
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


@pytest.fixture(autouse=True)
async def stop_automations(hass):
    """A run that waits in its pause would be a lingering timer."""
    yield
    if hass.services.has_service("automation", "turn_off"):
        await hass.services.async_call(
            "automation", "turn_off", {"entity_id": "all"}, blocking=True
        )
        await hass.async_block_till_done()


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


def let_the_pause_pass(hass):
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=DELAY + 1))


async def until(hass, condition, *, pause_passes=False):
    """Wait (a few seconds at most) until ``condition`` holds.

    With ``pause_passes`` the clock is moved on in every round, so the
    blueprint's pause between two attempts ends.
    """
    for _ in range(200):
        if condition():
            return
        if pause_passes:
            let_the_pause_pass(hass)
        await asyncio.sleep(0.02)
    raise AssertionError("the expected state was not reached")


async def test_unlocks_when_the_car_connects(hass, http):
    charger = FakeCharger(http)
    hass.states.async_set(CAR, "off")
    await setup_entry(hass, make_entry())
    await setup_blueprint(hass)

    hass.states.async_set(CAR, "on")
    await until(hass, lambda: hass.states.get(switch_id(hass)).state == "on", pause_passes=True)

    assert charger.start_calls == 1
    assert charger.session == "SESSION-1"


async def test_does_not_start_a_second_session(hass, http):
    charger = FakeCharger(http, session="SESSION-1")
    hass.states.async_set(CAR, "off")
    await setup_entry(hass, make_entry())
    await setup_blueprint(hass)

    hass.states.async_set(CAR, "on")
    await hass.async_block_till_done()  # ends at once: the switch is already on

    assert charger.start_calls == 0


async def test_retries_until_the_wallbox_confirms(hass, http):
    """DKV only confirms while the wallbox may charge; keep trying."""
    charger = FakeCharger(http, confirm_from=3)
    hass.states.async_set(CAR, "off")
    await setup_entry(hass, make_entry())
    await setup_blueprint(hass, attempts=5)
    failed = async_capture_events(hass, FAILED_EVENT)

    hass.states.async_set(CAR, "on")
    await until(hass, lambda: charger.session == "SESSION-1", pause_passes=True)
    # it stops at the first confirmation, it does not use up all attempts
    await until(hass, lambda: hass.states.get(switch_id(hass)).state == "on", pause_passes=True)

    assert charger.start_calls == 3
    assert failed == []


async def test_waits_between_the_attempts(hass, http):
    """Without the pause passing, only the first attempt happens."""
    charger = FakeCharger(http, confirms=False)
    hass.states.async_set(CAR, "off")
    await setup_entry(hass, make_entry())
    await setup_blueprint(hass, attempts=5)

    hass.states.async_set(CAR, "on")
    await until(hass, lambda: charger.start_calls == 1)
    await asyncio.sleep(0.3)  # real time: the 30 second pause has not passed

    assert charger.start_calls == 1


async def test_gives_up_and_runs_the_failure_actions(hass, http):
    charger = FakeCharger(http, confirms=False)
    hass.states.async_set(CAR, "off")
    await setup_entry(hass, make_entry())
    await setup_blueprint(hass, attempts=3)
    failed = async_capture_events(hass, FAILED_EVENT)

    hass.states.async_set(CAR, "on")
    await until(hass, lambda: len(failed) == 1, pause_passes=True)

    assert charger.start_calls == 3


async def test_unplugging_the_car_ends_the_attempts(hass, http):
    charger = FakeCharger(http, confirms=False)
    hass.states.async_set(CAR, "off")
    await setup_entry(hass, make_entry())
    await setup_blueprint(hass, attempts=5)
    failed = async_capture_events(hass, FAILED_EVENT)

    hass.states.async_set(CAR, "on")
    await until(hass, lambda: charger.start_calls == 1)
    hass.states.async_set(CAR, "off")  # during the pause
    await hass.async_block_till_done()
    for _ in range(5):
        let_the_pause_pass(hass)
        await asyncio.sleep(0.05)

    assert charger.start_calls == 1
    assert failed == []


async def test_nothing_happens_while_no_car_is_connected(hass, http):
    charger = FakeCharger(http)
    hass.states.async_set(CAR, "off")
    await setup_entry(hass, make_entry())
    await setup_blueprint(hass)

    hass.states.async_set(CAR, "unavailable")
    await hass.async_block_till_done()
    let_the_pause_pass(hass)
    await hass.async_block_till_done()

    assert charger.start_calls == 0
