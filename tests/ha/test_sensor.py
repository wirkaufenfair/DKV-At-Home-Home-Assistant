"""Tests for the consumption and reimbursement sensors."""

from homeassistant.helpers import entity_registry as er
from test_integration import FakeCharger, make_entry, next_poll, setup_entry

from custom_components.dkv_at_home.const import DOMAIN

USER = "100000000001"
REIMBURSEMENT = {"consumption": 18.01, "sum": 5.02, "currencyIsoCode": "EUR"}


def sensor_id(hass, key):
    return er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"dkv_at_home_{USER}_{key}"
    )


async def test_sensors_show_what_dkv_reports(hass, http):
    charger = FakeCharger(http)
    charger.reimbursement = REIMBURSEMENT
    await setup_entry(hass, make_entry())

    consumption = hass.states.get(sensor_id(hass, "consumption"))
    assert consumption.state == "18.01"
    assert consumption.attributes["unit_of_measurement"] == "kWh"
    assert consumption.attributes["device_class"] == "energy"
    assert consumption.attributes["state_class"] == "total_increasing"

    money = hass.states.get(sensor_id(hass, "reimbursement"))
    assert money.state == "5.02"
    assert money.attributes["unit_of_measurement"] == "EUR"
    assert money.attributes["device_class"] == "monetary"
    assert "state_class" not in money.attributes


async def test_sensors_sit_on_the_device_of_the_switch(hass, http):
    charger = FakeCharger(http)
    charger.reimbursement = REIMBURSEMENT
    await setup_entry(hass, make_entry())

    registry = er.async_get(hass)
    switch = registry.async_get(
        registry.async_get_entity_id("switch", DOMAIN, f"dkv_at_home_{USER}")
    )
    sensor = registry.async_get(sensor_id(hass, "consumption"))
    assert sensor.device_id == switch.device_id


async def test_sensors_follow_the_poll(hass, http):
    charger = FakeCharger(http)
    charger.reimbursement = REIMBURSEMENT
    await setup_entry(hass, make_entry())

    charger.reimbursement = {**REIMBURSEMENT, "consumption": 30.5, "sum": 8.5}
    await next_poll(hass)

    assert hass.states.get(sensor_id(hass, "consumption")).state == "30.5"
    assert hass.states.get(sensor_id(hass, "reimbursement")).state == "8.5"


async def test_sensors_are_unknown_without_numbers(hass, http):
    """DKV leaves out or garbles the values: no crash, state unknown."""
    charger = FakeCharger(http)
    charger.reimbursement = {"consumption": None, "sum": "x"}
    await setup_entry(hass, make_entry())

    assert hass.states.get(sensor_id(hass, "consumption")).state == "unknown"
    assert hass.states.get(sensor_id(hass, "reimbursement")).state == "unknown"
