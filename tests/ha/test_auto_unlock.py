"""Tests for the automatic unlock when a vehicle is connected."""

from datetime import timedelta
from unittest.mock import patch

from helpers import FakeResponse
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)
from test_integration import (
    FakeCharger,
    let_refresh_run,
    make_entry,
    next_poll,
    setup_entry,
    switch_id,
)

from custom_components.dkv_at_home.const import (
    CONF_CONNECTED_ENTITY,
    EVENT_UNLOCK_FAILED,
    UNLOCK_MAX_ATTEMPTS,
    UNLOCK_RETRY_SECONDS,
)

CAR = "binary_sensor.car_connected"
OPTIONS = {CONF_CONNECTED_ENTITY: CAR}


async def retry_pause(hass):
    """Let the pause between two unlock attempts pass."""
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=UNLOCK_RETRY_SECONDS + 1)
    )
    await hass.async_block_till_done()


async def connect_car(hass):
    hass.states.async_set(CAR, "on")
    await hass.async_block_till_done()


async def test_unlocks_when_the_car_connects(hass, http):
    charger = FakeCharger(http)
    hass.states.async_set(CAR, "off")
    await setup_entry(hass, make_entry(options=OPTIONS))

    await connect_car(hass)
    await let_refresh_run(hass)

    assert charger.start_calls == 1
    assert charger.session == "SESSION-1"
    assert hass.states.get(switch_id(hass)).state == "on"


async def test_unlocks_at_startup_when_the_car_is_already_connected(hass, http):
    charger = FakeCharger(http)
    hass.states.async_set(CAR, "on")

    await setup_entry(hass, make_entry(options=OPTIONS))

    assert charger.start_calls == 1


async def test_does_not_start_a_second_session(hass, http):
    charger = FakeCharger(http, session="SESSION-1")
    hass.states.async_set(CAR, "off")
    await setup_entry(hass, make_entry(options=OPTIONS))

    await connect_car(hass)

    assert charger.start_calls == 0


async def test_nothing_happens_without_the_option(hass, http):
    charger = FakeCharger(http)
    hass.states.async_set(CAR, "off")
    await setup_entry(hass, make_entry())

    await connect_car(hass)

    assert charger.start_calls == 0


async def test_retries_until_the_wallbox_confirms(hass, http):
    """DKV only confirms while the wallbox may charge; keep trying."""
    charger = FakeCharger(http, confirm_from=3)
    hass.states.async_set(CAR, "off")
    await setup_entry(hass, make_entry(options=OPTIONS))

    await connect_car(hass)
    assert charger.session is None
    await retry_pause(hass)
    assert charger.session is None
    await retry_pause(hass)

    assert charger.start_calls == 3
    assert charger.session == "SESSION-1"


async def test_gives_up_with_event_and_notification(hass, http):
    charger = FakeCharger(http, confirms=False)
    events = async_capture_events(hass, EVENT_UNLOCK_FAILED)
    hass.states.async_set(CAR, "off")
    await setup_entry(hass, make_entry(options=OPTIONS))

    with patch(
        "custom_components.dkv_at_home.unlock.persistent_notification"
    ) as notification:
        await connect_car(hass)
        for _ in range(UNLOCK_MAX_ATTEMPTS):
            await retry_pause(hass)

    assert charger.start_calls == UNLOCK_MAX_ATTEMPTS
    assert len(events) == 1
    assert events[0].data["attempts"] == UNLOCK_MAX_ATTEMPTS
    notification.async_create.assert_called_once()

    # it stopped: further time changes start nothing
    await retry_pause(hass)
    assert charger.start_calls == UNLOCK_MAX_ATTEMPTS


async def test_disconnecting_the_car_cancels_the_retries(hass, http):
    charger = FakeCharger(http, confirms=False)
    hass.states.async_set(CAR, "off")
    await setup_entry(hass, make_entry(options=OPTIONS))

    await connect_car(hass)
    assert charger.start_calls == 1
    hass.states.async_set(CAR, "off")
    await hass.async_block_till_done()
    await retry_pause(hass)

    assert charger.start_calls == 1


async def test_unavailable_sensor_does_not_cancel_the_retries(hass, http):
    """evcc restarting must not end the attempts."""
    charger = FakeCharger(http, confirm_from=2)
    hass.states.async_set(CAR, "off")
    await setup_entry(hass, make_entry(options=OPTIONS))

    await connect_car(hass)
    hass.states.async_set(CAR, "unavailable")
    await hass.async_block_till_done()
    await retry_pause(hass)

    assert charger.start_calls == 2
    assert charger.session == "SESSION-1"


async def test_a_dead_login_stops_the_attempts(hass, http):
    charger = FakeCharger(http)
    hass.states.async_set(CAR, "off")
    await setup_entry(hass, make_entry(options=OPTIONS))
    http.add(
        "POST",
        "openid-connect/token",
        FakeResponse(400, text='{"error":"invalid_grant"}'),
    )

    charger.status_error = "auth"
    await connect_car(hass)
    await retry_pause(hass)

    assert charger.start_calls == 0


async def test_token_updates_do_not_reload_the_entry(hass, http):
    """The token is written back regularly; that must not reload the entry."""
    from helpers import make_jwt

    FakeCharger(http)
    http.add(
        "POST",
        "openid-connect/token",
        FakeResponse(
            200,
            {
                "access_token": make_jwt(4102444800),
                "refresh_token": "refresh-NEW",
            },
        ),
    )
    entry = make_entry(access_token=None, options=OPTIONS)
    hass.states.async_set(CAR, "off")

    with patch.object(
        hass.config_entries, "async_reload", wraps=hass.config_entries.async_reload
    ) as reload:
        await setup_entry(hass, entry)
        await next_poll(hass)

    assert entry.data["refresh_token"] == "refresh-NEW"
    reload.assert_not_called()


async def test_choosing_the_sensor_in_the_options(hass, http):
    FakeCharger(http)
    entry = make_entry()
    await setup_entry(hass, entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CONNECTED_ENTITY: CAR}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_CONNECTED_ENTITY: CAR}
    assert entry.state is ConfigEntryState.LOADED  # reloaded with the option


async def test_clearing_the_sensor_switches_the_feature_off(hass, http):
    charger = FakeCharger(http)
    hass.states.async_set(CAR, "off")
    entry = make_entry(options=OPTIONS)
    await setup_entry(hass, entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    await connect_car(hass)

    assert entry.options == {}
    assert charger.start_calls == 0
