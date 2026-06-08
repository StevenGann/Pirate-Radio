"""RED tests for ``pirate_radio.pipeline.producer`` — render-ahead (P1 no-drop, R11/R15).

Tests first. The producer renders each schedule item just ahead of the playhead: a
``track`` via the decoder, patter (station_id / block_transition / block_reminder) via
the TTS engine. P1: every item produces a segment, in order — nothing is dropped. R11/R15:
a ``ProviderError`` from a backend does NOT crash or drop; the producer substitutes the
canned backstop (and logs) so the player still has something to play.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pirate_radio.audio.buffer import AudioBuffer
from pirate_radio.audio.decode import FailingDecoder, FakeDecoder
from pirate_radio.catalog.models import Track
from pirate_radio.dj.fakes import FailingTTS, StubTTS
from pirate_radio.errors import ProviderFatal
from pirate_radio.pipeline.buffer import LookAheadBuffer
from pirate_radio.pipeline.producer import Producer, announcement_text
from pirate_radio.schedule.models import (
    BlockReminderItem,
    BlockTransitionItem,
    StationIdItem,
    TrackItem,
)

_TZ = ZoneInfo("America/New_York")
_T0 = datetime(2026, 6, 10, 0, 0, tzinfo=_TZ)
_BACKSTOP = AudioBuffer.silence(seconds=3.0)


def _track_item(dur: float) -> TrackItem:
    return TrackItem(
        planned_start=_T0,
        duration=dur,
        block_name="Morning",
        track=Track(path=Path(f"/lib/x/{dur}.flac"), group="x", duration=dur),
    )


def _id_item() -> StationIdItem:
    return StationIdItem(planned_start=_T0, duration=5.0, block_name="Morning")


def _drain(buf: LookAheadBuffer) -> list[object]:
    out: list[object] = []
    while (seg := buf.get_nowait()) is not None:
        out.append(seg)
    return out


async def test_renders_all_items_in_order_no_drop() -> None:
    items = [_track_item(10.0), _id_item(), _track_item(20.0)]
    buf = LookAheadBuffer(maxsize=10)
    await Producer(
        items=items, tts=StubTTS(), decoder=FakeDecoder(), buffer=buf, backstop=_BACKSTOP
    ).run()
    segs = _drain(buf)
    assert [s.item for s in segs] == items  # P1: same items, same order, none dropped


async def test_track_routes_to_decoder_patter_routes_to_tts() -> None:
    # FakeDecoder yields the track's EXACT duration; StubTTS yields a wpm-derived length.
    buf = LookAheadBuffer(maxsize=10)
    track = _track_item(33.0)
    await Producer(
        items=[track, _id_item()],
        tts=StubTTS(),
        decoder=FakeDecoder(),
        buffer=buf,
        backstop=_BACKSTOP,
    ).run()
    segs = _drain(buf)
    assert segs[0].audio.duration_seconds == 33.0  # decoder used the exact track duration
    # patter went through TTS, not the decoder: a short wpm-derived length, never 33.0.
    assert segs[1].audio.duration_seconds != 33.0
    assert 0.0 < segs[1].audio.duration_seconds < 10.0


async def test_tts_provider_error_substitutes_backstop(caplog) -> None:
    buf = LookAheadBuffer(maxsize=10)
    with caplog.at_level(logging.WARNING):
        await Producer(
            items=[_id_item()],
            tts=FailingTTS(),
            decoder=FakeDecoder(),
            buffer=buf,
            backstop=_BACKSTOP,
        ).run()
    segs = _drain(buf)
    assert len(segs) == 1  # not dropped
    assert segs[0].item.kind == "station_id"
    assert segs[0].audio is _BACKSTOP  # R11/R15: backstop substituted, never dead air
    assert any(r.levelno == logging.WARNING for r in caplog.records)


async def test_decoder_provider_error_substitutes_backstop(caplog) -> None:
    buf = LookAheadBuffer(maxsize=10)
    with caplog.at_level(logging.WARNING):
        await Producer(
            items=[_track_item(10.0)],
            tts=StubTTS(),
            decoder=FailingDecoder(),
            buffer=buf,
            backstop=_BACKSTOP,
        ).run()
    segs = _drain(buf)
    assert len(segs) == 1
    assert segs[0].audio is _BACKSTOP
    assert any(r.levelno == logging.WARNING for r in caplog.records)


async def test_terminal_provider_error_also_substitutes_backstop() -> None:
    # The producer must catch the BASE ProviderError, not just the retryable leaf — a
    # ProviderFatal render failure is backstopped too (failover is Phase 3; Phase 1 never
    # dead-airs regardless of the leaf).
    buf = LookAheadBuffer(maxsize=10)
    await Producer(
        items=[_id_item()],
        tts=FailingTTS(error=ProviderFatal("bad request")),
        decoder=FakeDecoder(),
        buffer=buf,
        backstop=_BACKSTOP,
    ).run()
    segs = _drain(buf)
    assert len(segs) == 1
    assert segs[0].audio is _BACKSTOP


async def test_empty_item_list_produces_nothing_and_returns() -> None:
    buf = LookAheadBuffer(maxsize=10)
    await Producer(
        items=[], tts=StubTTS(), decoder=FakeDecoder(), buffer=buf, backstop=_BACKSTOP
    ).run()
    assert buf.depth == 0  # nothing produced, no hang


def test_announcement_text_is_nonempty_and_block_aware() -> None:
    sid = StationIdItem(planned_start=_T0, duration=5.0, block_name="Morning")
    rem = BlockReminderItem(planned_start=_T0, duration=8.0, block_name="Morning")
    trans = BlockTransitionItem(
        planned_start=_T0,
        duration=10.0,
        block_name="Morning",
        next_block_name="Afternoon",
        next_block_starts_at=_T0 + timedelta(hours=6),
    )
    assert "Morning" in announcement_text(sid)  # station id names the current block
    assert "Morning" in announcement_text(rem)  # reminder names the current block
    assert "Afternoon" in announcement_text(trans)  # transition names the NEXT block


def test_announcement_text_rejects_a_track_item() -> None:
    # A track is rendered by the decoder, never spoken — asking for its patter is a bug.
    import pytest

    with pytest.raises(ValueError):
        announcement_text(_track_item(10.0))
