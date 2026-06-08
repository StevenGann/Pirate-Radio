"""RED tests for ``pirate_radio.dj.failover`` — Phase 3 plan §4.4 / §5 / §6 (P3-4).

Tests first (strict spec-driven TDD): the ranked provider failover (§9.3, R15) — ONE generic
``_ranked_call`` core + two thin Protocol adapters (``RankedTextGenerator`` /
``RankedTTSEngine``). Tries each provider in order; on ANY failure FALLS THROUGH to the next:
retryable (Unavailable/QuotaExceeded) AND ``ProviderFatal`` alike (Fatal is terminal FOR THAT
PROVIDER, not the chain — §9.3 "never dead air"); a non-``ProviderError`` is re-typed to
``ProviderUnavailable`` so the floor is TOTAL. Raises ``ProviderUnavailable`` only when EVERY
provider is exhausted (so the producer's R11 backstop fires). FAKES ONLY, zero network (R21).
"""

from __future__ import annotations

import pytest

from pirate_radio.audio.buffer import DEFAULT_SAMPLE_RATE, AudioBuffer
from pirate_radio.dj.context import BlockContext, DjContext
from pirate_radio.dj.failover import RankedTextGenerator, RankedTTSEngine
from pirate_radio.dj.fakes import FailingTTS, NullDJ, ScriptedDJ, StubTTS
from pirate_radio.dj.protocols import TextGenerator, TTSEngine
from pirate_radio.errors import (
    ProviderError,
    ProviderFatal,
    ProviderQuotaExceeded,
    ProviderUnavailable,
)


def _ctx(kind: str = "intro") -> DjContext:
    return DjContext(kind=kind, persona="P", station_name="S", current_block=BlockContext(name="B"))


