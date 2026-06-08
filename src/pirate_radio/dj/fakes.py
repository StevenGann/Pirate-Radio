"""Phase-1 fakes for the DJ/audio seams (no hardware, no network).

NullDJ is the DJ-brain floor (§9.3 / D2). StubTTS logs the announcement it WOULD
speak and returns a deterministic-length *silent* buffer (so timing is real, audio
is silent — §20). FakeAudioSink records buffers for the pipeline tests (R21). All
default to the shared ``DEFAULT_SAMPLE_RATE`` and mono so producer/backstop buffers
can never desync (H5).
"""

from __future__ import annotations

import logging

from pirate_radio.audio.buffer import DEFAULT_SAMPLE_RATE, AudioBuffer
from pirate_radio.dj.context import DjContext
from pirate_radio.errors import ProviderError, ProviderUnavailable

logger = logging.getLogger(__name__)


class NullDJ:
    """The DJ-brain floor (§9.3 / D2): produces no patter."""

    async def patter(self, context: DjContext | None = None) -> str:
        return ""


class ScriptedDJ:
    """Text-side analogue of ``StubTTS``/``FailingTTS`` (R21). Returns canned patter — a
    constant ``text``, or per-kind via ``by_kind`` — or raises a seeded ``ProviderError``
    (folding the old ``FailingDJ``; **the error wins** over any text/by_kind). Records every
    ``(kind, context)`` attempt BEFORE raising, so a failover order-spy sees failed attempts
    too (kind is read from ``context.kind`` — R16). Drives the P3-4 failover and P3-8 producer
    tests."""

    def __init__(
        self,
        *,
        text: str = "",
        by_kind: dict[str, str] | None = None,
        error: ProviderError | None = None,
    ) -> None:
        self._text = text
        self._by_kind = by_kind or {}
        self._error = error
        self.calls: list[tuple[str, DjContext | None]] = []

    async def patter(self, context: DjContext | None = None) -> str:
        kind = context.kind if context is not None else ""  # R16: kind rides on the context
        self.calls.append((kind, context))  # record-then-raise (diagnostics see attempts)
        if self._error is not None:
            raise self._error
        return self._by_kind.get(kind, self._text)


class StubTTS:
    """Phase-1 TTS stub: logs what it would say, returns silence of realistic length."""

    def __init__(
        self,
        *,
        words_per_minute: float = 150.0,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        channels: int = 1,
    ) -> None:
        self._wpm = words_per_minute
        self._sample_rate = sample_rate
        self._channels = channels

    async def synthesize(self, text: str) -> AudioBuffer:
        seconds = max(0.5, len(text.split()) / self._wpm * 60.0)
        logger.info("StubTTS would speak (%.1fs): %r", seconds, text)
        return AudioBuffer.silence(
            seconds=seconds, sample_rate=self._sample_rate, channels=self._channels
        )


class FailingTTS:
    """A TTS engine that always raises ``ProviderError`` (R15) — drives the pipeline's
    R11 backstop path in tests. The error class is configurable so a test can exercise
    both the retryable (``ProviderUnavailable``, default) and terminal (``ProviderFatal``)
    branches and prove the pipeline catches the *base* ``ProviderError``, not one leaf."""

    def __init__(self, *, error: ProviderError | None = None) -> None:
        self._error = error if error is not None else ProviderUnavailable("stub TTS failure")

    async def synthesize(self, text: str) -> AudioBuffer:
        raise self._error


class FakeAudioSink:
    """Records every played buffer; pipeline tests assert ordering + totals (R21)."""

    def __init__(self) -> None:
        self.played: list[AudioBuffer] = []

    async def play(self, buf: AudioBuffer) -> None:
        self.played.append(buf)

    @property
    def total_seconds(self) -> float:
        return sum(b.duration_seconds for b in self.played)
