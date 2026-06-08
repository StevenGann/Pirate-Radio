"""The shared async-HTTP seam for the httpx-backed providers (DeepSeek, Ollama, ElevenLabs) +
the PURE HTTP error mappers (R15).

NOTHING network at module scope (R21): ``httpx`` is imported inside ``post_json``.
``map_http_status``/``map_httpx_exception`` are PURE and importable by BOTH ``dj/text.py`` and
``dj/tts.py``, so no backend module depends on a sibling backend module (no ``tts -> text``
import). The only ``pragma: no cover`` lines are the literal network calls (R20).
"""

from __future__ import annotations

from pirate_radio.errors import (
    ProviderError,
    ProviderFatal,
    ProviderQuotaExceeded,
    ProviderUnavailable,
)


def map_http_status(provider: str, status: int, body: str) -> ProviderError:
    """PURE: an HTTP status (DeepSeek/Ollama/ElevenLabs) -> typed ProviderError (R15, §3.4)."""
    if status == 429:
        return ProviderQuotaExceeded(f"{provider} rate/quota (429): {body[:200]}")
    if 400 <= status < 500:
        return ProviderFatal(f"{provider} client error {status}: {body[:200]}")
    return ProviderUnavailable(f"{provider} server error {status}: {body[:200]}")  # 5xx/other


def map_httpx_exception(provider: str, exc: Exception) -> ProviderError:
    """PURE: a caught httpx transport exception -> typed ProviderError. Matched by class name
    so NO httpx import is needed here (R21)."""
    if isinstance(exc, ProviderError):
        return exc  # already classified; don't double-wrap
    name = type(exc).__name__  # ConnectError, ReadTimeout, ConnectTimeout, PoolTimeout, ...
    if "Timeout" in name or "Connect" in name or name == "TransportError":
        return ProviderUnavailable(f"{provider} transport: {exc}")
    return ProviderUnavailable(f"{provider} error: {exc}")  # H18: retryable default


async def post_json(
    provider: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, object],
    *,
    timeout: float,
) -> dict:
    """The ONE httpx POST->JSON path for DeepSeek + Ollama. Lazy import (R21); the network lines
    are the only ``pragma: no cover``; >=4xx -> map_http_status; transport errors ->
    map_httpx_exception (an already-typed ProviderError surfaces unchanged)."""
    import httpx  # R21: lazy — never imported at module scope / on the faked test path

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:  # pragma: no cover (network)
            resp = await client.post(url, headers=headers, json=body)  # pragma: no cover
            if resp.status_code >= 400:  # pragma: no cover
                raise map_http_status(provider, resp.status_code, resp.text)
            return resp.json()  # pragma: no cover
    except ProviderError:
        raise
    except Exception as exc:  # noqa: BLE001 — re-typed by the pure mapper
        raise map_httpx_exception(provider, exc) from exc
