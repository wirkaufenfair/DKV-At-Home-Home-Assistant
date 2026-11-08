"""Automatic unlock: start the DKV session when the car is connected.

The user picks a binary sensor that reports "vehicle connected" (for
example from evcc). When it turns on, the wallbox is released at DKV. DKV
only confirms the start while the wallbox is allowed to charge, so a failed
attempt is repeated every ``UNLOCK_RETRY_SECONDS`` up to
``UNLOCK_MAX_ATTEMPTS`` times. When it gives up, an event is fired and a
notification is shown.
"""

import logging

from homeassistant.components import persistent_notification
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import DkvApiClient, DkvApiError, DkvAuthError
from .const import (
    DOMAIN,
    EVENT_UNLOCK_FAILED,
    UNLOCK_MAX_ATTEMPTS,
    UNLOCK_RETRY_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

NOTIFICATION_ID = f"{DOMAIN}_unlock_failed"


ALREADY_ACTIVE = "already_active"
STARTED = "started"


def unlock(client: DkvApiClient) -> str | None:
    """Make sure a session is active, starting one if needed (executor).

    Returns ``ALREADY_ACTIVE`` or ``STARTED``, and ``None`` when the wallbox
    did not confirm.
    """
    if client.fetch_status().get("activeSessionId"):
        return ALREADY_ACTIVE
    return STARTED if client.start() is not None else None


class AutoUnlock:
    """Starts a session when the chosen "vehicle connected" sensor turns on."""

    def __init__(
        self,
        hass: HomeAssistant,
        entity_id: str,
        client: DkvApiClient,
        coordinator: DataUpdateCoordinator,
        persist_tokens,
    ) -> None:
        self._hass = hass
        self._entity_id = entity_id
        self._client = client
        self._coordinator = coordinator
        self._persist_tokens = persist_tokens
        self._unsub_state = None
        self._unsub_retry = None
        self._running = False
        self._attempt = 0

    @callback
    def async_start(self) -> None:
        self._unsub_state = async_track_state_change_event(
            self._hass, [self._entity_id], self._handle_state
        )
        state = self._hass.states.get(self._entity_id)
        if state is not None and state.state == "on":
            # Home Assistant started with the car already connected.
            self._begin()

    @callback
    def async_stop(self) -> None:
        if self._unsub_state is not None:
            self._unsub_state()
            self._unsub_state = None
        self._cancel()

    @callback
    def _handle_state(self, event: Event) -> None:
        new = event.data.get("new_state")
        old = event.data.get("old_state")
        if new is None:
            return
        if new.state == "on" and (old is None or old.state != "on"):
            self._begin()
        elif new.state == "off":
            # Only a real "off" ends the attempts; unavailable (for example
            # while evcc restarts) must not.
            self._cancel()

    @callback
    def _begin(self) -> None:
        if self._running:
            return
        self._running = True
        self._attempt = 0
        _LOGGER.info(
            "Fahrzeug angeschlossen (%s): Freischalten beginnt", self._entity_id
        )
        self._hass.async_create_task(self._try())

    @callback
    def _cancel(self) -> None:
        if self._running:
            _LOGGER.info(
                "Fahrzeug abgesteckt (%s): Freischalten abgebrochen",
                self._entity_id,
            )
        self._running = False
        if self._unsub_retry is not None:
            self._unsub_retry()
            self._unsub_retry = None

    async def _try(self, _now=None) -> None:
        self._unsub_retry = None
        if not self._running:
            return
        self._attempt += 1
        reason = None
        try:
            result = await self._hass.async_add_executor_job(
                unlock, self._client
            )
            done = result is not None
        except DkvAuthError as err:
            # The status poll starts the new login; retrying cannot help.
            _LOGGER.warning("Freischalten nicht möglich: %s", err)
            self._running = False
            return
        except DkvApiError as err:
            done, reason = False, str(err)
        except Exception as err:  # keep the retry loop alive
            _LOGGER.exception("Unerwarteter Fehler beim Freischalten")
            done, reason = False, f"Unerwarteter Fehler: {err}"
        finally:
            self._persist_tokens()

        if not self._running:  # the car was disconnected meanwhile
            return
        if done:
            self._running = False
            if result == ALREADY_ACTIVE:
                _LOGGER.info("Wallbox ist bereits freigeschaltet (Session läuft)")
            else:
                _LOGGER.info(
                    "Wallbox freigeschaltet nach %d Versuch(en)", self._attempt
                )
            persistent_notification.async_dismiss(self._hass, NOTIFICATION_ID)
            await self._coordinator.async_request_refresh()
            return
        if self._attempt >= UNLOCK_MAX_ATTEMPTS:
            self._give_up(reason)
            return
        _LOGGER.debug(
            "Freischalten Versuch %d/%d ohne Bestätigung, neuer Versuch in %ds",
            self._attempt,
            UNLOCK_MAX_ATTEMPTS,
            UNLOCK_RETRY_SECONDS,
        )
        self._unsub_retry = async_call_later(
            self._hass, UNLOCK_RETRY_SECONDS, self._try
        )

    def _give_up(self, reason: str | None) -> None:
        self._running = False
        _LOGGER.warning(
            "Wallbox nach %d Versuchen nicht freigeschaltet%s",
            self._attempt,
            f": {reason}" if reason else "",
        )
        self._hass.bus.async_fire(
            EVENT_UNLOCK_FAILED,
            {"attempts": self._attempt, "reason": reason},
        )
        persistent_notification.async_create(
            self._hass,
            "DKV@Home konnte die Wallbox nach "
            f"{self._attempt} Versuchen nicht freischalten. Bitte prüfen, ob "
            "die Wallbox gerade laden darf, oder in der DKV-App freischalten.",
            title="DKV@Home",
            notification_id=NOTIFICATION_ID,
        )
