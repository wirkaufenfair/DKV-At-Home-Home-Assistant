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
from .entity import device_info


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
        self._attr_device_info = device_info(username)

    @property
    def available(self) -> bool:
        """Always available: the failure is the information."""
        return True

    @property
    def is_on(self) -> bool:
        """True when the last poll of DKV worked without any error.

        A short outage at DKV keeps the last data (the switch stays usable),
        but it is still an error: the sensor shows it as "off" with the
        reason instead of claiming everything is fine.
        """
        return bool(
            self.coordinator.last_update_success
            and self._status.get("last_error") is None
        )

    @property
    def extra_state_attributes(self) -> dict:
        """What went wrong, and when the last poll worked before that.

        ``last_success`` is only set while the sensor is "off". While it is
        "on" it would change at every poll and write a new state (and a
        database row) every 30 seconds for no use.
        """
        last_success = self._status.get("last_success")
        return {
            "last_success": (
                last_success.isoformat()
                if last_success and not self.is_on
                else None
            ),
            # a class ("blocked", "auth", "transient", "api", "unexpected"),
            # never a URL, a token or an account number
            "last_error": self._status.get("last_error"),
        }
