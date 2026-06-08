"""RED tests for ``pirate_radio.dj.text`` — Phase 3 plan §4.2 / §5 (P3-5).

Tests first (strict spec-driven TDD): the network LLM TextGenerators ClaudeDJ / DeepSeekDJ /
OllamaDJ — PURE response parsers, PURE exception->ProviderError mappers (R15), and the thin
lazy-network shell. R21: NO real SDK import on the CI path and NO socket — the Anthropic SYNC
SDK is proven to hop off the main thread via ``threading.get_ident()`` (not a fake-to_thread
flag), and ``post_json`` is monkeypatched at the helper seam. An import-guard + a top-level-import
grep guard (H28) prove ``anthropic``/``httpx`` are never imported on the faked path.
"""

from __future__ import annotations

import ast
import builtins
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from pirate_radio.dj.context import BlockContext, DjContext
from pirate_radio.dj.text import (
    ClaudeDJ,
    DeepSeekDJ,
    OllamaDJ,
    map_claude_exception,
    parse_claude_response,
    parse_ollama_response,
    parse_openai_chat_response,
)
from pirate_radio.errors import (
    ProviderError,
    ProviderFatal,
    ProviderQuotaExceeded,
    ProviderUnavailable,
)

_SRC = Path(__file__).resolve().parents[2] / "src" / "pirate_radio"


def _ctx(kind: str = "intro") -> DjContext:
    return DjContext(kind=kind, persona="P", station_name="S", current_block=BlockContext(name="B"))


def _areturn(value: Any) -> Callable[..., Awaitable[Any]]:
    async def _f(*a: object, **k: object) -> Any:
        return value

    return _f


# ---- PURE parsers -------------------------------------------------------------------------
def test_parse_claude_extracts_text() -> None:
    class _B:
        text = "hello"

    class _R:
        content = [_B()]

    assert parse_claude_response(_R()) == "hello"


def test_parse_claude_empty_content_is_fatal() -> None:
    class _R:
        content: list[object] = []

    with pytest.raises(ProviderFatal):
        parse_claude_response(_R())


def test_parse_claude_blank_text_is_fatal() -> None:
    class _B:
        text = "   "

    class _R:
        content = [_B()]

    with pytest.raises(ProviderFatal):
        parse_claude_response(_R())


def test_parse_claude_none_text_block_is_fatal_not_typeerror() -> None:
    # DA: a content block with text=None must NOT raise a bare TypeError from "".join([None])
    class _B:
        text = None

    class _R:
        content = [_B()]

    with pytest.raises(ProviderFatal):
        parse_claude_response(_R())


def test_parse_openai_chat_happy() -> None:
    assert parse_openai_chat_response({"choices": [{"message": {"content": " hi "}}]}) == "hi"


def test_parse_openai_chat_missing_field_is_fatal() -> None:
    with pytest.raises(ProviderFatal):
        parse_openai_chat_response({"choices": []})


def test_parse_openai_chat_empty_completion_is_fatal() -> None:
    with pytest.raises(ProviderFatal):
        parse_openai_chat_response({"choices": [{"message": {"content": ""}}]})


def test_parse_openai_chat_null_content_is_fatal_not_attributeerror() -> None:
    # DA: present-but-null content (tool-call / content-filter) must be ProviderFatal, not a
    # leaked AttributeError from None.strip() that would escape the failover net.
    with pytest.raises(ProviderFatal):
        parse_openai_chat_response({"choices": [{"message": {"content": None}}]})


def test_parse_ollama_happy() -> None:
    assert parse_ollama_response({"message": {"content": "yo"}}) == "yo"


def test_parse_ollama_missing_field_is_fatal() -> None:
    with pytest.raises(ProviderFatal):
        parse_ollama_response({"message": {}})


def test_parse_ollama_null_content_is_fatal_not_attributeerror() -> None:
    with pytest.raises(ProviderFatal):
        parse_ollama_response({"message": {"content": None}})


def test_parse_ollama_empty_completion_is_fatal() -> None:
    with pytest.raises(ProviderFatal):
        parse_ollama_response({"message": {"content": "   "}})


# ---- PURE map_claude_exception (matched by class NAME + status_code, no SDK) ---------------
def test_map_claude_ratelimit_by_name_is_quota() -> None:
    class RateLimitError(Exception):
        status_code = 429

    assert isinstance(map_claude_exception(RateLimitError()), ProviderQuotaExceeded)


