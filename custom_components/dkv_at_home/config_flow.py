"""Config flow for DKV@Home integration."""

# pyright: reportMissingImports=false, reportCallIssue=false
# pylint: disable=import-error

import logging
import secrets as _secrets
from urllib.parse import parse_qs, urlparse

import voluptuous as vol  # type: ignore[import]

from homeassistant import config_entries  # type: ignore[import]
from homeassistant.core import HomeAssistant  # type: ignore[import]

from .api import DkvApiClient, DkvApiError
from .const import CLIENT_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Redirect URI used for PKCE flow. Keycloak's dkv-portal client always
# redirects to /dashboard after login, regardless of the redirect_uri
# parameter – so we register /dashboard here to match the token exchange.
_PKCE_REDIRECT_URI = "https://my.dkv-mobility.com/dashboard"


async def _build_entry_from_tokens(
    hass: HomeAssistant,
    refresh_token: str,
    access_token: str | None = None,
) -> dict:
    """Build config entry data from existing token values."""
    client = DkvApiClient(
        refresh_token=refresh_token,
        app_token="unknown",
        client_id=CLIENT_ID,
        access_token=access_token,
    )

    # Ensure we have a valid access token for userinfo.
    if not client.access_token:
        await hass.async_add_executor_job(client.validate)

    preferred_username = await hass.async_add_executor_job(
        client.fetch_preferred_username
    )

    return {
        "preferred_username": preferred_username,
        "refresh_token": client.refresh_token,
        "access_token": client.access_token,
        "client_id": CLIENT_ID,
    }


def _parse_user_input(text: str) -> dict:
    """Detect whether the user pasted a redirect URL or bare code.

    Returns a dict with key ``mode`` set to one of:
    - ``"pkce_url"``  – full redirect URL containing ``?code=…``
    - ``"pkce_code"`` – bare authorization code string
    - ``"invalid"``   – unrecognised input
    """
    raw = (text or "").strip()

    if raw.startswith("http"):
        parsed = urlparse(raw)
        params = parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        if not code:
            return {"mode": "invalid"}
        # Rebuild redirect_uri as Keycloak saw it (no query string)
        redirect_uri = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        return {
            "mode": "pkce_url",
            "code": code,
            "state": state,
            "redirect_uri": redirect_uri,
        }

    # Keycloak offline-token is a JWT – starts with "eyJ" (base64 of '{"')
    # and has exactly two dots separating header, payload and signature.
    if raw.startswith("eyJ") and raw.count(".") >= 2:
        return {"mode": "refresh_token", "token": raw}

    if raw:
        return {"mode": "pkce_code", "code": raw}

    return {"mode": "invalid"}


