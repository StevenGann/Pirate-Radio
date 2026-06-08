"""Decoder Protocol (R14) + FakeDecoder (Phase 1).

The real ``FfmpegDecoder`` (subprocess via ``asyncio.to_thread``, streaming/chunked
per H7, paired with loudness per R22) lands in Phase 2. Phase 1 uses ``FakeDecoder``:
a silent buffer at the track's EXACT metadata duration (§7) so the player's timing
math is real even though the audio is silence.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pirate_radio.audio.buffer import DEFAULT_SAMPLE_RATE, AudioBuffer
from pirate_radio.catalog.models import Track
from pirate_radio.errors import ProviderError, ProviderUnavailable


@runtime_checkable
class Decoder(Protocol):
    """Track file -> ``AudioBuffer`` (R14). Raises ``ProviderError`` (R15) on a
    bad/missing file. Blocking native decoders MUST use ``asyncio.to_thread``."""

    async def decode(self, track: Track) -> AudioBuffer: ...


class FakeDecoder:
    """Phase-1 decode stub: silence at the track's exact metadata duration (§7)."""

    def __init__(self, *, sample_rate: int = DEFAULT_SAMPLE_RATE, channels: int = 1) -> None:
        self._sample_rate = sample_rate
        self._channels = channels

    async def decode(self, track: Track) -> AudioBuffer:
        return AudioBuffer.silence(
            seconds=track.duration, sample_rate=self._sample_rate, channels=self._channels
        )


class FailingDecoder:
    """A decoder that always raises ``ProviderError`` (R15) — drives the pipeline's R11
    backstop path in tests. Error class configurable (default ``ProviderUnavailable``)."""

    def __init__(self, *, error: ProviderError | None = None) -> None:
        self._error = error if error is not None else ProviderUnavailable("stub decode failure")

    async def decode(self, track: Track) -> AudioBuffer:
        raise self._error
