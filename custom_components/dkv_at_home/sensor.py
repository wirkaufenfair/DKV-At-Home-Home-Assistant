"""Sensor platform for DKV@Home (consumption and reimbursement).

DKV reports ``reimbursement`` on the charge point: a ``consumption`` and a
``sum`` in the currency ``currencyIsoCode``. The ratio on a live installation
(18.01 and 5.02 EUR) is about 0.28 per kWh, so ``consumption`` is read as
kWh and ``sum`` as money. DKV does not say which period the values cover, so
the sensors do not claim one (see CHANGELOG 1.3.0).
"""

# pyright: reportMissingImports=false, reportMissingModuleSource=false

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


@dataclass(frozen=True, kw_only=True)
class DkvSensorDescription(SensorEntityDescription):
    """A sensor that reads one value of ``reimbursement``."""

    reimbursement_key: str
    is_money: bool = False


SENSORS = (
    DkvSensorDescription(
        key="consumption",
        reimbursement_key="consumption",
        name="Verbrauch laut DKV",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        # DKV can reset the value (new period); HA treats a drop as a new
        # cycle for TOTAL_INCREASING.
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
    ),
    DkvSensorDescription(
        key="reimbursement",
        reimbursement_key="sum",
        name="Erstattung laut DKV",
        device_class=SensorDeviceClass.MONETARY,
        # No state class: the monetary class allows only TOTAL, and a reset
        # would then show up as a negative step in the statistics.
        suggested_display_precision=2,
        is_money=True,
    ),
)


def _reimbursement(data: dict | None) -> dict:
    """The ``reimbursement`` dict of the charge point, or an empty one."""
    if not isinstance(data, dict):
        return {}
    value = data.get("reimbursement")
    return value if isinstance(value, dict) else {}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the DKV@Home sensors from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        DkvReimbursementSensor(coordinator, entry, description)
        for description in SENSORS
    )


class DkvReimbursementSensor(CoordinatorEntity, SensorEntity):
    """Consumption or sum of ``reimbursement`` as reported by DKV."""

    entity_description: DkvSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator,
        entry: ConfigEntry,
        description: DkvSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        username = entry.data["preferred_username"]
        self._attr_unique_id = f"dkv_at_home_{username}_{description.key}"
        # Same device as the switch (identifiers must match exactly).
        self._attr_device_info = {
            "identifiers": {(DOMAIN, username)},
            "name": "DKV@Home Wallbox",
            "manufacturer": "DKV@Home",
            "model": "At-Home Charger",
        }

    @property
    def native_value(self) -> float | None:
        """The value, or None when DKV did not report a number."""
        value = _reimbursement(self.coordinator.data).get(
            self.entity_description.reimbursement_key
        )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    @property
    def native_unit_of_measurement(self) -> str | None:
        """kWh for consumption, the currency DKV reports for the sum."""
        if self.entity_description.is_money:
            currency = _reimbursement(self.coordinator.data).get(
                "currencyIsoCode"
            )
            return currency if isinstance(currency, str) else None
        return self.entity_description.native_unit_of_measurement
