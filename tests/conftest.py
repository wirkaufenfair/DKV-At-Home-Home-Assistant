"""Shared fixtures for the DKV@Home tests.

The tests of ``api.py`` do not need Home Assistant. The integration's
``__init__`` imports ``homeassistant``, so a stub package pointing at the
same directory is registered instead; ``api.py`` and ``const.py`` only use
relative imports of each other.
"""

import sys
import time
import types
from pathlib import Path

import pytest

COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent / "custom_components" / "dkv_at_home"
)

try:
    import homeassistant  # noqa: F401
except ImportError:
    # Lightweight runs: the Home Assistant level tests are skipped.
    collect_ignore_glob = ["ha/*"]

if "dkv_at_home" not in sys.modules:
    _pkg = types.ModuleType("dkv_at_home")
    _pkg.__path__ = [str(COMPONENT_DIR)]
    sys.modules["dkv_at_home"] = _pkg

from dkv_at_home import api as dkv_api  # noqa: E402
from dkv_at_home import const  # noqa: E402
from helpers import FakeHttp, make_jwt  # noqa: E402


@pytest.fixture
def http(monkeypatch) -> FakeHttp:
    fake = FakeHttp()
    monkeypatch.setattr(
        dkv_api.requests, "get", lambda url, **kw: fake.handle("GET", url, **kw)
    )
    monkeypatch.setattr(
        dkv_api.requests, "post", lambda url, **kw: fake.handle("POST", url, **kw)
    )
    return fake


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Never really wait while polling for confirmation."""
    monkeypatch.setattr(dkv_api.time, "sleep", lambda _s: None)


@pytest.fixture
def valid_access_token() -> str:
    return make_jwt(int(time.time()) + 3600)


@pytest.fixture
def client(valid_access_token):
    return dkv_api.DkvApiClient(
        refresh_token="refresh-0",
        app_token="100000000001",
        access_token=valid_access_token,
    )


@pytest.fixture
def api_module():
    return dkv_api


@pytest.fixture
def consts():
    return const
