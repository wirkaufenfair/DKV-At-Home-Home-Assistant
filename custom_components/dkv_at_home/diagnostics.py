"""Diagnostics for DKV@Home.

The download (device page -> Download diagnostics) is meant for bug reports.
It shows versions, state and the *structure* of DKV's answers (keys and
types), but never tokens, account numbers or any ids from the answers.
"""

import time
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .api import DkvApiClient, describe_shape
from .const import DOMAIN

TO_REDACT = {"refresh_token", "access_token", "preferred_username"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    integration = await async_get_integration(hass, DOMAIN)
    runtime = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime["coordinator"]
    client = runtime["client"]

    expires_at = DkvApiClient._decode_jwt_exp(client.access_token)
    refresh_claims = DkvApiClient._decode_jwt_claims(client.refresh_token)
    interval = coordinator.update_interval

    data = coordinator.data
    charge_point: dict[str, Any] | None = None
    if isinstance(data, dict):
        charge_point = {
            "status": data.get("status"),
            "has_active_session": data.get("activeSessionId") is not None,
            "remote_start_stop_capable": data.get("remoteStartStopCapable"),
            "structure": describe_shape(data),
        }

    return {
        "integration_version": integration.version,
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval_seconds": (
                interval.total_seconds() if interval else None
            ),
        },
        "tokens": {
            "refresh_token_type": refresh_claims.get("typ"),
            "access_token_seconds_left": (
                max(0, expires_at - int(time.time())) if expires_at else None
            ),
        },
        "charge_point": charge_point,
    }
