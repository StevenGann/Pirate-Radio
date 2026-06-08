"""RED tests for ``pirate_radio.schedule.generator`` — Phase 1 plan §4.5 / design §8.4.

Tests first (strict spec-driven TDD). Authored from the §8.4 fill rule and the
plan's must-fix/hardening items, using a **synthetic Catalog** (Tracks built directly
with long durations — no real files) so a 24h schedule is dozens of items, fast and
deterministic.

Headline (R19): ``(catalog, grid, seed, clock) -> byte-identical persisted JSON``.

Pinned behaviors:
  - R19 determinism: two runs identical; persist->load->regenerate identical; seed
    actually drives variation (anti-no-op).
  - P3: ``_slot_boundary`` rolls a ``time(0,0)`` end to NEXT-day midnight, so the final
    block fills (else it computes a negative span and emits zero tracks).
  - §8.4.1 a block_transition at each slot boundary (open/close semantics pinned).
  - §8.4.4 station_id near each top-of-hour (H1 5.0s; de-duped per hour).
  - §8.4.3 block_reminder periodically in long slots (H1 8.0s; >= 30 min apart).
  - §8.4 timing: every element advances the cursor by ``duration + silence``.
  - §8.5 soft boundary: no item *starts* past its slot boundary (stop rule).
  - H2 repeat_window is a soft down-weight that genuinely affects output.
  - H3 a grid group absent from the catalog -> typed PirateRadioError, not KeyError.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pirate_radio.catalog.models import Track
from pirate_radio.catalog.scanner import Catalog
from pirate_radio.clock import FixedClock
from pirate_radio.config import StationConfig
from pirate_radio.errors import PirateRadioError
from pirate_radio.schedule.generator import (
    _BLOCK_REMINDER_SECONDS,
    _BLOCK_TRANSITION_SECONDS,
    _STATION_ID_SECONDS,
    derive_seed,
    generate_schedule,
)
from pirate_radio.schedule.grid import Grid, Slot
from pirate_radio.schedule.models import (
    BlockReminderItem,
    BlockTransitionItem,
    DailySchedule,
    StationIdItem,
    TrackItem,
)

_TZ = ZoneInfo("America/New_York")
_DAY = date(2026, 6, 10)  # a Wednesday, well clear of any DST transition


# --- builders (synthetic, no disk) -------------------------------------------------


def _clock(day: date = _DAY, *, hour: int = 9) -> FixedClock:
    # Generator reads only clock.now().date() + clock.tz(); time-of-day is irrelevant.
    return FixedClock(datetime(day.year, day.month, day.day, hour, 0, tzinfo=_TZ))


def _track(group: str, name: str, dur: float) -> Track:
    return Track(path=Path(f"/lib/{group}/{name}.flac"), group=group, duration=dur)


def _catalog(*tracks: Track) -> Catalog:
    # Mirror the scanner's (group, path) stable sort so the determinism contract holds.
    ordered = tuple(sorted(tracks, key=lambda t: (t.group, str(t.path))))
    return Catalog(content_dir=Path("/lib"), tracks=ordered)


def _station(**over: object) -> StationConfig:
    base: dict[str, object] = {
        "name": "pirate-one",
        "schedule_dir": Path("/s"),
        "content_dir": Path("/c"),
        "audio_device": "hw:0",
        "dj_personality": "snarky",  # exactly one of dj_personality/_file (validator)
        "tts": ({"backend": "piper", "voice": "en"},),  # required (min_length=1); unused here
    }
    base.update(over)
    return StationConfig(**base)  # type: ignore[arg-type]


def _grid(*slots: Slot) -> Grid:
    return Grid(name="g", slots=tuple(slots))


def _bind(day: date, t: time) -> datetime:
    return datetime(day.year, day.month, day.day, t.hour, t.minute, tzinfo=_TZ)


# A roomy two-group catalog: 10 distinct ~10-minute tracks per group.
def _big_catalog() -> Catalog:
    tracks = []
    for group in ("classical", "oldies"):
        for i in range(10):
            tracks.append(_track(group, f"t{i:02d}", 600.0 + i))  # distinct durations
    return _catalog(*tracks)


_ALLDAY_CLASSICAL = _grid(Slot(start=time(0, 0), end=time(0, 0), group="classical", name="All Day"))


# --- R19 determinism (the headline) ------------------------------------------------


def test_same_inputs_give_byte_identical_json() -> None:
    cat, st, clk = _big_catalog(), _station(), _clock()
    a = generate_schedule(grid=_ALLDAY_CLASSICAL, catalog=cat, station=st, clock=clk, seed=7)
    b = generate_schedule(grid=_ALLDAY_CLASSICAL, catalog=cat, station=st, clock=clk, seed=7)
    assert a.model_dump_json() == b.model_dump_json()


def test_persist_load_regenerate_is_identical(tmp_path: Path) -> None:
    # R19/P5: persisted bytes round-trip back to the same object, and regenerating
    # from the same inputs reproduces those exact bytes.
    cat, st, clk = _big_catalog(), _station(), _clock()
    a = generate_schedule(grid=_ALLDAY_CLASSICAL, catalog=cat, station=st, clock=clk, seed=7)

    f = tmp_path / "2026-06-10.json"
    f.write_text(a.model_dump_json(), encoding="utf-8")
    reloaded = DailySchedule.model_validate_json(f.read_text(encoding="utf-8"))
    assert reloaded == a

    b = generate_schedule(grid=_ALLDAY_CLASSICAL, catalog=cat, station=st, clock=clk, seed=7)
    assert b.model_dump_json() == f.read_text(encoding="utf-8")


def test_seed_actually_drives_variation() -> None:
    # Anti-no-op: a different seed must change the realized schedule (the rng is not
    # ignored). Over a full day of picks, two seeds diverge.
    cat, st, clk = _big_catalog(), _station(), _clock()
    a = generate_schedule(grid=_ALLDAY_CLASSICAL, catalog=cat, station=st, clock=clk, seed=1)
    b = generate_schedule(grid=_ALLDAY_CLASSICAL, catalog=cat, station=st, clock=clk, seed=2)
    assert a.model_dump_json() != b.model_dump_json()


def test_metadata_is_recorded() -> None:
    cat, st, clk = _big_catalog(), _station(), _clock()
    sched = generate_schedule(grid=_ALLDAY_CLASSICAL, catalog=cat, station=st, clock=clk, seed=42)
    assert sched.seed == 42
    assert sched.date == _DAY
    assert sched.station == "pirate-one"
    assert len(sched.items) >= 1


def test_derive_seed_is_stable_and_varies() -> None:
    assert derive_seed(_DAY, "pirate-one") == derive_seed(_DAY, "pirate-one")
    assert derive_seed(_DAY, "pirate-one") != derive_seed(_DAY, "pirate-two")
    assert derive_seed(_DAY, "pirate-one") != derive_seed(date(2026, 6, 11), "pirate-one")


# --- P3 final-block midnight roll --------------------------------------------------


def test_final_midnight_slot_actually_fills() -> None:
    # P3: a 12:00 -> 24:00 (00:00) final slot must fill. Without rolling the boundary
    # to NEXT-day midnight it would compute a negative span and emit zero tracks.
    grid = _grid(
        Slot(start=time(0, 0), end=time(12, 0), group="classical", name="AM"),
        Slot(start=time(12, 0), end=time(0, 0), group="oldies", name="PM"),
    )
    sched = generate_schedule(
        grid=grid, catalog=_big_catalog(), station=_station(), clock=_clock(), seed=3
    )
    pm_tracks = [i for i in sched.items if isinstance(i, TrackItem) and i.block_name == "PM"]
    # Non-emptiness alone proves the roll: without it the boundary would be THIS-day
    # midnight (a negative span) and the PM block would emit zero tracks.
    assert pm_tracks, "the PM (12:00->24:00) block must fill with tracks"
    # The day's last item is in the PM block and the timeline runs to ~NEXT-day midnight
    # (the roll): the final residual gap to 24:00 is under one short item (soft stop).
    last = sched.items[-1]
    assert last.block_name == "PM"
    next_midnight = _bind(date(2026, 6, 11), time(0, 0))
    shortest = min(t.duration for t in _big_catalog().tracks if t.group == "oldies")
    residual = (
        next_midnight - (last.planned_start + timedelta(seconds=last.duration))
    ).total_seconds()
    assert residual < shortest + 2.0  # filled up to (or past) next-day midnight, not THIS noon


# --- §8.4.1 block_transition emission ----------------------------------------------


def test_block_transition_at_each_slot_boundary() -> None:
    grid = _grid(
        Slot(start=time(0, 0), end=time(12, 0), group="classical", name="AM"),
        Slot(start=time(12, 0), end=time(0, 0), group="oldies", name="PM"),
    )
    sched = generate_schedule(
        grid=grid, catalog=_big_catalog(), station=_station(), clock=_clock(), seed=5
    )
    transitions = [i for i in sched.items if isinstance(i, BlockTransitionItem)]
    assert len(transitions) == 2  # one per slot
    # H1: the block_transition content duration is a named constant (pins the otherwise
    # free value so the station_id placement math below is well-defined).
    assert all(i.duration == _BLOCK_TRANSITION_SECONDS for i in transitions)
    # The drift the station_id test tolerates: with a 3600s track each hour adds one
    # station_id + one reminder of cumulative offset, on top of the opening transition.
    # For station_ids to keep landing inside the 2-min top-of-hour window for the first
    # few hours, that compounded drift must stay under 120s — pin the real relationship,
    # not a loose < 120 bound (which would let a ~105s transition silently break it).
    assert _BLOCK_TRANSITION_SECONDS > 0
    assert _BLOCK_TRANSITION_SECONDS + 2 * (_STATION_ID_SECONDS + _BLOCK_REMINDER_SECONDS) < 120

    # The day opens with a transition into the first block. With no prior block, the
    # opening transition's block_name names the block it opens (slot 0).
    first = sched.items[0]
    assert isinstance(first, BlockTransitionItem)
    assert first.next_block_name == "AM"
    assert first.next_block_starts_at == _bind(_DAY, time(0, 0))
    assert first.block_name == "AM"

    # The second transition announces PM and is anchored at noon; it airs while the
    # prior (AM) block is closing, so block_name names the block being LEFT, not entered
    # (a deliberate open/close convention: _transition must know the prior slot).
    second = transitions[1]
    assert second.next_block_name == "PM"
    assert second.next_block_starts_at == _bind(_DAY, time(12, 0))
    assert second.block_name == "AM"


# --- §8.4.4 station_id ; §8.4.3 block_reminder -------------------------------------


def test_station_id_recurs_near_top_of_hour() -> None:
    # Deterministic construction: silence=0 and a single 3600s track make the cursor
    # re-enter each hour just after HH:00, so a station_id recurs near each top-of-hour.
    cat = _catalog(_track("classical", "hour", 3600.0))
    st = _station(transition_silence_seconds=0.0)
    sched = generate_schedule(
        grid=_ALLDAY_CLASSICAL, catalog=cat, station=st, clock=_clock(), seed=1
    )
    ids = [i for i in sched.items if isinstance(i, StationIdItem)]
    assert len(ids) >= 3  # recurs across hours, not just the day-opening one
    assert all(i.duration == _STATION_ID_SECONDS == 5.0 for i in ids)  # H1 constant
    # Placement rule (NOT a tautology — ids is filtered by TYPE, so a station_id placed
    # mid-hour by a wrong impl would fail here): each airs within the top-of-hour window.
    assert all(i.planned_start.minute < 2 for i in ids)
    hours = [i.planned_start.hour for i in ids]
    assert hours == sorted(hours)  # ascending in time
    assert len(set(hours)) == len(hours)  # de-duped: at most one per hour
    assert hours[0] == 0  # the day opens with one; recurrence proven by len>=3 + unique


def test_block_reminder_in_long_slot() -> None:
    cat = _catalog(_track("classical", "hour", 3600.0))
    st = _station(transition_silence_seconds=0.0)
    sched = generate_schedule(
        grid=_ALLDAY_CLASSICAL, catalog=cat, station=st, clock=_clock(), seed=1
    )
    reminders = [i for i in sched.items if isinstance(i, BlockReminderItem)]
    assert reminders, "a multi-hour slot must emit at least one block_reminder"
    assert all(i.duration == _BLOCK_REMINDER_SECONDS == 8.0 for i in reminders)  # H1
    starts = [i.planned_start for i in reminders]
    for prev, nxt in zip(starts, starts[1:], strict=False):
        assert nxt - prev >= timedelta(minutes=30)  # _BLOCK_REMINDER_EVERY


# --- §8.4 timing & §8.5 soft boundary ----------------------------------------------


def test_cursor_advances_by_duration_plus_silence() -> None:
    # Every element advances the cursor by its content duration PLUS the transition
    # silence (the silence is part of timing AND of the fill calc, §8.4).
    silence = 2.0
    cat = _catalog(_track("classical", "a", 300.0), _track("classical", "b", 420.0))
    st = _station(transition_silence_seconds=silence)
    sched = generate_schedule(
        grid=_ALLDAY_CLASSICAL, catalog=cat, station=st, clock=_clock(), seed=9
    )
    items = sched.items
    for prev, nxt in zip(items, items[1:], strict=False):
        expected = prev.planned_start + timedelta(seconds=prev.duration + silence)
        assert nxt.planned_start == expected


def test_no_item_starts_past_its_slot_boundary() -> None:
    # Soft boundary (§8.5): the stop rule means nothing *starts* after the boundary;
    # only the already-placed final item may run past it.
    grid = _grid(Slot(start=time(0, 0), end=time(6, 0), group="classical", name="Night"))
    sched = generate_schedule(
        grid=grid, catalog=_big_catalog(), station=_station(), clock=_clock(), seed=4
    )
    silence = 2.0  # default
    shortest = min(t.duration for t in _big_catalog().tracks if t.group == "classical")
    boundary = _bind(_DAY, time(6, 0))
    # Stop rule = `remaining >= shortest` (§8.5), NOT a per-pick fit check. So:
    assert all(i.planned_start < boundary for i in sched.items)  # nothing STARTS past it
    assert len(sched.items) > 1  # the 6h block actually filled
    # ...and it fills RIGHT UP to the boundary: the final residual gap is < shortest item
    # (a hard cutoff that stops as soon as a drawn track wouldn't fit can leave a gap as
    # large as the longest track — this guaranteed-tight-fill invariant rules that out).
    last = sched.items[-1]
    residual = (boundary - (last.planned_start + timedelta(seconds=last.duration))).total_seconds()
    assert residual < shortest + silence


def test_all_items_tz_aware_and_monotonic() -> None:
    sched = generate_schedule(
        grid=_ALLDAY_CLASSICAL,
        catalog=_big_catalog(),
        station=_station(),
        clock=_clock(),
        seed=11,
    )
    starts = [i.planned_start for i in sched.items]
    assert all(s.tzinfo is not None for s in starts)
    for prev, nxt in zip(starts, starts[1:], strict=False):
        assert nxt > prev  # strictly increasing (positive durations + silence)


# --- H2 repeat-window soft down-weight ---------------------------------------------


def test_repeat_window_changes_output_but_is_not_a_hard_ban() -> None:
    # H2: the window down-weights recent tracks (soft) — it must genuinely affect the
    # realized schedule (not a no-op), while still allowing a track to recur.
    cat, clk = _big_catalog(), _clock()
    windowed = generate_schedule(
        grid=_ALLDAY_CLASSICAL,
        catalog=cat,
        station=_station(repeat_window_minutes=120),
        clock=clk,
        seed=8,
    )
    no_window = generate_schedule(
        grid=_ALLDAY_CLASSICAL,
        catalog=cat,
        station=_station(repeat_window_minutes=0),
        clock=clk,
        seed=8,
    )
    assert windowed.model_dump_json() != no_window.model_dump_json()


def test_recently_played_track_still_recurs_within_window() -> None:
    # The "soft" half of H2: down-weighting is NOT a hard ban — a 10-track pool cannot
    # fill 24h without repeats, so some track MUST recur within the repeat window. A
    # hard-exclusion impl (weight 0.0 inside the window) could only ever ban-then-stall
    # or refuse repeats; this proves recurrence is allowed.
    st = _station(repeat_window_minutes=120)
    window = timedelta(minutes=120)
    sched = generate_schedule(
        grid=_ALLDAY_CLASSICAL, catalog=_big_catalog(), station=st, clock=_clock(), seed=8
    )
    starts: dict[str, list[datetime]] = {}
    for i in sched.items:
        if isinstance(i, TrackItem):
            starts.setdefault(str(i.track.path), []).append(i.planned_start)
    recurs_in_window = any(
        any(b - a < window for a, b in zip(times, times[1:], strict=False))
        for times in starts.values()
    )
    assert recurs_in_window, "a down-weighted track must still be able to recur (soft, not banned)"


def test_window_covering_whole_pool_still_completes() -> None:
    # When the window down-weights the entire (tiny) pool, generation must fall back to
    # a uniform draw and keep filling — not stall or crash.
    cat = _catalog(_track("classical", "a", 600.0), _track("classical", "b", 600.0))
    st = _station(repeat_window_minutes=1440)  # whole day -> covers both tracks
    sched = generate_schedule(
        grid=_ALLDAY_CLASSICAL, catalog=cat, station=st, clock=_clock(), seed=2
    )
    track_items = [i for i in sched.items if isinstance(i, TrackItem)]
    assert len(track_items) > 1  # it kept filling (did not stall on a saturated window)
    assert {i.track.path for i in track_items}  # at least one track used, none crashed


# --- H3 typed error on a missing group pool ----------------------------------------


def test_missing_group_raises_typed_error_not_keyerror() -> None:
    grid = _grid(Slot(start=time(0, 0), end=time(0, 0), group="nonexistent", name="Bad"))
    with pytest.raises(PirateRadioError):
        generate_schedule(
            grid=grid, catalog=_big_catalog(), station=_station(), clock=_clock(), seed=1
        )
