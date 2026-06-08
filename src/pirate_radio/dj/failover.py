"""Ranked provider failover (§9.3, R15, R7). ONE generic wrapper used for BOTH the
TextGenerator chain (Claude->DeepSeek->Ollama->NullDJ) and the TTSEngine chain ([station tts
list]->silence floor). Tries each provider in order; on ANY failure FALLS THROUGH to the next
(R15): retryable (Unavailable/QuotaExceeded) AND Fatal alike are "this provider can't serve
THIS request" — Fatal is terminal FOR THAT PROVIDER, not the chain (§9.3 "never dead air"). A
non-ProviderError is re-typed to ProviderUnavailable so the floor is TOTAL — a provider bug can
never escape the chain to crash the producer. Raises ProviderUnavailable only when EVERY
provider is exhausted; the producer's R11 backstop catches that. Each wrapper satisfies the SAME
Protocol it wraps -> drop-in.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, TypeVar

from pirate_radio.errors import ProviderError, ProviderUnavailable

if TYPE_CHECKING:
    from pirate_radio.audio.buffer import AudioBuffer
    from pirate_radio.dj.context import DjContext

logger = logging.getLogger(__name__)

T = TypeVar("T")  # the call's return type: str (patter) or AudioBuffer (synthesize)


async def _ranked_call(
    providers: Sequence[object],
    call: Callable[[object], Awaitable[T]],
    *,
    op: str,
) -> T:
    """Try each provider's ``call`` in order; fall through on ANY failure; raise when exhausted.
    PURE control flow over the injected ``call`` — unit-tested entirely with fake providers."""
    if not providers:
        raise ProviderUnavailable(f"{op}: no providers configured")
    last: ProviderError | None = None
    for i, provider in enumerate(providers):
        try:
            return await call(provider)
        except Exception as raw:  # noqa: BLE001 — the floor must be TOTAL (DA HIGH)
            # A ProviderError is the expected, classified failure. ANYTHING else (e.g. a
            # ValueError from build_user_prompt on a bad kind, or any provider bug) is re-typed
            # to ProviderUnavailable so it ALSO skips to the next provider and ultimately the
            # floor -- a provider's exception can never escape the chain to crash the producer.
            exc: ProviderError = (
                raw
                if isinstance(raw, ProviderError)
                else ProviderUnavailable(
                    f"{type(provider).__name__} raised non-ProviderError "
                    f"{type(raw).__name__}: {raw}"
                )
            )
            last = exc
            logger.warning(
                "%s: provider %d/%d (%s) failed (%s) -> next (R15/§9.3)",
                op,
                i + 1,
                len(providers),
                type(provider).__name__,
                exc,
            )
            continue  # retryable, Fatal, AND unexpected errors all skip to the next provider
    # exhausted every provider; surface a retryable error so the R11 backstop fires
    raise ProviderUnavailable(
        f"{op}: all {len(providers)} providers failed; last: {last}"
    ) from last


class RankedTextGenerator:
    """A TextGenerator (Protocol drop-in) over an ordered list of TextGenerators (§12)."""

    def __init__(self, providers: Sequence[object]) -> None:
        self._providers = tuple(providers)

    async def patter(self, item_kind: str, context: DjContext | None) -> str:
        return await _ranked_call(
            self._providers,
            lambda p: p.patter(item_kind, context),  # type: ignore[attr-defined]
            op="patter",
        )


class RankedTTSEngine:
    """A TTSEngine (Protocol drop-in) over an ordered list of TTSEngines (§12 per-station tts)."""

    def __init__(self, providers: Sequence[object]) -> None:
        self._providers = tuple(providers)

    async def synthesize(self, text: str) -> AudioBuffer:
        return await _ranked_call(
            self._providers,
            lambda p: p.synthesize(text),  # type: ignore[attr-defined]
            op="synthesize",
        )