def test_map_claude_connection_by_name_is_unavailable() -> None:
    class APIConnectionError(Exception): ...

    assert isinstance(map_claude_exception(APIConnectionError()), ProviderUnavailable)


def test_map_claude_timeout_by_name_is_unavailable() -> None:
    class APITimeoutError(Exception): ...

    assert isinstance(map_claude_exception(APITimeoutError()), ProviderUnavailable)


def test_map_claude_4xx_is_fatal() -> None:
    class APIStatusError(Exception):
        status_code = 400

    assert isinstance(map_claude_exception(APIStatusError()), ProviderFatal)


def test_map_claude_5xx_is_unavailable() -> None:
    class APIStatusError(Exception):
        status_code = 503

    assert isinstance(map_claude_exception(APIStatusError()), ProviderUnavailable)


def test_map_claude_unknown_is_unavailable_default() -> None:
    assert isinstance(map_claude_exception(RuntimeError("?")), ProviderUnavailable)


def test_map_claude_passes_through_providererror() -> None:
    pe = ProviderFatal("already classified")
    assert map_claude_exception(pe) is pe


def test_map_claude_ratelimit_name_beats_4xx_status() -> None:
    # DA: precedence — a RateLimitError that also carries a 4xx status_code must map to QUOTA
    # (retryable-against-next), NOT Fatal. A reordered impl that checks 4xx first would flip it.
    class RateLimitError(Exception):
        status_code = 400

    assert isinstance(map_claude_exception(RateLimitError()), ProviderQuotaExceeded)


# ---- _body builders (DeepSeek/Ollama) + URL shape (Fact-Checker: no /v1/) ------------------
def test_deepseek_body_shape() -> None:
    body = DeepSeekDJ(model="deepseek-chat", api_key="k")._body("sysp", "userp")
    assert body["model"] == "deepseek-chat"
    assert body["messages"] == [
        {"role": "system", "content": "sysp"},
        {"role": "user", "content": "userp"},
    ]


def test_deepseek_url_has_no_v1_segment() -> None:
    assert DeepSeekDJ(model="m", api_key="k")._url == "https://api.deepseek.com/chat/completions"


def test_ollama_body_shape_streams_false() -> None:
    body = OllamaDJ(model="llama3", endpoint="http://lan:11434")._body("s", "u")
    assert body["model"] == "llama3" and body["stream"] is False


def test_ollama_url_built_from_endpoint() -> None:
    assert OllamaDJ(model="m", endpoint="http://lan:11434/")._url == "http://lan:11434/api/chat"


# ---- ClaudeDJ: REAL to_thread offload (get_ident), no SDK import ---------------------------
async def test_claudedj_offload_runs_off_the_main_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    main_ident = threading.get_ident()
    seen: dict[str, int] = {}

    def fake_blocking(self: ClaudeDJ, system: str, user: str) -> str:
        seen["ident"] = threading.get_ident()
        return "patter!"

    monkeypatch.setattr(ClaudeDJ, "_blocking_call", fake_blocking)
    out = await ClaudeDJ(model="m", api_key="k").patter(_ctx())
    assert out == "patter!"
    assert seen["ident"] != main_ident  # really offloaded via asyncio.to_thread (R23)


async def test_claudedj_none_context_is_fatal() -> None:
    with pytest.raises(ProviderFatal):
        await ClaudeDJ(model="m", api_key="k").patter(None)


async def test_claudedj_reraises_providererror_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    # a ProviderError from the (faked) blocking call (e.g. parse_claude_response classified it)
    # must surface as-is, NOT be re-wrapped by map_claude_exception.
    def boom(self: ClaudeDJ, system: str, user: str) -> str:
        raise ProviderFatal("claude: response contained no text")

    monkeypatch.setattr(ClaudeDJ, "_blocking_call", boom)
    with pytest.raises(ProviderFatal):
        await ClaudeDJ(model="m", api_key="k").patter(_ctx())


async def test_claudedj_maps_blocking_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    class RateLimitError(Exception):
        status_code = 429

    def boom(self: ClaudeDJ, system: str, user: str) -> str:
        raise RateLimitError()

    monkeypatch.setattr(ClaudeDJ, "_blocking_call", boom)
    with pytest.raises(ProviderQuotaExceeded):
        await ClaudeDJ(model="m", api_key="k").patter(_ctx())


# ---- DeepSeek/Ollama: post_json monkeypatched at the helper seam ---------------------------
async def test_deepseekdj_patter_happy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pirate_radio.dj.text.post_json",
        _areturn({"choices": [{"message": {"content": "spun up"}}]}),
    )
    assert await DeepSeekDJ(model="m", api_key="k").patter(_ctx()) == "spun up"


