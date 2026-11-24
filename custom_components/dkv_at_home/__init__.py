"""DKV@Home Home Assistant integration."""


import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry  # type: ignore[import]
from homeassistant.core import HomeAssistant  # type: ignore[import]
from homeassistant.exceptions import (  # type: ignore[import]
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
)
from homeassistant.helpers import issue_registry as ir  # type: ignore[import]
from homeassistant.helpers.storage import Store  # type: ignore[import]
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
# keeps such a block alive.
BLOCKED_POLL_STEPS = (
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
)

# The normal rhythm only comes back after this many polls in a row worked:
# a shield that lets single requests through and blocks again under load
# must not see a burst after every lucky answer. In between the poll stays
# at the first (slowest short) step.
RECOVERY_SUCCESSES = 2

# A block that lasts through every step (the third one in a row) is no longer
# a hiccup: Home Assistant shows a repair notice so a human sees it.
BLOCKED_ISSUE_ID = "dkv_blocked"
BLOCKED_ISSUE_AFTER = len(BLOCKED_POLL_STEPS)

BLOCK_STORE_VERSION = 1


def block_store_key(entry_id: str) -> str:
    """Name of the file that keeps the block state over a restart."""
    return f"{DOMAIN}.blocked_{entry_id}"


def _parse_time(value) -> datetime | None:
    """A stored point in time, or None when it is missing or unreadable."""
    if not isinstance(value, str):
        return None
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        return None
    return dt_util.as_utc(parsed)


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

    # The block state survives a restart: a restart during a block must not
    # start again at 30 seconds, that is exactly what keeps a block alive.
    store = Store(hass, BLOCK_STORE_VERSION, block_store_key(entry.entry_id))
    saved = await store.async_load()
    saved = saved if isinstance(saved, dict) else {}
    saved_polls = saved.get("blocked_polls")
    blocked_polls = (
        saved_polls
        if isinstance(saved_polls, int) and not isinstance(saved_polls, bool)
        else 0
    )
    blocked_polls = max(0, blocked_polls)
    blocked_until = _parse_time(saved.get("blocked_until"))
    good_polls = 0
    # What the connection sensor shows: when the last poll worked and what
    # went wrong since (a class like "blocked", never URLs or tokens).
    status: dict = {"last_success": None, "last_error": None}

    async def async_update_data() -> dict:
        nonlocal blocked_polls, good_polls
        try:
            data = await hass.async_add_executor_job(client.fetch_status)
            status["last_success"] = dt_util.utcnow()
            status["last_error"] = None
            if blocked_polls:
                good_polls += 1
                if good_polls >= RECOVERY_SUCCESSES:
                    blocked_polls = 0
                    good_polls = 0
                    coordinator.update_interval = timedelta(
                        seconds=POLL_INTERVAL_SECONDS
                    )
                    ir.async_delete_issue(hass, DOMAIN, BLOCKED_ISSUE_ID)
                    await store.async_remove()
                else:
                    coordinator.update_interval = BLOCKED_POLL_STEPS[0]
            return data
        except DkvAuthError as err:
            status["last_error"] = "auth"
            raise ConfigEntryAuthFailed(str(err)) from err
        except DkvTransientError as err:
            # Temporary backend outage – keep last known state and log only
            # a warning so the error log is not flooded during downtime.
            # Deliberately neither a block nor a success: the slowed rhythm
            # of a running block stays as it is until polls really work.
            status["last_error"] = "transient"
            _LOGGER.warning(
                "DKV-Backend vorübergehend nicht erreichbar: %s", err
            )
            if coordinator.data is not None:
                return coordinator.data
            raise UpdateFailed(str(err)) from err
        except DkvBlockedError as err:
            status["last_error"] = "blocked"
            good_polls = 0
            step = min(blocked_polls, len(BLOCKED_POLL_STEPS) - 1)
            blocked_polls += 1
            wait = BLOCKED_POLL_STEPS[step]
            coordinator.update_interval = wait
            await store.async_save(
                {
                    "blocked_polls": blocked_polls,
                    "blocked_until": (dt_util.utcnow() + wait).isoformat(),
                }
            )
            if blocked_polls >= BLOCKED_ISSUE_AFTER:
                _create_blocked_issue(hass)
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
        # Home Assistant wants the entry passed explicitly; relying on the
        # context variable is deprecated and an error in newer versions.
        config_entry=entry,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=timedelta(seconds=POLL_INTERVAL_SECONDS),
    )

    remaining = blocked_until - dt_util.utcnow() if blocked_until else None
    if blocked_polls and remaining is not None and remaining > timedelta(0):
        # Restarted while the wait after the last block is still running:
        # do not ask DKV now. The entities exist, but are unavailable, and
        # the first poll comes when the wait is over.
        _LOGGER.warning(
            "DKV hat die Anfragen zuletzt abgewiesen, die nächste Abfrage "
            "folgt in %d Minuten",
            max(1, int(remaining.total_seconds() // 60)),
        )
        status["last_error"] = "blocked"
        coordinator.last_update_success = False
        coordinator.update_interval = remaining
        if blocked_polls >= BLOCKED_ISSUE_AFTER:
            _create_blocked_issue(hass)
    else:
        try:
            await coordinator.async_config_entry_first_refresh()
        except ConfigEntryNotReady:
            # A block at start must not end in "setup is retried every few
            # minutes" (more requests, no entities, no repair notice): the
            # entry is set up, the entities are unavailable and the slowed
            # poll takes over. Every other failure keeps the usual retry.
            if status["last_error"] != "blocked":
                raise

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "client": client,
        "persist_tokens": _persist_tokens,
        "status": status,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _create_blocked_issue(hass: HomeAssistant) -> None:
    """Show the repair notice for a lasting block (same id every time)."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        BLOCKED_ISSUE_ID,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=BLOCKED_ISSUE_ID,
    )


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


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """The block state belongs to the entry: it goes when the entry goes."""
    await Store(
        hass, BLOCK_STORE_VERSION, block_store_key(entry.entry_id)
    ).async_remove()
