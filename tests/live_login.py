"""Create the token file for ``tests/test_live_account.py``.

Usage: ``python tests/live_login.py``

Follows the browser flow of the README: open the printed link, log in with
the browser developer tools open, copy the ``Location`` header of the
``authenticate`` request and paste it here. The tokens are stored in
``.dkv-test-token`` (ignored by git). Use this login only for the tests.
"""

import json
import os
import sys
import types
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
pkg = types.ModuleType("dkv_at_home")
pkg.__path__ = [str(ROOT / "custom_components" / "dkv_at_home")]
sys.modules["dkv_at_home"] = pkg

from dkv_at_home.api import DkvApiClient, DkvApiError

REDIRECT_URI = "com.dkv-mobility.app://oauth2redirect"
TOKEN_FILE = Path(os.environ.get("DKV_TOKEN_FILE", ROOT / ".dkv-test-token"))


def main() -> int:
    verifier, challenge = DkvApiClient.generate_pkce_pair()
    print("1. Open this link and log in (developer tools open, Network tab):\n")
    print(DkvApiClient.build_authorize_url("live-test", REDIRECT_URI, challenge))
    print(
        "\n2. Copy the Location header of the 'authenticate' request "
        "(com.dkv-mobility.app://oauth2redirect?...code=...) and paste it.\n"
    )
    raw = input("Location: ").strip()
    code = parse_qs(urlparse(raw).query).get("code", [raw])[0]
    client = DkvApiClient(refresh_token="", app_token="live-test")
    try:
        client.exchange_code(
            code=code, redirect_uri=REDIRECT_URI, code_verifier=verifier
        )
    except DkvApiError as err:
        print(f"Login failed: {err}", file=sys.stderr)
        return 1
    TOKEN_FILE.write_text(
        json.dumps(
            {
                "refresh_token": client.refresh_token,
                "access_token": client.access_token,
            }
        ),
        encoding="utf-8",
    )
    print(f"Saved to {TOKEN_FILE}. Run: python -m pytest -m e2e -v")
    return 0


if __name__ == "__main__":
    sys.exit(main())
