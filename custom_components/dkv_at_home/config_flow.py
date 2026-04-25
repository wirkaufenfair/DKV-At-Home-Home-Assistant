"""Config flow for DKV@Home integration."""

# pyright: reportMissingImports=false, reportCallIssue=false
# pylint: disable=import-error

import json

import voluptuous as vol  # type: ignore[import]

from homeassistant import config_entries  # type: ignore[import]
from homeassistant.core import HomeAssistant  # type: ignore[import]

from .api import DkvApiClient, DkvApiError
from .const import CLIENT_ID, DOMAIN

DKV_PORTAL_LOGIN_URL = "https://my.dkv-mobility.com"


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


def _extract_tokens_from_text(text: str) -> tuple[str | None, str | None]:
    """Extract refresh/access token from JSON text or return (None, None)."""
    raw = (text or "").strip()
    if not raw.startswith("{"):
        return None, None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, None

    refresh_token = data.get("refresh_token")
    access_token = data.get("access_token")
    if not refresh_token:
        return None, None
    return refresh_token, access_token


class DkvMobilityConfigFlow(  # type: ignore[call-arg]
    config_entries.ConfigFlow,
    domain=DOMAIN,
):
    """Handle the DKV@Home config flow."""

    VERSION = 1

    async def async_step_user(self, _user_input: dict | None = None):
        """Start setup flow."""
        return await self.async_step_auth()

    async def async_step_auth(self, user_input: dict | None = None):
        """Create config entry from token JSON."""
        errors: dict[str, str] = {}

        schema = vol.Schema(
            {
                vol.Required("token_json"): str,
            }
        )

        if user_input is not None:
            input_text = user_input["token_json"]
            refresh_token, access_token = _extract_tokens_from_text(input_text)

            if not refresh_token:
                errors["base"] = "invalid_token_json"
            else:
                try:
                    entry_data = await _build_entry_from_tokens(
                        self.hass,
                        refresh_token=refresh_token,
                        access_token=access_token,
                    )
                except DkvApiError:
                    errors["base"] = "cannot_connect"
                except (ValueError, TypeError):
                    errors["base"] = "unknown"
                else:
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
            data_schema=schema,
            errors=errors,
        )
