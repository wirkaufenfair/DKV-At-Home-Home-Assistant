"""Standalone HTTP bridge for DKV@Home (no Home Assistant required).

Reuses the API client of the Home Assistant integration and exposes a
small local HTTP API, e.g. for evcc::

    GET  /status   -> JSON with session state (cached, polled in background)
    GET  /active   -> plain text "true" / "false"
    GET  /health   -> like /status, but HTTP 503 while the last poll failed
    POST /start    -> start a session (blocks until confirmed or timeout)
    POST /stop     -> stop the active session (blocks until confirmed)

Usage::

    python dkv_bridge.py login   # one-time interactive login
    python dkv_bridge.py serve   # run the bridge

Configuration (environment variables):

    DKV_DATA_DIR       directory for tokens.json (default: ./data)
    DKV_BIND           listen address (default: 0.0.0.0)
    DKV_PORT           listen port (default: 8099)
    DKV_POLL_SECONDS   status poll interval (default: 30)
    DKV_LOG_LEVEL      logging level (default: INFO)
    DKV_BRIDGE_TOKEN   optional; if set, POST requests need the header
                       ``Authorization: Bearer <token>``
"""

import json
import logging
import os
import sys
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import import_module
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent


def _load_api() -> types.ModuleType:
    """Import api.py of the HA integration without importing homeassistant.

    The integration's ``__init__`` needs Home Assistant, so a stub package
    pointing at the same directory is registered instead; api.py and
    const.py only use relative imports of each other.
    """
    for candidate in (
        HERE / "dkv_at_home",  # Docker image layout
        HERE.parent / "custom_components" / "dkv_at_home",  # repo layout
    ):
        if (candidate / "api.py").is_file():
            pkg = types.ModuleType("dkv_at_home")
            pkg.__path__ = [str(candidate)]
            sys.modules["dkv_at_home"] = pkg
            return import_module("dkv_at_home.api")
    raise SystemExit("api.py der Integration nicht gefunden")


api = _load_api()
const = import_module("dkv_at_home.const")

_LOGGER = logging.getLogger("dkv_bridge")

REDIRECT_URI = "com.dkv-mobility.app://oauth2redirect"

DATA_DIR = Path(os.environ.get("DKV_DATA_DIR", "data"))
TOKEN_FILE = DATA_DIR / "tokens.json"
BIND = os.environ.get("DKV_BIND", "0.0.0.0")
PORT = int(os.environ.get("DKV_PORT", "8099"))
POLL_SECONDS = int(os.environ.get("DKV_POLL_SECONDS", const.POLL_INTERVAL_SECONDS))
BRIDGE_TOKEN = os.environ.get("DKV_BRIDGE_TOKEN")


# ----------------------------------------------------------------------
# Token storage
# ----------------------------------------------------------------------


