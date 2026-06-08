"""AudioBuffer: the one buffer shape every pipeline stage produces/consumes (R14).

Normalized shape: float32 samples, 2-D ``(frames, channels)``. A mono buffer is
``(frames, 1)`` — never 1-D — so the player/sink never branch on rank. A frozen,
self-validating dataclass (not a Pydantic model): NumPy arrays are not natural
Pydantic fields and this object never round-trips through JSON (it stays in RAM).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

# H5: the single shared default sample rate. StubTTS / FakeDecoder / silence backstop
# all default to this so producer-rendered and silence buffers can never desync rate.
DEFAULT_SAMPLE_RATE = 48_000


@dataclass(frozen=True)
class AudioBuffer:
    samples: npt.NDArray[np.float32]  # shape (frames, channels), dtype float32
    sample_rate: int  # Hz, > 0
    channels: int  # >= 1, == samples.shape[1]

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError(f"sample_rate must be > 0, got {self.sample_rate}")
        if self.channels < 1:
            raise ValueError(f"channels must be >= 1, got {self.channels}")
        if self.samples.ndim != 2:
            raise ValueError(
                f"samples must be 2-D (frames, channels), got ndim={self.samples.ndim}"
            )
        if self.samples.shape[1] != self.channels:
            raise ValueError(
                f"channels={self.channels} != samples.shape[1]={self.samples.shape[1]}"
            )
        if self.samples.dtype != np.float32:
            raise ValueError(f"samples must be float32, got {self.samples.dtype}")

    @property
    def frames(self) -> int:
        return int(self.samples.shape[0])

    @property
    def duration_seconds(self) -> float:
        return self.frames / self.sample_rate

    @classmethod
    def silence(
        cls, *, seconds: float, sample_rate: int = DEFAULT_SAMPLE_RATE, channels: int = 1
    ) -> AudioBuffer:
        """A silent buffer of ``seconds`` (rounded to whole frames; negatives clamp to 0)."""
        frames = max(0, round(seconds * sample_rate))
        return cls(np.zeros((frames, channels), dtype=np.float32), sample_rate, channels)
