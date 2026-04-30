"""Config flow for DKV@Home integration."""

# pyright: reportMissingImports=false, reportCallIssue=false

import logging
import secrets as _secrets
from urllib.parse import parse_qs, urlparse

import voluptuous as vol  # type: ignore[import]

from homeassistant import config_entries  # type: ignore[import]
from homeassistant.core import HomeAssistant  # type: ignore[import]

from .api import DkvApiClient, DkvApiError
from .const import CLIENT_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Redirect URI registered for the ``dkv-app`` Keycloak client (the same
# client used by the official DKV mobile app, see the public Postman
# collection). It is a custom URI scheme; desktop browsers cannot follow
# it and will instead show a "open external app?" dialog. The user has
# to grab the URL containing ``?code=…`` from the browser's network log
# / address bar and paste it back into HA. We accept either the full
# URL or just the bare ``code`` value.
_REDIRECT_URI = "com.dkv-mobility.app://oauth2redirect"


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

    # Accept full redirect URLs in any scheme (https, custom app scheme, …).
    # The dkv-app Keycloak client uses ``com.dkv-mobility.app://...`` so we
    # cannot restrict to ``http``.
    if "://" in raw and "code=" in raw:
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
        self._auth_state: str | None = None
        self._auth_url: str | None = None
        self._code_verifier: str | None = None

    # ------------------------------------------------------------------
    # Auth URL helper
    # ------------------------------------------------------------------

    def _ensure_auth_url(self) -> None:
        """Build a fresh login URL if one is not already prepared.

        Uses Authorization Code Flow with PKCE (S256). The PKCE verifier,
        state and URL are persisted in ``self.context`` so they survive a
        frontend reconnect or an HA restart that recreates the flow object.
        """
        # Restore from flow context first (survives object recreation).
        if self._auth_state is None and "auth_state" in self.context:
            self._auth_state = self.context["auth_state"]
            self._auth_url = self.context.get("auth_url")
            self._code_verifier = self.context.get("code_verifier")
            _LOGGER.debug("Auth-URL aus Flow-Kontext wiederhergestellt")

        if self._auth_url is not None and self._code_verifier is not None:
            return

        verifier, challenge = DkvApiClient.generate_pkce_pair()
        self._auth_state = _secrets.token_urlsafe(16)
        self._code_verifier = verifier
        self._auth_url = DkvApiClient.build_authorize_url(
            state=self._auth_state,
            redirect_uri=_REDIRECT_URI,
            code_challenge=challenge,
        )
        self.context["auth_state"] = self._auth_state
        self.context["auth_url"] = self._auth_url
        self.context["code_verifier"] = self._code_verifier
        _LOGGER.debug("Neue Auth-URL mit PKCE generiert")

    def _reset_auth_url(self) -> None:
        """Discard the current auth URL so a fresh one is generated next."""
        self._auth_state = None
        self._auth_url = None
        self._code_verifier = None
        self.context.pop("auth_state", None)
        self.context.pop("auth_url", None)
        self.context.pop("code_verifier", None)

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

    async def _exchange_code(
        self,
        code: str,
        returned_state: str | None,
        redirect_uri: str = _REDIRECT_URI,
    ) -> tuple[dict | None, dict]:
        """Exchange an authorization code for tokens.

        Returns ``(entry_data, errors)``.
        """
        if returned_state and self._auth_state:
            _LOGGER.debug(
                "State: gesendet=%s, erhalten=%s",
                self._auth_state,
                returned_state,
            )

        _LOGGER.debug(
            "Code-Austausch: redirect_uri=%s code_prefix=%s",
            redirect_uri,
            code[:8] if code else "NONE",
        )
        verifier = self._code_verifier
        if not verifier:
            _LOGGER.error(
                "PKCE code_verifier fehlt im Flow-Kontext – "
                "neuer Anmeldelink erforderlich"
            )
            self._reset_auth_url()
            return None, {"base": "code_expired"}
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
            exc_str = str(exc)
            _LOGGER.error("Code-Austausch fehlgeschlagen: %s", exc_str)
            if "invalid_grant" in exc_str:
                self._reset_auth_url()
                return None, {"base": "code_expired"}
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
        redirect_uri = parsed.get("redirect_uri", _REDIRECT_URI)
        return await self._exchange_code(code, state, redirect_uri)

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
        self._ensure_auth_url()
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
            description_placeholders={"auth_url": self._auth_url},
        )

    async def async_step_auth(self, user_input: dict | None = None):
        """Create config entry via authorization code or refresh token."""
        self._ensure_auth_url()
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
            description_placeholders={"auth_url": self._auth_url},
        )