class DkvMobilityConfigFlow(  # type: ignore[call-arg]
    config_entries.ConfigFlow,
    domain=DOMAIN,
):
    """Handle the DKV@Home config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow state."""
        self._reauth_entry: config_entries.ConfigEntry | None = None
        self._pkce_verifier: str | None = None
        self._pkce_state: str | None = None
        self._pkce_auth_url: str | None = None

    # ------------------------------------------------------------------
    # PKCE helper
    # ------------------------------------------------------------------

    def _ensure_pkce(self) -> None:
        """Generate a fresh PKCE pair if one is not already prepared."""
        if self._pkce_verifier is not None:
            return
        verifier, challenge = DkvApiClient.generate_pkce_pair()
        self._pkce_verifier = verifier
        self._pkce_state = _secrets.token_urlsafe(16)
        self._pkce_auth_url = DkvApiClient.build_authorize_url(
            state=self._pkce_state,
            code_challenge=challenge,
            redirect_uri=_PKCE_REDIRECT_URI,
        )

    async def _validate_refresh_token(
        self,
        refresh_token: str,
    ) -> tuple[dict | None, dict]:
        """Validate a refresh token pasted directly from the browser.

        Returns ``(entry_data, errors)``.
        """
        _LOGGER.debug(
            "Validiere Refresh-Token (Prefix: %s…)", refresh_token[:12]
        )
        try:
            entry_data = await _build_entry_from_tokens(
                self.hass,
                refresh_token=refresh_token,
            )
            return entry_data, {}
        except DkvApiError as exc:
            _LOGGER.error("Refresh-Token ungültig: %s", exc)
            return None, {"base": "cannot_connect"}
        except (ValueError, TypeError) as exc:
            _LOGGER.error("Fehler bei Refresh-Token-Validierung: %s", exc)
            return None, {"base": "unknown"}

    async def _exchange_pkce_code(
        self,
        code: str,
        returned_state: str | None,
        redirect_uri: str = _PKCE_REDIRECT_URI,
    ) -> tuple[dict | None, dict]:
        """Exchange an authorization code for tokens.

        Returns ``(entry_data, errors)``.
        """
        verifier = self._pkce_verifier
        if verifier is None:
            _LOGGER.error("PKCE-Verifier fehlt – neuer Anlauf nötig")
            return None, {"base": "unknown"}

        # Validate that the returned state matches the one we sent.
        # A mismatch means the user opened an old/wrong auth URL instead
        # of the link currently shown in the HA form.
        if (
            returned_state
            and self._pkce_state
            and returned_state != self._pkce_state
        ):
            _LOGGER.error(
                "State-Mismatch: erwartet=%s, erhalten=%s – "
                "Bitte den Anmeldelink AUS DEM FORMULAR klicken, "
                "keine alte oder gespeicherte URL verwenden!",
                self._pkce_state,
                returned_state,
            )
            return None, {"base": "wrong_auth_url"}

        _LOGGER.debug(
            "PKCE Code-Austausch: redirect_uri=%s code_prefix=%s",
            redirect_uri,
            code[:8] if code else "NONE",
        )
        try:
            client = DkvApiClient(
                refresh_token="",
                app_token="",
                client_id=CLIENT_ID,
            )
            await self.hass.async_add_executor_job(
                lambda: client.exchange_code(
                    code=code,
                    redirect_uri=redirect_uri,
                    code_verifier=verifier,
                )
            )
            entry_data = await _build_entry_from_tokens(
                self.hass,
                refresh_token=client.refresh_token,
                access_token=client.access_token,
            )
            return entry_data, {}
        except DkvApiError as exc:
            _LOGGER.error("PKCE Code-Austausch fehlgeschlagen: %s", exc)
            # Keep the same PKCE pair so the user can retry with the same
            # auth URL. Resetting would force a new pair and a new login.
            return None, {"base": "cannot_connect"}
        except (ValueError, TypeError) as exc:
            _LOGGER.error("Unerwarteter Fehler beim Code-Austausch: %s", exc)
            return None, {"base": "unknown"}

    async def _process_input(self, text: str) -> tuple[dict | None, dict]:
        """Dispatch parsed input to the right auth path."""
        parsed = _parse_user_input(text)
        mode = parsed["mode"]

        if mode == "invalid":
            return None, {"base": "invalid_input"}

        if mode == "refresh_token":
            return await self._validate_refresh_token(parsed["token"])

        code = parsed["code"]
        state = parsed.get("state")
        redirect_uri = parsed.get("redirect_uri", _PKCE_REDIRECT_URI)
        return await self._exchange_pkce_code(code, state, redirect_uri)

    # ------------------------------------------------------------------
    # Flow steps
    # ------------------------------------------------------------------

    async def async_step_user(self, _user_input: dict | None = None):
        """Start setup flow."""
        return await self.async_step_auth()

    async def async_step_reauth(self, _entry_data: dict):
        """Start reauthentication flow when tokens are no longer valid."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict | None = None,
    ):
        """Handle token update for an existing config entry."""
        self._ensure_pkce()
        errors: dict[str, str] = {}

        if user_input is not None:
            entry_data, errors = await self._process_input(
                user_input.get("token_input", "")
            )
            if not errors and entry_data is not None:
                if self._reauth_entry is None:
                    return self.async_abort(reason="unknown")
                return self.async_update_reload_and_abort(
                    self._reauth_entry,
                    data_updates=entry_data,
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required("token_input"): str}),
            errors=errors,
            description_placeholders={"auth_url": self._pkce_auth_url},
        )

    async def async_step_auth(self, user_input: dict | None = None):
        """Create config entry via PKCE OAuth or legacy token JSON."""
        self._ensure_pkce()
        errors: dict[str, str] = {}

        if user_input is not None:
            entry_data, errors = await self._process_input(
                user_input.get("token_input", "")
            )
            if not errors and entry_data is not None:
                await self.async_set_unique_id(
                    entry_data["preferred_username"]
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=(
                        "DKV@Home "
                        f"({entry_data['preferred_username']})"
                    ),
                    data=entry_data,
                )

        return self.async_show_form(
            step_id="auth",
            data_schema=vol.Schema({vol.Required("token_input"): str}),
            errors=errors,
            description_placeholders={"auth_url": self._pkce_auth_url},
        )
