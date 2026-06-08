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

logger = logging.getLogger(__name__)


class NullDJ:
    """The DJ-brain floor (§9.3 / D2): produces no patter."""

    async def patter(self, item_kind: str, context: object | None = None) -> str:
        return ""


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


class FakeAudioSink:
    """Records every played buffer; pipeline tests assert ordering + totals (R21)."""

    def __init__(self) -> None:
        self.played: list[AudioBuffer] = []

    async def play(self, buf: AudioBuffer) -> None:
        self.played.append(buf)

    @property
    def total_seconds(self) -> float:
        return sum(b.duration_seconds for b in self.played)
