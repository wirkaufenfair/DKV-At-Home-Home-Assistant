"""Config flow for DKV@Home integration."""

# pyright: reportMissingImports=false, reportCallIssue=false
# pylint: disable=import-error

import secrets as _secrets
from urllib.parse import parse_qs, urlparse

import voluptuous as vol  # type: ignore[import]

from homeassistant import config_entries  # type: ignore[import]
from homeassistant.core import HomeAssistant  # type: ignore[import]

from .api import DkvApiClient, DkvApiError
from .const import CLIENT_ID, DOMAIN

# Redirect URI used for PKCE flow. DKV's Keycloak portal client accepts
# its own origin; after login the browser lands on the DKV portal home
# page with ?code=…&state=… in the address bar.
_PKCE_REDIRECT_URI = "https://my.dkv-mobility.com/"


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

    async def _exchange_pkce_code(
        self,
        code: str,
        _returned_state: str | None,
        redirect_uri: str = _PKCE_REDIRECT_URI,
    ) -> tuple[dict | None, dict]:
        """Exchange an authorization code for tokens.

        Returns ``(entry_data, errors)``.
        """
        verifier = self._pkce_verifier
        if verifier is None:
            return None, {"base": "unknown"}
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
        except DkvApiError:
            self._pkce_verifier = None  # force new PKCE pair on retry
            return None, {"base": "cannot_connect"}
        except (ValueError, TypeError):
            self._pkce_verifier = None
            return None, {"base": "unknown"}

    async def _process_input(self, text: str) -> tuple[dict | None, dict]:
        """Dispatch parsed input to the right auth path."""
        parsed = _parse_user_input(text)
        mode = parsed["mode"]

        if mode == "invalid":
            return None, {"base": "invalid_input"}

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
