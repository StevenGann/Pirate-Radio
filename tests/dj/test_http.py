"""RED tests for ``pirate_radio.dj._http`` — Phase 3 plan §4.2a / §5 (P3-5).

Tests first (strict spec-driven TDD): the shared async-HTTP seam for the httpx-backed providers
(DeepSeek, Ollama, ElevenLabs) + the PURE HTTP error mappers (R15). The mappers live HERE (not in
dj/text.py) so dj/tts.py imports them WITHOUT a cross-sibling tts->text import. ``post_json`` is
tested via a FAKE httpx module injected into ``sys.modules`` — no real httpx import, no socket.
"""

from __future__ import annotations

import sys
import types

import pytest

from pirate_radio.dj._http import map_http_status, map_httpx_exception, post_json
from pirate_radio.errors import (
    ProviderError,
    ProviderFatal,
    ProviderQuotaExceeded,
    ProviderUnavailable,
)


# ---- map_http_status (R15 §3.4) -----------------------------------------------------------
def test_map_http_429_is_quota() -> None:
    assert isinstance(map_http_status("deepseek", 429, "{}"), ProviderQuotaExceeded)


def test_map_http_401_is_fatal() -> None:
    assert isinstance(map_http_status("deepseek", 401, "{}"), ProviderFatal)


def test_map_http_400_is_fatal() -> None:
    assert isinstance(map_http_status("deepseek", 400, "bad"), ProviderFatal)


def test_map_http_503_is_unavailable() -> None:
    assert isinstance(map_http_status("ollama", 503, "x"), ProviderUnavailable)


def test_map_http_status_truncates_body() -> None:
    err = map_http_status("deepseek", 500, "y" * 1000)
    assert len(str(err)) < 400  # body truncated (no log flooding)


# ---- map_httpx_exception (matched by class NAME, no httpx import) --------------------------
def test_map_httpx_connect_is_unavailable() -> None:
    class ConnectError(Exception): ...

    assert isinstance(map_httpx_exception("ollama", ConnectError()), ProviderUnavailable)


def test_map_httpx_timeout_is_unavailable() -> None:
    class ReadTimeout(Exception): ...

    assert isinstance(map_httpx_exception("deepseek", ReadTimeout()), ProviderUnavailable)


def test_map_httpx_unknown_is_unavailable_default() -> None:
    assert isinstance(map_httpx_exception("ollama", RuntimeError("?")), ProviderUnavailable)


def test_map_httpx_passes_through_providererror() -> None:
    pe = ProviderFatal("already classified")
    assert map_httpx_exception("deepseek", pe) is pe  # don't double-wrap


# ---- post_json via a FAKE httpx module (no real import, no socket) -------------------------
class _FakeResp:
    def __init__(self, *, status_code: int, json_data: object = None, text: str = "") -> None:
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self) -> object:
        return self._json


class _FakeClient:
    def __init__(self, *, resp: _FakeResp | None = None, exc: Exception | None = None) -> None:
        self._resp = resp
        self._exc = exc
        self.posted: dict[str, object] = {}

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *a: object) -> bool:
        return False

    async def post(
        self, url: str, *, headers: object = None, json: object = None, params: object = None
    ) -> _FakeResp:
        self.posted = {"url": url, "headers": headers, "json": json, "params": params}
        if self._exc is not None:
            raise self._exc
        assert self._resp is not None
        return self._resp


def _install_fake_httpx(monkeypatch: pytest.MonkeyPatch, client: _FakeClient) -> None:
    fake = types.ModuleType("httpx")
    fake.AsyncClient = lambda **kw: client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "httpx", fake)


async def test_post_json_happy_returns_parsed_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(resp=_FakeResp(status_code=200, json_data={"ok": 1}))
    _install_fake_httpx(monkeypatch, client)
    out = await post_json(
        "deepseek", "http://x/chat", {"Authorization": "Bearer k"}, {"a": 1}, timeout=5.0
    )
    assert out == {"ok": 1}
    # forwards url + headers + body VERBATIM (a dropped Authorization header must fail this)
    assert client.posted["url"] == "http://x/chat"
    assert client.posted["headers"] == {"Authorization": "Bearer k"}
    assert client.posted["json"] == {"a": 1}


async def test_post_json_4xx_maps_via_status(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(resp=_FakeResp(status_code=401, text="nope"))
    _install_fake_httpx(monkeypatch, client)
    with pytest.raises(ProviderFatal):
        await post_json("deepseek", "http://x", {}, {}, timeout=5.0)


async def test_post_json_429_maps_to_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(resp=_FakeResp(status_code=429, text="slow down"))
    _install_fake_httpx(monkeypatch, client)
    with pytest.raises(ProviderQuotaExceeded):
        await post_json("deepseek", "http://x", {}, {}, timeout=5.0)


async def test_post_json_transport_error_maps_via_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ConnectError(Exception): ...

    client = _FakeClient(exc=ConnectError("refused"))
    _install_fake_httpx(monkeypatch, client)
    with pytest.raises(ProviderUnavailable):
        await post_json("ollama", "http://x", {}, {}, timeout=5.0)


async def test_post_json_reraises_providererror_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a ProviderError raised inside the client must surface as-is, not be re-wrapped
    client = _FakeClient(exc=ProviderFatal("boom"))
    _install_fake_httpx(monkeypatch, client)
    with pytest.raises(ProviderFatal):
        await post_json("deepseek", "http://x", {}, {}, timeout=5.0)


def test_map_httpx_exception_returns_base_providererror_type() -> None:
    assert isinstance(map_httpx_exception("x", RuntimeError("y")), ProviderError)
