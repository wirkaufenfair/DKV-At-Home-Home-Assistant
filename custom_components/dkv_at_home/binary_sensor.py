"""Connection sensor for DKV@Home.

Shows whether the last poll of DKV worked, so dashboards and automations can
react without reading texts: ``on`` = the last poll worked, ``off`` = it did
not. In contrast to the switch and the sensors it never turns ``unavailable``:
a diagnosis that disappears exactly when it is needed would be of no use.
"""

# pyright: reportMissingImports=false, reportMissingModuleSource=false

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the DKV@Home connection sensor from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [DkvConnectionSensor(data["coordinator"], entry, data["status"])]
    )


class DkvConnectionSensor(CoordinatorEntity, BinarySensorEntity):
    """On while the polls of DKV work."""

    _attr_has_entity_name = True
    _attr_name = "Verbindung zu DKV"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry: ConfigEntry, status: dict) -> None:
        super().__init__(coordinator)
        self._status = status
        username = entry.data["preferred_username"]
        self._attr_unique_id = f"dkv_at_home_{username}_connection"
        # Same device as the switch (identifiers must match exactly).
        self._attr_device_info = {
            "identifiers": {(DOMAIN, username)},
            "name": "DKV@Home Wallbox",
            "manufacturer": "DKV@Home",
            "model": "At-Home Charger",
        }

    @property
    def available(self) -> bool:
        """Always available: the failure is the information."""
        return True

    @property
    def is_on(self) -> bool:
        """True when the last poll of DKV worked."""
        return bool(self.coordinator.last_update_success)

    @property
    def extra_state_attributes(self) -> dict:
        """When the last poll worked and what went wrong since."""
        last_success = self._status.get("last_success")
        return {
            "last_success": (
                last_success.isoformat() if last_success else None
            ),
            # a class ("blocked", "auth", "transient", "api", "unexpected"),
            # never a URL, a token or an account number
            "last_error": self._status.get("last_error"),
        }