def load_state() -> dict:
    try:
        return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def save_state(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = TOKEN_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    tmp.replace(TOKEN_FILE)


# ----------------------------------------------------------------------
# Login
# ----------------------------------------------------------------------


def parse_input(text: str) -> tuple[str, dict]:
    """Return (mode, data) for a pasted redirect URL, code or refresh token."""
    raw = (text or "").strip()
    if "://" in raw and "code=" in raw:
        parsed = urlparse(raw)
        code = parse_qs(parsed.query).get("code", [None])[0]
        if code:
            return "code", {
                "code": code,
                "redirect_uri": f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
            }
    elif raw.startswith("eyJ") and raw.count(".") >= 2:
        return "refresh_token", {"token": raw}
    elif raw:
        return "code", {"code": raw, "redirect_uri": REDIRECT_URI}
    return "invalid", {}


def cmd_login() -> int:
    verifier, challenge = api.DkvApiClient.generate_pkce_pair()
    url = api.DkvApiClient.build_authorize_url(
        state=os.urandom(12).hex(),
        redirect_uri=REDIRECT_URI,
        code_challenge=challenge,
    )
    print("1. Diese URL im Browser oeffnen und bei DKV anmelden:\n")
    print(url)
    print(
        "\n2. Nach dem Login die URL mit '?code=...' "
        "(com.dkv-mobility.app://oauth2redirect?...) aus der Adresszeile\n"
        "   bzw. dem Netzwerk-Log kopieren. Alternativ geht auch nur der "
        "code oder ein vorhandener Refresh-Token.\n"
    )
    mode, data = parse_input(input("Eingabe: "))
    client = api.DkvApiClient(refresh_token="", app_token="")
    try:
        if mode == "code":
            client.exchange_code(
                code=data["code"],
                redirect_uri=data["redirect_uri"],
                code_verifier=verifier,
            )
        elif mode == "refresh_token":
            client.refresh_token = data["token"]
            client.validate()
        else:
            print("Ungueltige Eingabe", file=sys.stderr)
            return 1
        username = client.fetch_preferred_username()
    except api.DkvApiError as err:
        print(f"Login fehlgeschlagen: {err}", file=sys.stderr)
        return 1
    save_state(
        {
            "preferred_username": username,
            "refresh_token": client.refresh_token,
            "access_token": client.access_token,
        }
    )
    print(f"Angemeldet als {username}. Tokens in {TOKEN_FILE} gespeichert.")
    return 0


# ----------------------------------------------------------------------
# Bridge core
# ----------------------------------------------------------------------


class Bridge:
    """Owns the API client; serializes all calls (refresh tokens rotate)."""

    def __init__(self, state: dict) -> None:
        self._state = state
        self._client = api.DkvApiClient(
            refresh_token=state["refresh_token"],
            app_token=state["preferred_username"],
            access_token=state.get("access_token"),
        )
        self._lock = threading.Lock()
        self._cp: dict | None = None
        self._error: str | None = None
        self._updated: float | None = None

    def _call(self, func):
        with self._lock:
            try:
                return func()
            finally:
                # Persist rotated tokens even if the call failed.
                self._state["refresh_token"] = self._client.refresh_token
                self._state["access_token"] = self._client.access_token
                save_state(self._state)

    def refresh(self) -> None:
        try:
            cp = self._call(self._client.fetch_status)
        except api.DkvApiError as err:
            self._error = str(err)
            _LOGGER.warning("Status-Abfrage fehlgeschlagen: %s", err)
        except Exception as err:  # noqa: BLE001 - keep the poller alive
            self._error = f"Unerwarteter Fehler: {err}"
            _LOGGER.exception("Status-Abfrage fehlgeschlagen")
        else:
            self._cp, self._error, self._updated = cp, None, time.time()

    def status(self) -> dict:
        cp = self._cp or {}
        return {
            "active": cp.get("activeSessionId") is not None,
            "activeSessionId": cp.get("activeSessionId"),
            "status": cp.get("status"),
            "name": cp.get("name"),
            "error": self._error,
            "updated": self._updated,
        }

    def start(self) -> tuple[int, dict]:
        def _start():
            cp = self._client.fetch_status()
            if cp.get("activeSessionId"):
                return cp["activeSessionId"]
            return self._client.start()

        return self._run(_start, "Start")

    def stop(self) -> tuple[int, dict]:
        return self._run(self._client.stop, "Stopp")

    def _run(self, func, name: str) -> tuple[int, dict]:
        try:
            result = self._call(func)
        except api.DkvApiError as err:
            _LOGGER.error("%s fehlgeschlagen: %s", name, err)
            return 502, {"ok": False, "error": str(err)}
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("%s fehlgeschlagen", name)
            return 500, {"ok": False, "error": str(err)}
        self.refresh()
        # start() returns a session id, stop() a bool; None/False = timeout
        if not result:
            return 504, {
                "ok": False,
                "error": "Wallbox hat nicht innerhalb des Zeitlimits bestaetigt",
            }
        return 200, {"ok": True, **self.status()}

    def poll_forever(self) -> None:
        while True:
            self.refresh()
            time.sleep(POLL_SECONDS)


def make_handler(bridge: Bridge):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: str, ctype: str) -> None:
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _json(self, code: int, payload: dict) -> None:
            self._send(code, json.dumps(payload), "application/json")

        def do_GET(self):  # noqa: N802
            path = urlparse(self.path).path
            if path == "/status":
                self._json(200, bridge.status())
            elif path == "/active":
                self._send(
                    200, str(bridge.status()["active"]).lower(), "text/plain"
                )
            elif path == "/health":
                st = bridge.status()
                self._json(503 if st["error"] else 200, st)
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            if BRIDGE_TOKEN and self.headers.get("Authorization") != (
                f"Bearer {BRIDGE_TOKEN}"
            ):
                self._json(401, {"error": "unauthorized"})
                return
            path = urlparse(self.path).path
            if path == "/start":
                self._json(*bridge.start())
            elif path == "/stop":
                self._json(*bridge.stop())
            else:
                self._json(404, {"error": "not found"})

        def log_message(self, fmt, *args):
            _LOGGER.debug("%s %s", self.address_string(), fmt % args)

    return Handler


def cmd_serve() -> int:
    state = load_state()
    if not state.get("refresh_token"):
        print("Keine Tokens gefunden. Zuerst 'login' ausfuehren.", file=sys.stderr)
        return 1
    bridge = Bridge(state)
    threading.Thread(target=bridge.poll_forever, daemon=True).start()
    server = ThreadingHTTPServer((BIND, PORT), make_handler(bridge))
    _LOGGER.info("DKV-Bridge laeuft auf %s:%s", BIND, PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("DKV_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if cmd == "login":
        return cmd_login()
    if cmd == "serve":
        return cmd_serve()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
