"""The block state over a restart, and a block at the very start."""

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
)
from test_integration import FakeCharger, make_entry, setup_entry, switch_id

from custom_components.dkv_at_home import block_store_key
from custom_components.dkv_at_home.const import DOMAIN
from custom_components.dkv_at_home.diagnostics import (
    async_get_config_entry_diagnostics,
)

ISSUE = "dkv_blocked"


def save_block(hass_storage, entry, polls, wait):
    """What the integration wrote before the restart."""
    key = block_store_key(entry.entry_id)
    until = dt_util.utcnow() + wait
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {"blocked_polls": polls, "blocked_until": until.isoformat()},
    }


async def test_a_block_at_the_start_does_not_end_in_setup_retry(
    hass, http, hass_storage
):
    """No endless "setup is retried": the entry is set up, entities unavailable."""
    charger = FakeCharger(http)
    charger.status_error = "blocked"
    entry = make_entry()

    await setup_entry(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(switch_id(hass)).state == "unavailable"
    key = block_store_key(entry.entry_id)
    assert hass_storage[key]["data"]["blocked_polls"] == 1
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    assert coordinator.update_interval == timedelta(minutes=5)
    # one request at the start, not one more from adding the entities
    assert len(http.calls_to("GET", "charge-points")) == 1


async def test_a_restart_during_the_wait_does_not_ask_dkv(hass, http, hass_storage):
    FakeCharger(http, session="SESSION-1")
    entry = make_entry()
    entry.add_to_hass(hass)
    save_block(hass_storage, entry, polls=2, wait=timedelta(minutes=10))

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.state is ConfigEntryState.LOADED
    assert http.calls_to("GET", "charge-points") == []  # nothing asked yet
    assert hass.states.get(switch_id(hass)).state == "unavailable"
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    assert timedelta(minutes=9) < coordinator.update_interval <= timedelta(minutes=10)

    # when the wait is over, the poll comes and works
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=11))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(http.calls_to("GET", "charge-points")) == 1
    assert hass.states.get(switch_id(hass)).state == "on"
    # still careful after one good answer
    assert coordinator.update_interval == timedelta(minutes=5)


async def test_a_lasting_block_shows_the_notice_again_after_a_restart(
    hass, http, hass_storage
):
    """Repair notices are not kept over a restart: it must come back."""
    FakeCharger(http)
    entry = make_entry()
    entry.add_to_hass(hass)
    save_block(hass_storage, entry, polls=3, wait=timedelta(minutes=30))

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE) is not None


async def test_an_old_block_state_does_not_hold_back_the_start(
    hass, http, hass_storage
):
    """The wait is over: the start asks DKV right away."""
    FakeCharger(http, session="SESSION-1")
    entry = make_entry()
    entry.add_to_hass(hass)
    save_block(hass_storage, entry, polls=2, wait=timedelta(minutes=-5))

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert len(http.calls_to("GET", "charge-points")) == 1
    assert hass.states.get(switch_id(hass)).state == "on"


async def test_unreadable_block_state_means_start_carefully(
    hass, http, hass_storage
):
    """"Unknown" must never mean "not blocked": wait the first step."""
    FakeCharger(http, session="SESSION-1")
    entry = make_entry()
    entry.add_to_hass(hass)
    key = block_store_key(entry.entry_id)
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {"blocked_polls": "many", "blocked_until": 12345},
    }

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.state is ConfigEntryState.LOADED  # it still starts
    assert http.calls_to("GET", "charge-points") == []  # but does not ask yet
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    assert coordinator.update_interval <= timedelta(minutes=5)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(switch_id(hass)).state == "on"


async def test_a_clock_that_jumped_back_does_not_make_the_wait_endless(
    hass, http, hass_storage
):
    FakeCharger(http)
    entry = make_entry()
    entry.add_to_hass(hass)
    save_block(hass_storage, entry, polls=3, wait=timedelta(hours=7))

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    assert coordinator.update_interval <= timedelta(hours=1)


async def test_entities_set_up_during_a_block_wake_up_without_a_reload(
    hass, http, hass_storage
):
    """Not "set up, but dead for ever": the first good poll brings them back."""
    charger = FakeCharger(http, session="SESSION-1")
    charger.status_error = "blocked"
    entry = make_entry()
    await setup_entry(hass, entry)
    assert hass.states.get(switch_id(hass)).state == "unavailable"

    charger.status_error = None
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.state is ConfigEntryState.LOADED
    state = hass.states.get(switch_id(hass))
    assert state.state == "on"
    assert state.attributes["charge_point_status"] == "CHARGING"


async def test_nothing_reads_the_missing_data_of_a_block_at_the_start(
    hass, http, hass_storage
):
    """Entities and diagnostics must cope with ``coordinator.data = None``."""
    charger = FakeCharger(http)
    charger.status_error = "blocked"
    entry = make_entry()
    await setup_entry(hass, entry)

    assert hass.data[DOMAIN][entry.entry_id]["coordinator"].data is None
    assert hass.states.get(switch_id(hass)).state == "unavailable"
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["charge_point"] is None
    assert result["coordinator"]["last_update_success"] is False


async def test_a_short_rest_does_not_become_the_rhythm_after_a_failed_poll(
    hass, http, hass_storage
):
    """A restart shortly before the end of the wait must not mean "every 10 s"."""
    charger = FakeCharger(http)
    charger.status_error = "empty"  # DKV answers, but not with a charge point
    entry = make_entry()
    entry.add_to_hass(hass)
    save_block(hass_storage, entry, polls=1, wait=timedelta(seconds=10))

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    assert coordinator.update_interval <= timedelta(seconds=10)

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=20))
    await hass.async_block_till_done(wait_background_tasks=True)

    assert len(http.calls_to("GET", "charge-points")) == 1  # the poll failed
    assert coordinator.update_interval == timedelta(minutes=5)
