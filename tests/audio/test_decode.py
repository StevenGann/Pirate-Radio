"""RED tests for ``pirate_radio.audio.decode`` — Decoder + FakeDecoder — §4.7.

Tests first: the Decoder Protocol seam and the Phase-1 FakeDecoder that returns a
silent buffer at the track's EXACT metadata duration (§7) so the player's timing math
is real even though the audio is silence. Real ffmpeg decode is Phase 2 (H7 streaming).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pirate_radio.audio.buffer import DEFAULT_SAMPLE_RATE, AudioBuffer
from pirate_radio.audio.decode import Decoder, FakeDecoder
from pirate_radio.catalog.models import Track

_TRACK = Track(path=Path("/lib/classical/x.flac"), group="classical", duration=12.5)


def test_fake_decoder_satisfies_protocol() -> None:
    assert isinstance(FakeDecoder(), Decoder)


@pytest.mark.parametrize("seconds", [12.5, 47.0])
async def test_fake_decoder_returns_silence_at_exact_track_duration(seconds: float) -> None:
    # Two distinct durations: a hardcoded-constant decoder fails (DA) — this pins that
    # FakeDecoder reads track.duration, which is the stub's entire reason to exist (§7).
    track = Track(path=Path("/lib/g/x.flac"), group="g", duration=seconds)
    buf = await FakeDecoder().decode(track)
    assert isinstance(buf, AudioBuffer)
    assert buf.duration_seconds == pytest.approx(seconds)
    assert not buf.samples.any()  # silent


async def test_fake_decoder_default_sample_rate_is_shared_constant() -> None:
    buf = await FakeDecoder().decode(_TRACK)
    assert buf.sample_rate == DEFAULT_SAMPLE_RATE


async def test_fake_decoder_default_channels_is_mono() -> None:
    assert (await FakeDecoder().decode(_TRACK)).channels == 1


async def test_fake_decoder_honors_constructor_args() -> None:
    buf = await FakeDecoder(sample_rate=8_000, channels=2).decode(_TRACK)
    assert buf.sample_rate == 8_000
    assert buf.channels == 2
    assert buf.duration_seconds == pytest.approx(12.5)  # duration still exact
