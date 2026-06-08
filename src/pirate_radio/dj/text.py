"""Network LLM TextGenerators (D2): ClaudeDJ, DeepSeekDJ, OllamaDJ.

Each: build_system/user_prompt (PURE, dj/prompts.py) -> the ONE network call (lazily imported,
R21) -> parse_*_response (PURE) -> str. Every failure maps to a typed ProviderError (R15) via a
PURE mapper so dj/failover.py can branch on the subtype. NullDJ (the text floor) stays in
dj/fakes.py. R23: the Anthropic SYNC SDK hops via asyncio.to_thread; DeepSeek/Ollama use the
shared native-async ``post_json`` helper (dj/_http.py). NOTHING network is imported at module
scope (R21); the only ``pragma: no cover`` lines are the literal Claude network calls (R20).
"""

from __future__ import annotations

import asyncio
from typing import Any

from pirate_radio.dj._http import post_json
from pirate_radio.dj.context import DjContext
from pirate_radio.dj.prompts import build_system_prompt, build_user_prompt
from pirate_radio.errors import (
    ProviderError,
    ProviderFatal,
    ProviderQuotaExceeded,
    ProviderUnavailable,
)

_MAX_TOKENS = 256  # patter is short; bounds cost (H27) and latency


# ---- PURE response parsers (unit-tested with fake/dict payloads, no network) ---------------
def parse_claude_response(resp: object) -> str:
    """PURE: Anthropic Messages response -> the text. ProviderFatal on empty/unexpected shape.
    A block whose ``.text`` is None is coerced to "" (never a bare TypeError from join)."""
    blocks = getattr(resp, "content", None)
    if not blocks:
        raise ProviderFatal("claude: empty response content")
    text = "".join((getattr(b, "text", "") or "") for b in blocks).strip()
    if not text:
        raise ProviderFatal("claude: response contained no text")
    return text


def parse_openai_chat_response(data: dict[str, Any]) -> str:
    """PURE: OpenAI-compatible chat JSON (DeepSeek) -> text. ProviderFatal on missing/null."""
    try:
        text: str = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise ProviderFatal(f"deepseek: unexpected response shape ({exc})") from exc
    if not text:
        raise ProviderFatal("deepseek: empty completion")
    return text


def parse_ollama_response(data: dict[str, Any]) -> str:
    """PURE: Ollama /api/chat JSON -> text. ProviderFatal on missing/null fields."""
    try:
        text: str = data["message"]["content"].strip()
    except (KeyError, TypeError, AttributeError) as exc:
        raise ProviderFatal(f"ollama: unexpected response shape ({exc})") from exc
    if not text:
        raise ProviderFatal("ollama: empty completion")
    return text


# ---- PURE exception -> ProviderError mapper for Claude (no anthropic import — by NAME) ------
def map_claude_exception(exc: Exception) -> ProviderError:
    """PURE: a caught Anthropic exception -> typed ProviderError (R15 table §3.4).

    Matches by class NAME (not isinstance) so the mapper needs NO anthropic import (R21). Rate
    limit (by name OR status 429) is checked FIRST, so a RateLimitError that also carries a 4xx
    status still maps to QUOTA (retryable-against-next), not Fatal."""
    if isinstance(exc, ProviderError):
        return exc  # a parser already classified it; don't double-wrap
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)
    if name == "RateLimitError" or status == 429:
        return ProviderQuotaExceeded(f"claude rate/quota: {exc}")
    if name in ("APIConnectionError", "APITimeoutError"):
        return ProviderUnavailable(f"claude connection: {exc}")
    if isinstance(status, int) and 400 <= status < 500:
        return ProviderFatal(f"claude client error {status}: {exc}")
    if isinstance(status, int) and status >= 500:
        return ProviderUnavailable(f"claude server error {status}: {exc}")
    return ProviderUnavailable(f"claude error: {exc}")  # H18: retryable default


class ClaudeDJ:
    """Claude Messages backend (sync SDK via to_thread, R23). Network import is lazy (R21)."""

    def __init__(self, *, model: str, api_key: str, timeout_seconds: float = 20.0) -> None:
        self._model = model
        self._api_key = api_key
        self._timeout = timeout_seconds

    async def patter(self, context: DjContext | None) -> str:
        if context is None:  # defensive: failover only ever calls with a real context
            raise ProviderFatal("claude: DjContext required")
        system, user = build_system_prompt(context), build_user_prompt(context)
        try:
            return await asyncio.to_thread(self._blocking_call, system, user)  # R23
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 — re-typed by the pure mapper
            raise map_claude_exception(exc) from exc

    def _blocking_call(self, system: str, user: str) -> str:
        import anthropic  # R21: lazy — CI never imports the SDK

        client = anthropic.Anthropic(
            api_key=self._api_key, timeout=self._timeout
        )  # pragma: no cover
        resp = client.messages.create(  # pragma: no cover  (R20: the ONLY network line)
            model=self._model,
            max_tokens=_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return parse_claude_response(resp)  # PURE


class DeepSeekDJ:
    """DeepSeek (OpenAI-compatible chat, D2) over the shared httpx helper (native async, R23).

    Base URL ``https://api.deepseek.com`` + path ``/chat/completions`` (no ``/v1/`` segment; the
    host serves both, we pin the documented no-version form). Auth: ``Authorization: Bearer``."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        timeout_seconds: float = 20.0,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._timeout = timeout_seconds

    def _body(self, system: str, user: str) -> dict[str, object]:  # PURE, unit-tested
        return {
            "model": self._model,
            "max_tokens": _MAX_TOKENS,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

    async def patter(self, context: DjContext | None) -> str:
        if context is None:
            raise ProviderFatal("deepseek: DjContext required")
        system, user = build_system_prompt(context), build_user_prompt(context)
        headers = {"Authorization": f"Bearer {self._api_key}"}
        data = await post_json(
            "deepseek", self._url, headers, self._body(system, user), timeout=self._timeout
        )
        return parse_openai_chat_response(data)


class OllamaDJ:
    """Self-hosted Ollama on the LAN (D2 — NOT on the Pi). httpx /api/chat, native async."""

    def __init__(self, *, model: str, endpoint: str, timeout_seconds: float = 30.0) -> None:
        self._model = model
        self._url = f"{endpoint.rstrip('/')}/api/chat"
        self._timeout = timeout_seconds  # higher default: a LAN box may be loading the model

    def _body(self, system: str, user: str) -> dict[str, object]:  # PURE
        return {
            "model": self._model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

    async def patter(self, context: DjContext | None) -> str:
        if context is None:
            raise ProviderFatal("ollama: DjContext required")
        system, user = build_system_prompt(context), build_user_prompt(context)
        data = await post_json(
            "ollama", self._url, {}, self._body(system, user), timeout=self._timeout
        )
        return parse_ollama_response(data)