class _SpyTTS:
    """A TTS engine that records every synthesize() call — for the TTS-side laziness spy."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def synthesize(self, text: str) -> AudioBuffer:
        self.calls.append(text)
        return AudioBuffer.silence(seconds=0.5, sample_rate=DEFAULT_SAMPLE_RATE)


# ---- Protocol satisfaction (drop-in) -------------------------------------------------------
def test_ranked_wrappers_satisfy_protocols() -> None:
    assert isinstance(RankedTextGenerator([NullDJ()]), TextGenerator)
    assert isinstance(RankedTTSEngine([StubTTS()]), TTSEngine)


# ---- text chain: fall-through on each retryable subtype ------------------------------------
async def test_first_unavailable_second_succeeds() -> None:
    chain = RankedTextGenerator(
        [ScriptedDJ(error=ProviderUnavailable("down")), ScriptedDJ(text="hi")]
    )
    assert await chain.patter("intro", _ctx()) == "hi"


async def test_quota_exceeded_falls_through() -> None:
    chain = RankedTextGenerator(
        [ScriptedDJ(error=ProviderQuotaExceeded("429")), ScriptedDJ(text="hi")]
    )
    assert await chain.patter("intro", _ctx()) == "hi"


async def test_provider_fatal_skips_to_next() -> None:
    # §7-Q2 ratified: Fatal is terminal FOR THAT PROVIDER, not the chain
    chain = RankedTextGenerator([ScriptedDJ(error=ProviderFatal("bad key")), ScriptedDJ(text="hi")])
    assert await chain.patter("intro", _ctx()) == "hi"


# ---- exhaustion: raises ProviderUnavailable so R11 backstop fires --------------------------
async def test_all_fail_raises_unavailable_for_backstop() -> None:
    chain = RankedTextGenerator(
        [ScriptedDJ(error=ProviderFatal("x")), ScriptedDJ(error=ProviderUnavailable("y"))]
    )
    with pytest.raises(ProviderUnavailable):
        await chain.patter("intro", _ctx())


async def test_all_fatal_still_raises_unavailable_not_fatal() -> None:
    # §7-Q2: even an all-Fatal chain surfaces a RETRYABLE error so the backstop path fires
    chain = RankedTextGenerator(
        [ScriptedDJ(error=ProviderFatal("a")), ScriptedDJ(error=ProviderFatal("b"))]
    )
    with pytest.raises(ProviderUnavailable):
        await chain.patter("intro", _ctx())


async def test_empty_chain_raises_unavailable() -> None:
    with pytest.raises(ProviderUnavailable):
        await RankedTextGenerator([]).patter("intro", _ctx())


# ---- the NullDJ floor: degrades to "" (never raises) --------------------------------------
async def test_nulldj_floor_yields_empty_not_raise() -> None:
    chain = RankedTextGenerator([ScriptedDJ(error=ProviderUnavailable("x")), NullDJ()])
    assert await chain.patter("intro", _ctx()) == ""  # D2 floor: degrade to no patter


# ---- order: first success wins, later providers never called -------------------------------
async def test_order_preserved_first_success_wins() -> None:
    chain = RankedTextGenerator([ScriptedDJ(text="A"), ScriptedDJ(text="B")])
    assert await chain.patter("intro", _ctx()) == "A"


async def test_order_spy_second_provider_never_called() -> None:
    first, second = ScriptedDJ(text="A"), ScriptedDJ(text="B")
    chain = RankedTextGenerator([first, second])
    assert await chain.patter("intro", _ctx()) == "A"
    assert first.calls and second.calls == []  # #2 never invoked


# ---- the floor is TOTAL: a non-ProviderError is contained and skipped (DA HIGH) ------------
async def test_non_providererror_is_contained_and_skips() -> None:
    class _Boom:
        async def patter(self, item_kind: str, context: DjContext | None) -> str:
            raise ValueError("provider bug, NOT a ProviderError")

    chain = RankedTextGenerator([_Boom(), ScriptedDJ(text="hi")])
    assert await chain.patter("intro", _ctx()) == "hi"  # ValueError re-typed -> skipped


async def test_non_providererror_alone_surfaces_as_unavailable() -> None:
    class _Boom:
        async def patter(self, item_kind: str, context: DjContext | None) -> str:
            raise ValueError("bug")

    with pytest.raises(ProviderUnavailable):  # never escapes as a bare ValueError
        await RankedTextGenerator([_Boom()]).patter("intro", _ctx())


# ---- per-skip WARNING logging (Field-Op observability) ------------------------------------
async def test_failover_logs_warning_per_skip(caplog: pytest.LogCaptureFixture) -> None:
    chain = RankedTextGenerator(
        [ScriptedDJ(error=ProviderUnavailable("down")), ScriptedDJ(text="ok")]
    )
    with caplog.at_level("WARNING"):
        await chain.patter("intro", _ctx())
    assert any("failed" in r.message and "next" in r.message for r in caplog.records)


async def test_failover_warning_never_leaks_on_first_success(
    caplog: pytest.LogCaptureFixture,
) -> None:
    chain = RankedTextGenerator([ScriptedDJ(text="A")])
    with caplog.at_level("WARNING"):
        await chain.patter("intro", _ctx())
    assert not caplog.records  # a clean first-try success logs nothing


async def test_failover_logs_exactly_one_warning_per_skip(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Senior Dev: pin the "per-skip" claim — two failures before success => exactly two WARNINGs
    chain = RankedTextGenerator(
        [
            ScriptedDJ(error=ProviderUnavailable("a")),
            ScriptedDJ(error=ProviderFatal("b")),
            ScriptedDJ(text="ok"),
        ]
    )
    with caplog.at_level("WARNING"):
        await chain.patter("intro", _ctx())
    assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 2


# ---- TTS chain: same semantics over synthesize -------------------------------------------
async def test_ranked_tts_falls_through_to_silence_floor() -> None:
    chain = RankedTTSEngine([FailingTTS(error=ProviderUnavailable("eleven down")), StubTTS()])
    buf = await chain.synthesize("hello")
    assert buf.duration_seconds > 0  # the StubTTS floor served real-length audio


async def test_ranked_tts_fatal_skips_to_next() -> None:
    chain = RankedTTSEngine([FailingTTS(error=ProviderFatal("eleven 401")), StubTTS()])
    assert (await chain.synthesize("hi")).duration_seconds > 0  # 401 -> Piper/Stub floor


async def test_ranked_tts_all_fail_raises_unavailable() -> None:
    chain = RankedTTSEngine(
        [FailingTTS(error=ProviderFatal("x")), FailingTTS(error=ProviderUnavailable("y"))]
    )
    with pytest.raises(ProviderUnavailable):  # -> producer R11 backstop
        await chain.synthesize("hi")


async def test_ranked_tts_empty_chain_raises_unavailable() -> None:
    with pytest.raises(ProviderUnavailable):
        await RankedTTSEngine([]).synthesize("hi")


async def test_ranked_tts_order_spy_second_never_called() -> None:
    # DA: pin the TTS adapter's laziness independently (not merely inherited from the text spy)
    first, second = _SpyTTS(), _SpyTTS()
    chain = RankedTTSEngine([first, second])
    await chain.synthesize("hello")
    assert first.calls == ["hello"] and second.calls == []  # #2 never invoked on first success


# ---- the chain raises the BASE ProviderError type (catchable by the producer) -------------
async def test_exhaustion_error_is_a_providererror() -> None:
    with pytest.raises(ProviderError):  # ProviderUnavailable IS-A ProviderError
        await RankedTextGenerator([ScriptedDJ(error=ProviderFatal("x"))]).patter("intro", _ctx())
