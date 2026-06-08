"""RED tests for ``pirate_radio.schedule.resume`` — Phase 1 plan §4.6 / design §6.

Tests first (strict spec-driven TDD). ``find_now`` answers "what airs now, at what
offset" (§6); cold start and post-crash resume use the identical path. Phase 1 upgrades
the design's bare ``tuple[ScheduleItem | None, float]`` to a typed ``NowPlaying`` so the
two hardening rules are explicit:

  - R11 — never undefined dead air: a ``now`` that lands in a transition-silence gap
    returns ``item=None`` PLUS ``next_item`` + ``gap_seconds`` (the player plays exactly
    that much silence, then advances), not a bare ``None`` the caller must guess about.
  - R12 — exact-track re-anchor: persisted ``planned_start`` values are estimates (real
    TTS length is unknown until synthesis). ``find_now`` rebuilds the timeline from the
    anchor + each item's duration + the known silence, so a drifted/wrong stored
    ``planned_start`` cannot mislead it.
  - H4 — anchor the timeline ONCE, then binary-search per tick (``AnchoredSchedule``).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pirate_radio.catalog.models import Track
from pirate_radio.clock import FixedClock
from pirate_radio.schedule.models import (
    DailySchedule,
    StationIdItem,
    TrackItem,
)
from pirate_radio.schedule.resume import NowPlaying, anchor, find_now

_TZ = ZoneInfo("America/New_York")
_MIDNIGHT = datetime(2026, 6, 10, 0, 0, tzinfo=_TZ)
_SILENCE = 2.0


def _track_item(start: datetime, dur: float, name: str = "blk") -> TrackItem:
    return TrackItem(
        planned_start=start,
        duration=dur,
        block_name=name,
        track=Track(path=Path(f"/lib/x/{dur}.flac"), group="x", duration=dur),
    )


def _id_item(start: datetime, dur: float = 5.0, name: str = "blk") -> StationIdItem:
    return StationIdItem(planned_start=start, duration=dur, block_name=name)


def _schedule(*items: object) -> DailySchedule:
    return DailySchedule(
        date=_MIDNIGHT.date(),
        station="pirate-one",
        seed=1,
        items=tuple(items),  # type: ignore[arg-type]
    )


def _at(seconds: float) -> FixedClock:
    return FixedClock(_MIDNIGHT + timedelta(seconds=seconds))


# A 3-item timeline with silence=2.0 between items (planned_start set to the *correct*
# anchored values for readability; re-anchor ignores all but the first anyway):
#   A  track 100s   0   .. 100
#   (silence gap        100 .. 102)
#   ID station_id 5s    102 .. 107
#   (silence gap        107 .. 109)
#   B  track 100s   109 .. 209
def _basic() -> DailySchedule:
    a = _track_item(_MIDNIGHT, 100.0)
    sid = _id_item(_MIDNIGHT + timedelta(seconds=102))
    b = _track_item(_MIDNIGHT + timedelta(seconds=109), 100.0)
    return _schedule(a, sid, b)


# --- airing-now path ---------------------------------------------------------------


def test_item_airing_now_returns_item_and_seek_offset() -> None:
    np = find_now(_basic(), _at(50), transition_silence=_SILENCE)
    assert isinstance(np, NowPlaying)
    assert isinstance(np.item, TrackItem)
    assert np.offset_seconds == 50.0  # seek 50s into track A
    assert np.gap_seconds == 0.0
    assert isinstance(np.next_item, StationIdItem)  # the ID is next


def test_offset_is_relative_to_the_reanchored_start() -> None:
    # now = 105s -> inside the station_id (102..107), 3s in.
    np = find_now(_basic(), _at(105), transition_silence=_SILENCE)
    assert isinstance(np.item, StationIdItem)
    assert np.offset_seconds == 3.0
    assert isinstance(np.next_item, TrackItem)  # track B follows


def test_start_instant_is_inclusive() -> None:
    # now exactly at an item's start airs THAT item at offset 0 (start <= now < end).
    np = find_now(_basic(), _at(109), transition_silence=_SILENCE)
    assert isinstance(np.item, TrackItem)
    assert np.offset_seconds == 0.0


def test_last_item_airing_has_no_next() -> None:
    np = find_now(_basic(), _at(150), transition_silence=_SILENCE)  # inside track B
    assert isinstance(np.item, TrackItem)
    assert np.next_item is None  # B is the last item


# --- R11 gap path ------------------------------------------------------------------


def test_silence_gap_returns_none_with_next_and_gap_seconds() -> None:
    # now = 101s -> in the 100..102 transition-silence gap before the station_id.
    np = find_now(_basic(), _at(101), transition_silence=_SILENCE)
    assert np.item is None
    assert np.offset_seconds == 0.0
    assert isinstance(np.next_item, StationIdItem)
    assert np.gap_seconds == 1.0  # one second of silence remains before the ID


def test_before_first_item_is_a_gap_to_it() -> None:
    np = find_now(_basic(), _at(-30), transition_silence=_SILENCE)  # 30s before midnight
    assert np.item is None
    assert isinstance(np.next_item, TrackItem)
    assert np.gap_seconds == 30.0  # R11: the player sleeps exactly this long, then advances


def test_coming_out_of_a_gap_onto_an_item_start_is_inclusive() -> None:
    # now = 102s lands exactly on the station_id's re-anchored start (out of the 100..102
    # gap). start-inclusive means the ID is airing at offset 0, not still in the gap.
    np = find_now(_basic(), _at(102), transition_silence=_SILENCE)
    assert isinstance(np.item, StationIdItem)
    assert np.offset_seconds == 0.0
    assert np.gap_seconds == 0.0


def test_past_end_of_day_returns_all_none() -> None:
    # now after the last item ends -> caller regenerates; never a crash or dead air loop.
    np = find_now(_basic(), _at(10_000), transition_silence=_SILENCE)
    assert np.item is None
    assert np.next_item is None
    assert np.gap_seconds == 0.0
    assert np.offset_seconds == 0.0


def test_item_end_instant_is_exclusive() -> None:
    # now exactly at track A's end (100s) is NOT inside A; it's the gap before the ID.
    np = find_now(_basic(), _at(100), transition_silence=_SILENCE)
    assert np.item is None
    assert isinstance(np.next_item, StationIdItem)
    assert np.gap_seconds == 2.0  # the full silence gap remains


# --- R12 exact-track re-anchor -----------------------------------------------------


def test_reanchor_ignores_drifted_persisted_planned_start() -> None:
    # The stored planned_start of items AFTER the first are deliberately WRONG (as a real
    # TTS estimate would drift). find_now must rebuild the timeline from the anchor +
    # durations + silence, not trust the stored estimates.
    a = _track_item(_MIDNIGHT, 600.0)
    sid = _id_item(_MIDNIGHT + timedelta(seconds=9999), 5.0)  # WRONG stored start
    b = _track_item(_MIDNIGHT + timedelta(seconds=8888), 600.0)  # WRONG stored start
    sched = _schedule(a, sid, b)

    # Re-anchored: A 0..600, gap 600..602, ID 602..607, gap 607..609, B 609..1209.
    # now = 604s. Trusting the stored start (ID at 9999) would call this a gap after A;
    # re-anchoring correctly finds the station_id airing, 2s in.
    np = find_now(sched, _at(604), transition_silence=_SILENCE)
    assert isinstance(np.item, StationIdItem)
    assert np.offset_seconds == 2.0


# --- H4 anchor-once + binary search ------------------------------------------------


def test_anchor_built_once_is_reusable_across_ticks() -> None:
    # H4: anchor the timeline once, then answer many ticks against it (binary search).
    anchored = anchor(_basic(), transition_silence=_SILENCE)
    assert anchored.find_now(_MIDNIGHT + timedelta(seconds=50)).item is not None  # in A
    assert anchored.find_now(_MIDNIGHT + timedelta(seconds=101)).item is None  # in gap
    assert isinstance(anchored.find_now(_MIDNIGHT + timedelta(seconds=105)).item, StationIdItem)


def test_anchored_starts_are_strictly_increasing_datetimes() -> None:
    # Binary search needs a sorted timeline. duration > 0 + silence >= 0 means starts are
    # STRICTLY increasing (a merely-non-decreasing `== sorted()` check would let a buggy
    # anchor duplicate two starts and still pass while misrouting the search).
    anchored = anchor(_basic(), transition_silence=_SILENCE)
    starts = anchored.starts
    assert isinstance(starts[0], datetime)  # datetimes, not float offsets
    assert all(a < b for a, b in zip(starts, starts[1:], strict=False))


def test_find_now_matches_anchor_then_query() -> None:
    # The convenience find_now is exactly anchor(...).find_now(clock.now()).
    sched = _basic()
    via_convenience = find_now(sched, _at(105), transition_silence=_SILENCE)
    via_anchor = anchor(sched, transition_silence=_SILENCE).find_now(_at(105).now())
    assert via_convenience == via_anchor


def test_single_item_schedule_airing_and_past_end() -> None:
    # DailySchedule allows one item; the degenerate timeline must not crash and next_item
    # is always None.
    sched = _schedule(_track_item(_MIDNIGHT, 100.0))
    airing = find_now(sched, _at(40), transition_silence=_SILENCE)
    assert isinstance(airing.item, TrackItem)
    assert airing.next_item is None
    past = find_now(sched, _at(500), transition_silence=_SILENCE)
    assert past.item is None and past.next_item is None and past.gap_seconds == 0.0


def test_patter_first_item_is_a_valid_anchor() -> None:
    # Phase-1 schedules open with a patter item (the block_transition) at an EXACT instant
    # (midnight / slot boundary), so anchoring at items[0].planned_start is correct even
    # though it is patter. (Re-anchoring a patter-first item whose start has truly drifted
    # is a Phase-2 concern, once real TTS makes durations/starts estimates — see 0012.)
    sid = _id_item(_MIDNIGHT, 5.0)  # patter first, exact anchor
    a = _track_item(_MIDNIGHT + timedelta(seconds=7), 100.0)
    sched = _schedule(sid, a)
    np = find_now(sched, _at(3), transition_silence=_SILENCE)  # inside the opening ID
    assert isinstance(np.item, StationIdItem)
    assert np.offset_seconds == 3.0
    assert isinstance(np.next_item, TrackItem)


def test_nowplaying_is_frozen_value() -> None:
    np = find_now(_basic(), _at(50), transition_silence=_SILENCE)
    import dataclasses

    assert dataclasses.is_dataclass(np)
    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        np.offset_seconds = 1.0  # type: ignore[misc]
