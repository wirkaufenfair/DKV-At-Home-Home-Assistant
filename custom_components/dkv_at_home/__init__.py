"""DKV@Home Home Assistant integration."""


import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry  # type: ignore[import]
from homeassistant.core import HomeAssistant  # type: ignore[import]
from homeassistant.exceptions import (  # type: ignore[import]
    ConfigEntryAuthFailed,
)
from homeassistant.helpers import issue_registry as ir  # type: ignore[import]
from homeassistant.helpers.update_coordinator import (  # type: ignore[import]
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util  # type: ignore[import]

from .api import (
    DkvApiClient,
    DkvApiError,
    DkvAuthError,
    DkvBlockedError,
    DkvTransientError,
)
from .const import DOMAIN, POLL_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["switch", "sensor", "binary_sensor"]

# After a block by the shield in front of DKV (HTTP 403) the status poll
# slows down step by step instead of asking every 30 seconds: asking on
# keeps such a block alive. The first success brings the normal rhythm back.
BLOCKED_POLL_STEPS = (
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
)

# A block that lasts through every step (the third one in a row) is no longer
# a hiccup: Home Assistant shows a repair notice so a human sees it.
BLOCKED_ISSUE_ID = "dkv_blocked"
BLOCKED_ISSUE_AFTER = len(BLOCKED_POLL_STEPS)


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

    blocked_polls = 0
    # What the connection sensor shows: when the last poll worked and what
    # went wrong since (a class like "blocked", never URLs or tokens).
    status: dict = {"last_success": None, "last_error": None}

    async def async_update_data() -> dict:
        nonlocal blocked_polls
        try:
            data = await hass.async_add_executor_job(client.fetch_status)
            status["last_success"] = dt_util.utcnow()
            status["last_error"] = None
            if blocked_polls:
                blocked_polls = 0
                coordinator.update_interval = timedelta(
                    seconds=POLL_INTERVAL_SECONDS
                )
                ir.async_delete_issue(hass, DOMAIN, BLOCKED_ISSUE_ID)
            return data
        except DkvAuthError as err:
            status["last_error"] = "auth"
            raise ConfigEntryAuthFailed(str(err)) from err
        except DkvTransientError as err:
            # Temporary backend outage – keep last known state and log only
            # a warning so the error log is not flooded during downtime.
            status["last_error"] = "transient"
            _LOGGER.warning(
                "DKV-Backend vorübergehend nicht erreichbar: %s", err
            )
            if coordinator.data is not None:
                return coordinator.data
            raise UpdateFailed(str(err)) from err
        except DkvBlockedError as err:
            status["last_error"] = "blocked"
            step = min(blocked_polls, len(BLOCKED_POLL_STEPS) - 1)
            blocked_polls += 1
            coordinator.update_interval = BLOCKED_POLL_STEPS[step]
            if blocked_polls >= BLOCKED_ISSUE_AFTER:
                ir.async_create_issue(
                    hass,
                    DOMAIN,
                    BLOCKED_ISSUE_ID,
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key=BLOCKED_ISSUE_ID,
                )
            raise UpdateFailed(str(err)) from err
        except DkvApiError as err:
            status["last_error"] = "api"
            raise UpdateFailed(str(err)) from err
        except Exception as err:
            status["last_error"] = "unexpected"
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
        "status": status,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry,
        PLATFORMS,
    )
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        ir.async_delete_issue(hass, DOMAIN, BLOCKED_ISSUE_ID)
    return unload_ok
