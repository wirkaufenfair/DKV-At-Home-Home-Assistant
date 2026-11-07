"""Read-only checks against a real DKV account (run by hand before a release).

Uses a refresh token stored by ``python tests/live_login.py``. It refreshes
the token (the only place that sends a real token to DKV), then makes
read-only API calls. It never starts or stops a charging session.

DKV rotates the refresh token on every use, so the new one is written back
to the token file after each run. Use a login of its own for this (run
``tests/live_login.py``), not the one of the Home Assistant integration:
two users of one token would invalidate each other.

Run with ``pytest -m e2e``; skipped when there is no token file.
"""

import json
import os
import sys
from pathlib import Path

import pytest

TOKEN_FILE = Path(
    os.environ.get(
        "DKV_TOKEN_FILE",
        Path(__file__).resolve().parent.parent / ".dkv-test-token",
    )
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not TOKEN_FILE.is_file(),
        reason=f"no token file at {TOKEN_FILE}; run tests/live_login.py",
    ),
]


def save_tokens(client) -> None:
    TOKEN_FILE.write_text(
        json.dumps(
            {
                "refresh_token": client.refresh_token,
                "access_token": client.access_token,
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture(scope="module")
def live(request):
    api = sys.modules["dkv_at_home.api"]
    saved = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    client = api.DkvApiClient(
        refresh_token=saved["refresh_token"], app_token="live-test"
    )
    client._refresh()  # rotates the token ...
    save_tokens(client)  # ... so keep the new one right away
    yield client
    save_tokens(client)


def test_refresh_gives_long_lived_token(live):
    """offline_access must still give an Offline token (no short limit)."""
    api = sys.modules["dkv_at_home.api"]
    claims = api.DkvApiClient._decode_jwt_claims(live.refresh_token)
    assert claims.get("typ") == "Offline"


def test_userinfo_gives_username(live):
    assert live.fetch_preferred_username()


def test_charge_point_has_what_start_needs(live):
    """start() reads these fields; DKV renaming them would break it."""
    cp = live.fetch_status()
    hardware = cp.get("hardwareInfo", {})
    assert cp.get("evseUid") or hardware.get("evseUid")
    assert cp.get("locationIdCa") or hardware.get("locationIdCa")
    assert "activeSessionId" in cp or "status" in cp


def test_payment_card_is_available(live):
    assert live._get_card_id()
