"""RED tests for ``pirate_radio.pipeline.daily`` — Phase 4 plan §B / P4-4.

The daily-slice driver `run_once`'s docstring names: ``AnchoredSchedule`` + ``find_now`` → the
remaining items "today from now" + the seek offset into the first item + the leading gap silence
(R11). ``slice_from_now`` is PURE; ``play_day`` plays the R11 gap (at the station format), seeks
into the first item by decode+trim (with an offset-past-decoded-frames → skip guard, DA H2), then
delegates the remainder to the frozen ``run_once``. Virtual-time only (FixedClock/VirtualSleeper/
FakeAudioSink/FakeDecoder/StubTTS); the to_thread normalize is patched (P2-6 determinism).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pirate_radio.audio.buffer import DEFAULT_SAMPLE_RATE, AudioBuffer
from pirate_radio.audio.decode import FakeDecoder
from pirate_radio.catalog.models import Track
from pirate_radio.dj.fakes import FakeAudioSink, StubTTS
from pirate_radio.pipeline.daily import play_day, slice_from_now
from pirate_radio.pipeline.timing import VirtualSleeper
from pirate_radio.schedule.models import DailySchedule, StationIdItem, TrackItem
from pirate_radio.schedule.resume import anchor

_TZ = ZoneInfo("America/New_York")
_T0 = datetime(2026, 6, 10, 0, 0, tzinfo=_TZ)


def _track(dur: float, n: int) -> TrackItem:
    return TrackItem(
        planned_start=_T0,
        duration=dur,
        block_name="Morning",
        track=Track(path=Path(f"/lib/x/{n}.flac"), group="x", duration=dur),
    )


def _id() -> StationIdItem:
    return StationIdItem(planned_start=_T0, duration=5.0, block_name="Morning")


def _anchored(items, *, transition_silence: float = 0.0):
    sched = DailySchedule(date=_T0.date(), station="S", seed=1, items=tuple(items))
    return anchor(sched, transition_silence=transition_silence)


# ---- slice_from_now (PURE) ----------------------------------------------------------------
def test_slice_airing_returns_offset_and_items_from_current() -> None:
    a = _anchored([_track(100.0, 1), _track(200.0, 2), _id()])
    items, offset, gap = slice_from_now(a, _T0 + timedelta(seconds=30))  # 30s into item 0
    assert len(items) == 3 and offset == 30.0 and gap == 0.0


def test_slice_midway_drops_already_aired_items() -> None:
    a = _anchored([_track(100.0, 1), _track(200.0, 2), _id()])
    items, offset, gap = slice_from_now(a, _T0 + timedelta(seconds=150))  # 50s into item 1
    assert [i.duration for i in items] == [200.0, 5.0] and offset == 50.0 and gap == 0.0


def test_slice_in_gap_returns_silence_and_next_items() -> None:
    a = _anchored([_track(100.0, 1), _track(200.0, 2)], transition_silence=10.0)
    # item0 ends at 100; gap 100..110; sample now=105 -> 5s gap, then item1 onward
    items, offset, gap = slice_from_now(a, _T0 + timedelta(seconds=105))
    assert [i.duration for i in items] == [200.0] and offset == 0.0 and gap == 5.0


def test_slice_before_first_item_returns_leading_gap() -> None:
    a = _anchored([_track(100.0, 1)])
    items, offset, gap = slice_from_now(a, _T0 - timedelta(seconds=10))  # before the day starts
    assert len(items) == 1 and gap == 10.0 and offset == 0.0


def test_slice_past_end_of_day_is_empty() -> None:
    a = _anchored([_track(100.0, 1)])
    items, offset, gap = slice_from_now(a, _T0 + timedelta(seconds=999))
    assert items == [] and offset == 0.0 and gap == 0.0


# ---- play_day (integration; normalize patched for virtual-time determinism) ----------------
@pytest.fixture
def _deterministic(monkeypatch):
    monkeypatch.setattr("pirate_radio.pipeline.producer.normalize_to", lambda buf, **kw: buf)
    monkeypatch.setattr("pirate_radio.pipeline.daily.normalize_to", lambda buf, **kw: buf)

    async def _inline(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", _inline)


async def _run_play_day(a, now, sink) -> None:
    await play_day(
        anchored=a,
        now=now,
        tts=StubTTS(),
        decoder=FakeDecoder(),
        sink=sink,
        backstop=AudioBuffer.silence(seconds=1.0),
        sleeper=VirtualSleeper(),
        refill_budget_seconds=5.0,
        maxsize=10,
    )


async def test_play_day_plays_leading_gap_then_items(_deterministic) -> None:
    a = _anchored([_track(100.0, 1), _track(200.0, 2)], transition_silence=10.0)
    sink = FakeAudioSink()
    await _run_play_day(a, _T0 + timedelta(seconds=105), sink)  # 5s gap, then item1 (200s)
    assert sink.played[0].duration_seconds == 5.0  # R11 leading gap silence first
    assert sink.played[0].sample_rate == DEFAULT_SAMPLE_RATE and sink.played[0].channels == 1
    assert sink.played[1].duration_seconds == 200.0  # then the next track, in full


async def test_play_day_seeks_into_first_track(_deterministic) -> None:
    a = _anchored([_track(100.0, 1), _id()])
    sink = FakeAudioSink()
    await _run_play_day(a, _T0 + timedelta(seconds=40), sink)  # 40s into the 100s track
    assert abs(sink.played[0].duration_seconds - 60.0) < 0.01  # remaining 60s of the track aired
    assert (
        sink.played[1].duration_seconds < 10.0
    )  # then the short station_id (StubTTS), via run_once


def _mismatched_track(item_dur: float, track_dur: float, n: int) -> TrackItem:
    # a metadata-lying / truncated track: the schedule window is item_dur but the file decodes to
    # track_dur (FakeDecoder yields track.duration).
    return TrackItem(
        planned_start=_T0,
        duration=item_dur,
        block_name="Morning",
        track=Track(path=Path(f"/lib/x/{n}.flac"), group="x", duration=track_dur),
    )


async def test_play_day_offset_past_decoded_frames_skips_first(_deterministic) -> None:
    # DA H2: when the decoded length (10s) < the resume offset (40s), the first item must be SKIPPED
    # (not emit an empty buffer that would backstop). Schedule window 100s, file decodes to 10s.
    a = _anchored([_mismatched_track(100.0, 10.0, 1), _id()])
    sink = FakeAudioSink()
    await _run_play_day(a, _T0 + timedelta(seconds=40), sink)  # offset 40s > decoded 10s -> skip
    assert len(sink.played) == 1  # first item skipped; only the station_id aired
    assert sink.played[0].duration_seconds < 10.0  # the station_id (StubTTS), not a track
    assert all(b.duration_seconds > 0 for b in sink.played)  # never an empty buffer


async def test_play_day_past_end_of_day_airs_nothing(_deterministic) -> None:
    a = _anchored([_track(100.0, 1)])
    sink = FakeAudioSink()
    await _run_play_day(a, _T0 + timedelta(seconds=999), sink)
    assert sink.played == []
