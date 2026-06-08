"""RED tests for ``pirate_radio.audio.buffer`` — AudioBuffer (R14), Phase 1 §4.2.

Tests first: the one normalized buffer shape every pipeline stage produces/consumes —
float32, 2-D (frames, channels) — with a frozen, self-validating contract. H5: a
single shared DEFAULT_SAMPLE_RATE constant prevents producer/silence rate desync.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from pirate_radio.audio.buffer import DEFAULT_SAMPLE_RATE, AudioBuffer


def test_valid_buffer_exposes_frames_and_duration() -> None:
    buf = AudioBuffer(np.zeros((48_000, 2), dtype=np.float32), sample_rate=48_000, channels=2)
    assert buf.frames == 48_000
    assert buf.duration_seconds == pytest.approx(1.0)


def test_silence_factory_shape_and_dtype() -> None:
    buf = AudioBuffer.silence(seconds=0.5, sample_rate=8_000, channels=1)
    assert buf.samples.shape == (4_000, 1)
    assert buf.samples.dtype == np.float32
    assert buf.duration_seconds == pytest.approx(0.5)
    assert not buf.samples.any()  # all zeros


def test_silence_default_sample_rate_is_the_shared_constant() -> None:
    # H5: the silence/backstop default must match the producer's default rate.
    assert AudioBuffer.silence(seconds=1.0).sample_rate == DEFAULT_SAMPLE_RATE


def test_rejects_non_positive_sample_rate() -> None:
    with pytest.raises(ValueError):
        AudioBuffer(np.zeros((10, 1), dtype=np.float32), sample_rate=0, channels=1)


def test_rejects_one_dimensional_samples() -> None:
    with pytest.raises(ValueError):
        AudioBuffer(np.zeros(10, dtype=np.float32), sample_rate=48_000, channels=1)


def test_rejects_channel_count_mismatch() -> None:
    with pytest.raises(ValueError):
        AudioBuffer(np.zeros((10, 2), dtype=np.float32), sample_rate=48_000, channels=1)


def test_rejects_non_float32_dtype() -> None:
    with pytest.raises(ValueError):
        AudioBuffer(np.zeros((10, 1), dtype=np.float64), sample_rate=48_000, channels=1)


def test_rejects_zero_channels() -> None:
    # A degenerate (n, 0) buffer passes the channel==shape[1] check but is invalid.
    with pytest.raises(ValueError):
        AudioBuffer(np.zeros((10, 0), dtype=np.float32), sample_rate=48_000, channels=0)


def test_silence_rounds_fractional_frames_not_truncates() -> None:
    # 0.0002s * 8000Hz = 1.6 frames -> round() gives 2; a naive int() would give 1.
    assert AudioBuffer.silence(seconds=0.0002, sample_rate=8_000).frames == 2


def test_silence_zero_seconds_is_empty_mono() -> None:
    buf = AudioBuffer.silence(seconds=0.0)
    assert buf.frames == 0
    assert buf.samples.shape == (0, 1)  # default channels=1
    assert buf.duration_seconds == 0.0


def test_buffer_is_frozen() -> None:
    buf = AudioBuffer.silence(seconds=0.1)
    with pytest.raises(FrozenInstanceError):
        buf.sample_rate = 22_050  # type: ignore[misc]
