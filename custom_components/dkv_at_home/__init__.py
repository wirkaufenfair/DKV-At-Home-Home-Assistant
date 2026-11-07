"""DKV@Home Home Assistant integration."""


import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry  # type: ignore[import]
from homeassistant.core import HomeAssistant  # type: ignore[import]
from homeassistant.exceptions import (  # type: ignore[import]
    ConfigEntryAuthFailed,
)
from homeassistant.helpers.update_coordinator import (  # type: ignore[import]
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import DkvApiClient, DkvApiError, DkvAuthError, DkvTransientError
from .const import CONF_CONNECTED_ENTITY, DOMAIN, POLL_INTERVAL_SECONDS
from .unlock import AutoUnlock

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["switch"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up DKV@Home from a config entry."""
    client = DkvApiClient(
        refresh_token=entry.data["refresh_token"],
        app_token=entry.data["preferred_username"],
        access_token=entry.data.get("access_token"),
    )

    def _persist_tokens() -> None:
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                "refresh_token": client.refresh_token,
                "access_token": client.access_token,
            },
        )

    async def async_update_data() -> dict:
        try:
            return await hass.async_add_executor_job(client.fetch_status)
        except DkvAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except DkvTransientError as err:
            # Temporary backend outage – keep last known state and log only
            # a warning so the error log is not flooded during downtime.
            _LOGGER.warning(
                "DKV-Backend vorübergehend nicht erreichbar: %s", err
            )
            if coordinator.data is not None:
                return coordinator.data
            raise UpdateFailed(str(err)) from err
        except DkvApiError as err:
            raise UpdateFailed(str(err)) from err
        except Exception as err:
            raise UpdateFailed(f"Unerwarteter Fehler: {err}") from err
        finally:
            # Always persist tokens so that a newly-rotated refresh_token
            # is saved even when the subsequent API call fails.  Without
            # this, a HA restart after a failed poll would reload the
            # already-consumed (old) refresh token, causing invalid_grant.
            _persist_tokens()

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=timedelta(seconds=POLL_INTERVAL_SECONDS),
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "client": client,
        "persist_tokens": _persist_tokens,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    connected_entity = entry.options.get(CONF_CONNECTED_ENTITY)
    if connected_entity:
        auto_unlock = AutoUnlock(
            hass, connected_entity, client, coordinator, _persist_tokens
        )
        auto_unlock.async_start()
        entry.async_on_unload(auto_unlock.async_stop)

    # Home Assistant calls update listeners on every change of the entry,
    # including the token written back every few minutes. Reload only when
    # the options changed, otherwise the entry would reload constantly.
    options_at_setup = dict(entry.options)

    async def _async_options_updated(
        hass: HomeAssistant, updated: ConfigEntry
    ) -> None:
        if dict(updated.options) != options_at_setup:
            await hass.config_entries.async_reload(updated.entry_id)

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry,
        PLATFORMS,
    )
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