async def test_deepseekdj_patter_maps_429(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*a: object, **k: object) -> dict[str, object]:
        raise ProviderQuotaExceeded("429")

    monkeypatch.setattr("pirate_radio.dj.text.post_json", boom)
    with pytest.raises(ProviderQuotaExceeded):
        await DeepSeekDJ(model="m", api_key="k").patter(_ctx())


async def test_deepseekdj_none_context_is_fatal() -> None:
    with pytest.raises(ProviderFatal):
        await DeepSeekDJ(model="m", api_key="k").patter(None)


async def test_ollamadj_patter_happy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pirate_radio.dj.text.post_json", _areturn({"message": {"content": "hi"}}))
    assert await OllamaDJ(model="m", endpoint="http://lan:11434").patter(_ctx()) == "hi"


async def test_ollamadj_none_context_is_fatal() -> None:
    with pytest.raises(ProviderFatal):
        await OllamaDJ(model="m", endpoint="http://x").patter(None)


# ---- H22 secret hygiene: the api_key never appears in a raised error (named at the leak site) -
async def test_claudedj_error_never_contains_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "SUPER_SECRET_KEY"

    def boom(self: ClaudeDJ, system: str, user: str) -> str:
        raise RuntimeError("upstream 401 unauthorized")  # a realistic error, no key in it

    monkeypatch.setattr(ClaudeDJ, "_blocking_call", boom)
    with pytest.raises(ProviderError) as ei:
        await ClaudeDJ(model="m", api_key=secret).patter(_ctx())
    assert secret not in str(ei.value)  # our code never interpolates the key into the error


async def test_deepseekdj_error_never_contains_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "SUPER_SECRET_KEY"

    async def boom(*a: object, **k: object) -> dict[str, object]:
        raise ProviderFatal("deepseek client error 401: unauthorized")

    monkeypatch.setattr("pirate_radio.dj.text.post_json", boom)
    with pytest.raises(ProviderError) as ei:
        await DeepSeekDJ(model="m", api_key=secret).patter(_ctx())
    assert secret not in str(ei.value)


# ---- R21 import guards (H28) ---------------------------------------------------------------
async def test_no_sdk_imported_during_faked_run(monkeypatch: pytest.MonkeyPatch) -> None:
    # DA: POSITIVE guard — patch __import__ to RAISE if the faked path imports anthropic/httpx.
    # This proves the negative directly (vs the order-fragile pop-then-assert-absent).
    real_import = builtins.__import__

    def guard(name: str, *a: object, **k: object) -> Any:
        if name.split(".")[0] in {"anthropic", "httpx"}:
            raise AssertionError(f"faked path imported {name!r} (R21 violation)")
        return real_import(name, *a, **k)

    monkeypatch.setattr(ClaudeDJ, "_blocking_call", lambda self, s, u: "x")
    monkeypatch.setattr(
        "pirate_radio.dj.text.post_json",
        _areturn({"choices": [{"message": {"content": "y"}}]}),
    )
    monkeypatch.setattr(builtins, "__import__", guard)
    await ClaudeDJ(model="m", api_key="k").patter(_ctx())  # no anthropic import
    await DeepSeekDJ(model="m", api_key="k").patter(_ctx())  # no httpx import


def test_no_top_level_network_imports() -> None:
    # H28 grep guard (ast-based — robust vs a string split): a future edit that hoists
    # `import anthropic`/`import httpx` (or `from ... import`, `import ... as`) to MODULE SCOPE
    # re-couples CI to a real SDK/socket. ast walks only the module body, so a lazy import inside
    # a function/method, or a TYPE_CHECKING block, is correctly allowed.
    for path in sorted(_SRC.glob("dj/*.py")):
        tree = ast.parse(path.read_text())
        for node in tree.body:  # module scope only
            roots: list[str] = []
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                roots = [(node.module or "").split(".")[0]]
            assert "anthropic" not in roots, f"{path.name} hoisted anthropic to module scope"
            assert "httpx" not in roots, f"{path.name} hoisted httpx to module scope"


def test_claudedj_and_others_satisfy_text_generator() -> None:
    from pirate_radio.dj.protocols import TextGenerator

    assert isinstance(ClaudeDJ(model="m", api_key="k"), TextGenerator)
    assert isinstance(DeepSeekDJ(model="m", api_key="k"), TextGenerator)
    assert isinstance(OllamaDJ(model="m", endpoint="http://x"), TextGenerator)
