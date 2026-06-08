"""Sample-rate conversion (pure, unit-tested). ONE resampler in the codebase (Q2):
``scipy.signal.resample_poly``. Decode resamples ffmpeg-side (``-ar``); TTS WAVs come back
at the voice's native rate (~22.05 kHz) and are converted here — no second ffmpeg subprocess.
"""

from __future__ import annotations

from math import gcd

import numpy as np
from scipy.signal import resample_poly

from pirate_radio.audio.buffer import AudioBuffer


def to_rate(buf: AudioBuffer, target_rate: int) -> AudioBuffer:
    """Return a NEW ``AudioBuffer`` resampled to ``target_rate`` (per-channel polyphase).

    Identity no-op (returns the SAME object) when already at ``target_rate``. Output frame
    count is ``round(in_frames * target/source)`` (± 1 at the polyphase edge).
    """
    if target_rate <= 0:
        raise ValueError(f"target_rate must be > 0, got {target_rate}")
    if buf.sample_rate == target_rate:
        return buf  # no-op identity (no allocation)
    g = gcd(buf.sample_rate, target_rate)
    up, down = target_rate // g, buf.sample_rate // g
    out = resample_poly(buf.samples, up, down, axis=0).astype(np.float32)  # per-channel (axis=0)
    return AudioBuffer(np.ascontiguousarray(out), target_rate, buf.channels)
