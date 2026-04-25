"""DKV@Home API client."""

import base64
import hashlib
import logging
import secrets
import time
from urllib.parse import urlencode

import requests

from .const import (
    BASE_URL,
    CLIENT_ID,
    CONFIRM_INTERVAL_SECONDS,
    CONFIRM_TIMEOUT_SECONDS,
    TOKEN_URL,
)

AUTH_URL = (
    "https://my.dkv-mobility.com/auth/realms/dkv/"
    "protocol/openid-connect/auth"
)
USERINFO_URL = (
    "https://my.dkv-mobility.com/auth/realms/dkv/"
    "protocol/openid-connect/userinfo"
)

_LOGGER = logging.getLogger(__name__)


class DkvApiError(Exception):
    """Raised when the DKV API returns an unexpected response."""


class DkvApiClient:
    """Synchronous HTTP client for the DKV@Home at-home API.

    Designed to be called inside ``hass.async_add_executor_job``.
    After any successful call the caller should persist the updated
    ``refresh_token`` and ``access_token`` attributes back to the
    config entry so they survive a HA restart.
    """

    def __init__(
        self,
        refresh_token: str,
        app_token: str,
        client_id: str = CLIENT_ID,
        access_token: str | None = None,
    ) -> None:
        self.refresh_token = refresh_token
        self.app_token = app_token
        self.client_id = client_id
        self.access_token = access_token

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        """Exchange the refresh token for a new access token (in-place)."""
        r = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "refresh_token": self.refresh_token,
            },
            timeout=30,
        )
        if r.status_code != 200:
            raise DkvApiError(
                "Token-Refresh fehlgeschlagen: "
                f"HTTP {r.status_code} – {r.text}"
            )
        result = r.json()
        self.access_token = result["access_token"]
        self.refresh_token = result["refresh_token"]
        _LOGGER.debug("DKV access token erneuert")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _get_charge_point(self) -> dict:
        r = requests.get(
            f"{BASE_URL}/overview/v3/charge-points",
            headers=self._headers(),
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        points = data if isinstance(data, list) else data.get(
            "chargePoints", [data]
        )
        if not points:
            raise DkvApiError(
                "Keine Charge Points in der API-Antwort gefunden"
            )
        return points[0]

    def _get_card_id(self) -> str:
        r = requests.get(
            f"{BASE_URL}/cards/service-card",
            headers=self._headers(),
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        cards = (
            data
            if isinstance(data, list)
            else (data.get("cards") or data.get("data") or [data])
        )
        if not cards:
            raise DkvApiError("Keine Ladekarten in der API-Antwort gefunden")
        card_id = cards[0].get("id")
        if not card_id:
            raise DkvApiError("Card-ID fehlt in der API-Antwort")
        return card_id

    @staticmethod
    def generate_pkce_pair() -> tuple[str, str]:
        """Generate PKCE verifier/challenge for OAuth code flow."""
        verifier = (
            base64.urlsafe_b64encode(secrets.token_bytes(64))
            .decode()
            .rstrip("=")
        )
        challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode()).digest()
            )
            .decode()
            .rstrip("=")
        )
        return verifier, challenge

    @staticmethod
    def build_authorize_url(
        state: str,
        code_challenge: str,
        redirect_uri: str,
    ) -> str:
        """Build OAuth authorize URL for the DKV portal client."""
        params = {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": "openid email profile",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def exchange_code(
        self,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> None:
        """Exchange authorization code for refresh/access token (in-place)."""
        r = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
            timeout=30,
        )
        if r.status_code != 200:
            raise DkvApiError(
                "Code-Austausch fehlgeschlagen: "
                f"HTTP {r.status_code} – {r.text}"
            )

        result = r.json()
        self.access_token = result["access_token"]
        self.refresh_token = result["refresh_token"]

    def fetch_preferred_username(self) -> str:
        """Fetch ``preferred_username`` from the OIDC userinfo endpoint."""
        if not self.access_token:
            raise DkvApiError("Kein Access Token vorhanden")

        r = requests.get(
            USERINFO_URL,
            headers=self._headers(),
            timeout=30,
        )
        if r.status_code != 200:
            raise DkvApiError(
                "Userinfo konnte nicht geladen werden: "
                f"HTTP {r.status_code} – {r.text}"
            )

        data = r.json()
        preferred_username = data.get("preferred_username")
        if not preferred_username:
            raise DkvApiError(
                "preferred_username fehlt in der Userinfo-Antwort"
            )
        return preferred_username

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_status(self) -> dict:
        """Refresh token and return the raw charge-point dict.

        Intended to be called from the DataUpdateCoordinator.
        """
        self._refresh()
        return self._get_charge_point()

    def validate(self) -> None:
        """Validate credentials by performing a token refresh.

        Raises ``DkvApiError`` on failure. Used by config flow.
        """
        self._refresh()

    def start(self) -> str | None:
        """Start a charging session.

        Returns the confirmed ``activeSessionId`` on success,
        or ``None`` if the wallbox did not confirm within the timeout.
        Raises ``DkvApiError`` on hard failures.
        """
        self._refresh()

        cp = self._get_charge_point()
        hw = cp.get("hardwareInfo", {})
        evse_uid = cp.get("evseUid") or hw.get("evseUid")
        location_id = cp.get("locationIdCa") or hw.get("locationIdCa")

        if not evse_uid or not location_id:
            raise DkvApiError(
                f"evseUid oder locationId fehlt (evseUid={evse_uid}, "
                f"locationId={location_id})"
            )

        payment_method_id = self._get_card_id()

        r = requests.post(
            f"{BASE_URL}/station-management/session/start",
            json={
                "evseUid": evse_uid,
                "locationId": location_id,
                "paymentMethodId": payment_method_id,
            },
            headers=self._headers(),
            timeout=30,
        )
        if r.status_code not in (200, 201, 202):
            raise DkvApiError(
                "Session-Start fehlgeschlagen: "
                f"HTTP {r.status_code} – {r.text}"
            )

        try:
            requested_id: str | None = r.json().get("chargeSessionId")
        except ValueError:
            requested_id = None

        _LOGGER.debug(
            "Session-Start akzeptiert, chargeSessionId=%s",
            requested_id,
        )

        # Poll charge point until it reports an active session.
        attempts = CONFIRM_TIMEOUT_SECONDS // CONFIRM_INTERVAL_SECONDS
        for attempt in range(1, attempts + 1):
            cp = self._get_charge_point()
            active_id: str | None = cp.get("activeSessionId")
            _LOGGER.debug(
                "Start-Bestätigung %d/%d: status=%s activeSessionId=%s",
                attempt,
                attempts,
                cp.get("status"),
                active_id,
            )
            if active_id:
                return active_id
            if attempt < attempts:
                time.sleep(CONFIRM_INTERVAL_SECONDS)

        _LOGGER.warning(
            "Wallbox hat den Ladevorgang nicht innerhalb von %ds bestätigt",
            CONFIRM_TIMEOUT_SECONDS,
        )
        return None
