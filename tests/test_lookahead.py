"""RED tests for ``pirate_radio.lookahead`` — Phase-4 plan §A / P4-6a (the C1 fix core).

The PURE look-ahead budget math the coordinator computes once at boot: the buffer **depth** that
lets the serial producer pre-render a patter cluster *during the preceding multi-minute track*
(``worst_consecutive_patter + 1``); the **RAM ceiling** as a FAIL-FAST ``ConfigError`` (NOT a silent
clamp — a clamp would regress C1) against a **fixed** byte budget; the deterministic per-station
**stagger** offset; and the **worst-case render** seconds (Σ chain timeouts) with **named
constants**. Every function is PURE and unit-testable with synthetic items — no clock, no IO.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pirate_radio.audio.buffer import DEFAULT_SAMPLE_RATE
from pirate_radio.catalog.models import Track
from pirate_radio.errors import ConfigError
from pirate_radio.lookahead import (
    _LLM_TIMEOUT_DEFAULT,
    _LOOKAHEAD_RAM_BUDGET_BYTES,
    _RESIDENT_SLACK_SLOTS,
    _STAGGER_STEP_SECONDS,
    _TTS_TIMEOUT_DEFAULT,
    lookahead_depth,
    ram_affordable_depth,
    resolve_lookahead_depth,
    stagger_offset,
    track_buffer_bytes,
    worst_case_patter_render,
    worst_consecutive_patter,
)
from pirate_radio.schedule.models import (
    BlockReminderItem,
    BlockTransitionItem,
    ScheduleItem,
    StationIdItem,
    TrackItem,
)

_T0 = datetime(2026, 6, 10, 0, 0, tzinfo=ZoneInfo("UTC"))


def _track() -> TrackItem:
    t = Track(path=Path("/lib/x/s.flac"), group="x", duration=200.0, title="S")
    return TrackItem(planned_start=_T0, duration=200.0, block_name="B", track=t)


def _transition() -> BlockTransitionItem:
    return BlockTransitionItem(
        planned_start=_T0,
        duration=10.0,
        block_name="B",
        next_block_name="C",
        next_block_starts_at=_T0,
    )


def _id() -> StationIdItem:
    return StationIdItem(planned_start=_T0, duration=5.0, block_name="B")


def _reminder() -> BlockReminderItem:
    return BlockReminderItem(planned_start=_T0, duration=8.0, block_name="B")


# ---- worst_consecutive_patter (PURE) ------------------------------------------------------
def test_worst_consecutive_patter_all_tracks_is_zero() -> None:
    assert worst_consecutive_patter([_track(), _track(), _track()]) == 0


def test_worst_consecutive_patter_empty_is_zero() -> None:
    assert worst_consecutive_patter([]) == 0


def test_worst_consecutive_patter_single_patter_between_tracks_is_one() -> None:
    assert worst_consecutive_patter([_track(), _id(), _track(), _reminder(), _track()]) == 1


def test_worst_consecutive_patter_counts_a_boundary_cluster() -> None:
    # the generator's worst case: block_transition + station_id back-to-back at a top-of-hour
    items: list[ScheduleItem] = [_track(), _transition(), _id(), _track()]
    assert worst_consecutive_patter(items) == 2


def test_worst_consecutive_patter_counts_a_leading_cluster() -> None:
    # the day OPENS with a patter-only cluster and no masking track (Rev-2 prewarm motivation)
    assert worst_consecutive_patter([_transition(), _id(), _track()]) == 2


def test_worst_consecutive_patter_counts_a_trailing_cluster() -> None:
    assert worst_consecutive_patter([_track(), _track(), _transition(), _id(), _reminder()]) == 3


# ---- lookahead_depth = cluster + 1 (the masking-track slot) --------------------------------
def test_lookahead_depth_is_worst_cluster_plus_one() -> None:
    assert lookahead_depth([_track(), _transition(), _id(), _track()]) == 3  # cluster 2 -> depth 3


def test_lookahead_depth_all_tracks_is_one() -> None:
    assert lookahead_depth([_track(), _track()]) == 1  # no cluster -> one slot of look-ahead


# ---- track_buffer_bytes (whole-track float32 footprint) ------------------------------------
def test_track_buffer_bytes_is_rate_times_channels_times_four() -> None:
    # 60s mono @ DEFAULT_SAMPLE_RATE float32 = 60 * sr * 1 * 4 bytes (~11.5 MB @ 48k)
    assert track_buffer_bytes(60.0) == int(60.0 * DEFAULT_SAMPLE_RATE * 1 * 4)


def test_track_buffer_bytes_scales_with_channels() -> None:
    mono = track_buffer_bytes(10.0, channels=1)
    stereo = track_buffer_bytes(10.0, channels=2)
    assert stereo == 2 * mono


def test_track_buffer_bytes_truncates_a_fractional_byte() -> None:
    # DA H4: a non-integer-byte input (odd rate × fractional seconds) truncates to int, never floats
    out = track_buffer_bytes(0.1, sample_rate=44101, channels=1)  # 0.1*44101*4 = 17640.4 -> 17640
    assert out == 17640 and isinstance(out, int)


# ---- ram_affordable_depth (floor division, per-station scaling) ----------------------------
def test_ram_affordable_depth_is_floor_budget_over_total_track_bytes() -> None:
    per = track_buffer_bytes(200.0)
    budget = 10 * per  # exactly 10 track buffers fit total
    assert (
        ram_affordable_depth(worst_track_seconds=200.0, n_stations=2, ram_budget_bytes=budget) == 5
    )


def test_ram_affordable_depth_floors_a_partial_slot() -> None:
    per = track_buffer_bytes(200.0)
    budget = 5 * per + per // 2  # 5.5 buffers -> floors to 5
    assert (
        ram_affordable_depth(worst_track_seconds=200.0, n_stations=1, ram_budget_bytes=budget) == 5
    )


def test_ram_affordable_depth_scales_with_channels() -> None:
    # DA H4: stereo buffers are 2x, so the same budget affords half the depth
    per_mono = track_buffer_bytes(200.0, channels=1)
    budget = 8 * per_mono
    mono = ram_affordable_depth(worst_track_seconds=200.0, n_stations=1, ram_budget_bytes=budget)
    stereo = ram_affordable_depth(
        worst_track_seconds=200.0, n_stations=1, ram_budget_bytes=budget, channels=2
    )
    assert mono == 8 and stereo == 4


def test_ram_affordable_depth_rejects_nonpositive() -> None:
    for kw in (
        {"worst_track_seconds": 0.0, "n_stations": 1},
        {"worst_track_seconds": -5.0, "n_stations": 1},  # QA #3: negative seconds
        {"worst_track_seconds": 200.0, "n_stations": 0},
        {"worst_track_seconds": 200.0, "n_stations": -2},  # QA #3: negative stations
        {"worst_track_seconds": 200.0, "n_stations": 1, "ram_budget_bytes": 0},  # QA #3: 0 budget
        {"worst_track_seconds": 200.0, "n_stations": 1, "ram_budget_bytes": -1},  # negative budget
    ):
        with pytest.raises(ConfigError):
            ram_affordable_depth(**kw)  # type: ignore[arg-type]


# ---- resolve_lookahead_depth: FAIL-FAST, not a silent clamp (Rev-2 amendment) --------------
def test_resolve_returns_needed_when_ram_affords_it() -> None:
    per = track_buffer_bytes(200.0)
    budget = 100 * per  # plenty
    assert (
        resolve_lookahead_depth(
            needed_depth=3, worst_track_seconds=200.0, n_stations=4, ram_budget_bytes=budget
        )
        == 3
    )


def test_resolve_returns_needed_at_the_exact_boundary() -> None:
    # the budget must cover the REAL resident peak: needed + slack per station. At exactly that, OK.
    per = track_buffer_bytes(200.0)
    n, needed = 4, 3
    budget = n * (needed + _RESIDENT_SLACK_SLOTS) * per  # affords exactly the resident peak
    assert (
        resolve_lookahead_depth(
            needed_depth=needed, worst_track_seconds=200.0, n_stations=n, ram_budget_bytes=budget
        )
        == needed
    )


def test_resolve_accounts_for_the_resident_slack_slots() -> None:
    # deep-dive RPi: a budget that affords exactly `needed` (queue only) but NOT needed+slack must
    # FAIL-FAST — the real peak includes the in-flight player + producer-blocked segments.
    per = track_buffer_bytes(200.0)
    n, needed = 4, 3
    budget = n * needed * per  # affords the queue but not the +slack resident buffers
    with pytest.raises(ConfigError):
        resolve_lookahead_depth(
            needed_depth=needed, worst_track_seconds=200.0, n_stations=n, ram_budget_bytes=budget
        )


def test_resolve_fails_fast_one_below_the_boundary() -> None:
    # one byte below the resident-peak boundary -> FAIL-FAST (NOT clamp)
    per = track_buffer_bytes(200.0)
    n, needed = 4, 3
    budget = n * (needed + _RESIDENT_SLACK_SLOTS) * per - 1  # one byte short of the resident peak
    with pytest.raises(ConfigError) as exc:
        resolve_lookahead_depth(
            needed_depth=needed, worst_track_seconds=200.0, n_stations=n, ram_budget_bytes=budget
        )
    msg = str(exc.value).lower()
    assert "ram" in msg or "budget" in msg  # names the constraint
    assert "station" in msg and "track" in msg  # names the fix levers (fewer/shorter)


def test_resolve_uses_the_fixed_default_budget() -> None:
    # the default budget is the named fixed constant (reproducible across boots), not psutil
    # 4 stations x depth 3 x 200s tracks fits comfortably in ~1.6 GB
    assert resolve_lookahead_depth(needed_depth=3, worst_track_seconds=200.0, n_stations=4) == 3


def test_resolve_default_budget_fails_fast_when_fixed_budget_exhausted() -> None:
    # DA Hole-1 (THE pin that distinguishes a FIXED 1.6 GB budget from a psutil free-RAM fraction):
    # 8 stations x depth 4 x 600s tracks = ~3.7 GB, which the FIXED 1.6 GB budget CANNOT afford ->
    # the bare (no ram_budget_bytes) call MUST raise. A psutil-of-a-big-CI-box impl would NOT raise
    # here (and would thus fail this test), so this forces the fixed-constant, reproducible-at-3am
    # behaviour the Rev-2 amendment requires — not merely an injected budget.
    with pytest.raises(ConfigError):
        resolve_lookahead_depth(needed_depth=4, worst_track_seconds=600.0, n_stations=8)


def test_resolve_all_tracks_depth_one_is_affordable() -> None:
    # QA #5: a no-cluster system still needs depth 1 (one look-ahead slot); resolve passes through
    assert resolve_lookahead_depth(needed_depth=1, worst_track_seconds=200.0, n_stations=4) == 1


# ---- stagger_offset (deterministic per index, R19-style — no RNG) --------------------------
def test_stagger_offset_is_index_times_step() -> None:
    assert stagger_offset(0) == 0.0
    assert stagger_offset(3) == 3 * _STAGGER_STEP_SECONDS
    assert isinstance(stagger_offset(0), float)  # QA #4: always a float (Sleeper delay seconds)


def test_stagger_offset_rejects_negative_index() -> None:
    with pytest.raises(ConfigError):
        stagger_offset(-1)


# ---- worst_case_render (Q5, named constants) ----------------------------------------------
def test_worst_case_patter_render_sums_all_chain_timeouts() -> None:
    # Σ LLM timeouts + Σ TTS timeouts (every backend can hang its full timeout before failover)
    assert worst_case_patter_render([20.0, 20.0], [30.0]) == 70.0


def test_worst_case_patter_render_sums_the_two_chains_independently() -> None:
    # Senior #1: prove BOTH lists summed (not llm + max(tts), nor one ignored) — asymmetric
    assert worst_case_patter_render([20.0], [30.0, 30.0]) == 80.0
    assert worst_case_patter_render([20.0, 20.0], [30.0]) == 70.0


def test_worst_case_patter_render_empty_chains_is_zero() -> None:
    assert worst_case_patter_render([], []) == 0.0


def test_named_constants_are_the_documented_fixed_values() -> None:
    # Old-Man/RPi condition: a FIXED budget (not a psutil fraction), reproducible at 3am.
    assert _LOOKAHEAD_RAM_BUDGET_BYTES == 1_600_000_000  # ~1.6 GB ≈ 40% of a 4 GB Pi
    assert _STAGGER_STEP_SECONDS == 2.0
    assert _LLM_TIMEOUT_DEFAULT == 20.0
    assert _TTS_TIMEOUT_DEFAULT == 30.0
