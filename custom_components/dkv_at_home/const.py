"""Constants for DKV@Home integration."""

DOMAIN = "dkv_at_home"
# Switched from "dkv-portal" to "dkv-app" in v1.0.25: the portal client
# only issues short-lived refresh tokens (bound to the realm's SSO Session
# Max, ~ a few hours) and does not allow the `offline_access` scope. The
# mobile-app client used by the official DKV app supports `offline_access`,
# which yields a long-lived (typically 30+ day) refresh token suitable for
# unattended polling from Home Assistant.
CLIENT_ID = "dkv-app"
TOKEN_URL = (
    "https://my.dkv-mobility.com/auth/realms/dkv/"
    "protocol/openid-connect/token"
)
BASE_URL = (
    "https://my.dkv-mobility.com/apidnext/emobility/at-home/mobile/api"
)
# Stop endpoint of the "next-gen" charge-assist backend. Found in the public
# JavaScript bundle of DKV's web app (ng-station-services); the web app sends
# the literal placeholder "{app-token}" as query parameter `appToken`.
STOP_URL = (
    "https://my.dkv-mobility.com/apidnext/bff-stationservices/"
    "charge-assist/ca/v2.1/session/stop"
)
STOP_APP_TOKEN = "{app-token}"
CONFIRM_TIMEOUT_SECONDS = 60
CONFIRM_INTERVAL_SECONDS = 5
POLL_INTERVAL_SECONDS = 30
