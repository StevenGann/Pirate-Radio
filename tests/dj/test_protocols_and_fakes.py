"""RED tests for ``pirate_radio.dj`` protocols + fakes — Phase 1 plan §4.7.

Tests first: the TextGenerator/TTSEngine/AudioSink Protocol seams and the Phase-1
fakes (NullDJ = the DJ-brain floor; StubTTS = logs-what-it-would-say + silent buffer
of real length; FakeAudioSink = records buffers for pipeline tests). Async via
asyncio_mode="auto". H5: the fakes default to the shared DEFAULT_SAMPLE_RATE.
"""

from __future__ import annotations

import logging

import pytest

from pirate_radio.audio.buffer import DEFAULT_SAMPLE_RATE, AudioBuffer
from pirate_radio.dj.fakes import FakeAudioSink, NullDJ, StubTTS
from pirate_radio.dj.protocols import AudioSink, TextGenerator, TTSEngine


def test_fakes_satisfy_their_protocols() -> None:
    assert isinstance(NullDJ(), TextGenerator)
    assert isinstance(StubTTS(), TTSEngine)
    assert isinstance(FakeAudioSink(), AudioSink)


async def test_nulldj_returns_empty_patter() -> None:
    assert await NullDJ().patter("station_id", None) == ""


async def test_stubtts_minimum_duration_floor() -> None:
    buf = await StubTTS().synthesize("")
    assert isinstance(buf, AudioBuffer)
    assert buf.duration_seconds == pytest.approx(0.5)  # max(0.5, 0 words)


async def test_stubtts_duration_scales_with_word_count_and_wpm() -> None:
    # wpm=120 makes the /wpm divisor NON-trivial (4 words / 120 * 60 = 2.0 s); a
    # wpm=60 case would let an impl ignore words_per_minute and still pass (DA).
    buf = await StubTTS(words_per_minute=120.0).synthesize("one two three four")
    assert buf.duration_seconds == pytest.approx(2.0)


async def test_stubtts_returns_silent_buffer() -> None:
    buf = await StubTTS().synthesize("hello world")
    assert not buf.samples.any()


async def test_stubtts_is_deterministic_for_identical_text() -> None:
    a = await StubTTS().synthesize("hello world")
    b = await StubTTS().synthesize("hello world")
    assert a.duration_seconds == b.duration_seconds


async def test_stubtts_logs_announcement(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        await StubTTS().synthesize("good evening listeners")
    assert any("good evening listeners" in r.getMessage() for r in caplog.records)


async def test_stubtts_default_sample_rate_is_shared_constant() -> None:
    # H5: StubTTS must default to the SAME rate as AudioBuffer.silence to avoid a
    # producer/backstop rate desync.
    buf = await StubTTS().synthesize("x")
    assert buf.sample_rate == DEFAULT_SAMPLE_RATE


async def test_stubtts_default_channels_is_mono() -> None:
    # H5 (channels): same desync guard as sample_rate — both buffer producers default mono.
    buf = await StubTTS().synthesize("hello")
    assert buf.channels == 1


async def test_fake_audio_sink_records_buffers_and_total() -> None:
    sink = FakeAudioSink()
    await sink.play(AudioBuffer.silence(seconds=1.0))
    await sink.play(AudioBuffer.silence(seconds=0.5))
    assert len(sink.played) == 2
    assert sink.total_seconds == pytest.approx(1.5)
