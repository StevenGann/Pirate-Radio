"""RED tests for ``pirate_radio.audio.resample`` — Phase 2 plan §4.2 (Q2: ONE resampler).

Tests first. ``to_rate`` converts an ``AudioBuffer`` to a target sample rate via
``scipy.signal.resample_poly`` (polyphase, per-channel). Pinned:
  - frame count = round(in_frames * target/source) ± 1 (polyphase edge), both polarities;
  - output.sample_rate == target, dtype float32, channels preserved;
  - mono AND stereo;
  - no-op identity: ``to_rate(buf, buf.sample_rate) is buf`` (no allocation when already at rate);
  - ``target_rate <= 0`` raises ValueError;
  - energy (RMS) is approximately preserved — proves it actually resamples, not relabels.
"""

from __future__ import annotations

import numpy as np
import pytest

from pirate_radio.audio.buffer import AudioBuffer
from pirate_radio.audio.resample import to_rate


def _tone(freq: float, amp: float, seconds: float, sr: int, channels: int = 1) -> AudioBuffer:
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False, dtype=np.float32)
    mono = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    samples = np.column_stack([mono] * channels) if channels > 1 else mono.reshape(-1, 1)
    return AudioBuffer(np.ascontiguousarray(samples), sr, channels)


def _rms(buf: AudioBuffer) -> float:
    return float(np.sqrt(np.mean(np.square(buf.samples, dtype=np.float64))))


def test_upsample_22050_to_48000_frame_count_rate_dtype() -> None:
    src = _tone(1000.0, 0.5, 1.0, 22_050)
    out = to_rate(src, 48_000)
    assert out.sample_rate == 48_000
    assert out.channels == 1
    assert out.samples.dtype == np.float32
    expected = round(src.frames * 48_000 / 22_050)
    assert abs(out.frames - expected) <= 1


def test_downsample_48000_to_22050_frame_count() -> None:
    src = _tone(1000.0, 0.5, 1.0, 48_000)
    out = to_rate(src, 22_050)
    assert out.sample_rate == 22_050
    assert out.channels == 1
    assert out.samples.dtype == np.float32
    expected = round(src.frames * 22_050 / 48_000)
    assert abs(out.frames - expected) <= 1


def test_stereo_is_resampled_independently_per_channel() -> None:
    # DISTINCT content per channel: a lazy impl that resamples ch0 and copies it to ch1
    # (or resamples the wrong axis) would be caught here, unlike identical channels.
    sr = 22_050
    t = np.linspace(0, 1.0, sr, endpoint=False, dtype=np.float32)
    ch0 = (0.5 * np.sin(2 * np.pi * 1000.0 * t)).astype(np.float32)
    ch1 = (0.3 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
    src = AudioBuffer(np.ascontiguousarray(np.column_stack([ch0, ch1])), sr, 2)
    out = to_rate(src, 48_000)
    assert out.channels == 2 and out.samples.shape[1] == 2
    assert out.sample_rate == 48_000 and out.samples.dtype == np.float32
    assert abs(out.frames - round(src.frames * 48_000 / sr)) <= 1
    assert not np.allclose(out.samples[:, 0], out.samples[:, 1])  # channels stay distinct
    # each output channel preserves ITS source channel's energy
    rms = lambda x: float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))  # noqa: E731
    assert abs(rms(out.samples[:, 0]) - rms(ch0)) < 0.005
    assert abs(rms(out.samples[:, 1]) - rms(ch1)) < 0.005


def test_no_op_returns_the_same_object() -> None:
    src = _tone(1000.0, 0.5, 1.0, 48_000)
    assert to_rate(src, 48_000) is src  # identity: no allocation when already at rate


def test_non_positive_target_rate_raises() -> None:
    # match= pins that OUR guard fires (naming target_rate), not scipy's downstream error.
    src = _tone(1000.0, 0.5, 0.1, 48_000)
    with pytest.raises(ValueError, match="target_rate"):
        to_rate(src, 0)
    with pytest.raises(ValueError, match="target_rate"):
        to_rate(src, -48_000)


def test_duration_is_preserved() -> None:
    # A relabel-only impl (same samples, new rate label) would change duration -> fails.
    src = _tone(1000.0, 0.5, 1.0, 22_050)
    out = to_rate(src, 48_000)
    assert abs(out.duration_seconds - src.duration_seconds) < 0.01


def test_energy_is_approximately_preserved_both_polarities() -> None:
    # Resampling preserves signal energy (RMS); proves real resampling, not garbage/zeros.
    up = to_rate(_tone(1000.0, 0.5, 1.0, 22_050), 48_000)
    assert abs(_rms(up) - _rms(_tone(1000.0, 0.5, 1.0, 22_050))) < 0.005
    down = to_rate(_tone(1000.0, 0.5, 1.0, 48_000), 22_050)
    assert abs(_rms(down) - _rms(_tone(1000.0, 0.5, 1.0, 48_000))) < 0.005
