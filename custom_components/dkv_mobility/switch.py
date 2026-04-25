"""Switch platform for DKV Mobility (wallbox remote start)."""

# pylint: disable=import-error

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import DkvApiClient, DkvApiError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DKV Mobility switch from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            DkvChargingSwitch(
                coordinator=data["coordinator"],
                client=data["client"],
                persist_tokens=data["persist_tokens"],
                entry=entry,
            )
        ],
        update_before_add=True,
    )


class DkvChargingSwitch(CoordinatorEntity, SwitchEntity):
    """Switch that starts a DKV Mobility charging session.

    State is derived from ``activeSessionId`` on the charge point:
    - **On**  – a session is confirmed and active.
    - **Off** – no active session.

    Turning off is not supported by the DKV API; evcc or the DKV app
    must be used to stop charging.
    """

    _attr_icon = "mdi:ev-station"
    _attr_has_entity_name = True
    _attr_name = "Ladevorgang"

    def __init__(
        self,
        coordinator,
        client: DkvApiClient,
        persist_tokens,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._persist_tokens = persist_tokens
        self._entry = entry
        username = entry.data["preferred_username"]
        self._attr_unique_id = f"dkv_mobility_{username}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, username)},
            "name": "DKV Wallbox",
            "manufacturer": "DKV Mobility",
            "model": "At-Home Charger",
        }

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def is_on(self) -> bool | None:
        """Return True when an active charging session exists."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("activeSessionId") is not None

    @property
    def extra_state_attributes(self) -> dict:
        """Expose charge-point status and session ID as attributes."""
        if self.coordinator.data is None:
            return {}
        return {
            "charge_point_status": self.coordinator.data.get("status"),
            "active_session_id": self.coordinator.data.get("activeSessionId"),
            "charge_point_name": self.coordinator.data.get("name"),
        }

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def async_turn_on(self, **kwargs) -> None:
        """Start a charging session."""
        try:
            session_id: str | None = await self.hass.async_add_executor_job(
                self._client.start
            )
        except DkvApiError as err:
            raise HomeAssistantError(str(err)) from err
        except Exception as err:
            raise HomeAssistantError(
                f"Unerwarteter Fehler beim Starten: {err}"
            ) from err
        finally:
            # Always persist the refreshed tokens, even on failure.
            self._persist_tokens()

        if session_id is None:
            raise HomeAssistantError(
                "Ladevorgang wurde vom DKV-Backend angenommen, aber die "
                "Wallbox hat ihn nicht innerhalb des Zeitlimits bestätigt."
            )

        _LOGGER.info("DKV Wallbox gestartet – activeSessionId: %s", session_id)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        """Stop is not supported via the DKV API."""
        raise HomeAssistantError(
            "Stoppen wird von der DKV API nicht unterstützt. "
            "Bitte evcc oder die DKV App verwenden."
        )
