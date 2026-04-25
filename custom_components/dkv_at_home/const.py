"""Constants for DKV@Home integration."""

DOMAIN = "dkv_at_home"
CLIENT_ID = "dkv-portal"
TOKEN_URL = (
    "https://my.dkv-mobility.com/auth/realms/dkv/"
    "protocol/openid-connect/token"
)
BASE_URL = (
    "https://my.dkv-mobility.com/apidnext/emobility/at-home/mobile/api"
)
CONFIRM_TIMEOUT_SECONDS = 60
CONFIRM_INTERVAL_SECONDS = 5
POLL_INTERVAL_SECONDS = 30
