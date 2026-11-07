"""Plain helpers shared by the tests (JWT builder and a fake DKV server)."""

import base64
import json


def make_jwt(exp: int | None, **claims) -> str:
    """Build an unsigned JWT with the given ``exp`` claim."""

    def b64(data: dict) -> str:
        raw = json.dumps(data).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    payload = dict(claims)
    if exp is not None:
        payload["exp"] = exp
    return f"{b64({'alg': 'none'})}.{b64(payload)}.sig"


class FakeResponse:
    """Minimal stand-in for ``requests.Response``."""

    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text or (
            json.dumps(json_data) if json_data is not None else ""
        )

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttp:
    """Records requests and answers them from per-route queues.

    A route is matched by ``method`` and a substring of the URL. Responses
    are consumed in order; the last one repeats.
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._routes: list[tuple[str, str, list]] = []

    def add(self, method: str, url_part: str, *responses) -> None:
        self._routes.append((method, url_part, list(responses)))

    def reset_routes(self) -> None:
        self._routes.clear()

    def calls_to(self, method: str, url_part: str) -> list[dict]:
        return [
            c
            for c in self.calls
            if c["method"] == method and url_part in c["url"]
        ]

    def handle(self, method: str, url: str, **kwargs) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        for m, part, queue in self._routes:
            if m == method and part in url:
                response = queue.pop(0) if len(queue) > 1 else queue[0]
                # a callable answers from test state (e.g. a started session)
                return response() if callable(response) else response
        raise AssertionError(f"unexpected request: {method} {url}")
