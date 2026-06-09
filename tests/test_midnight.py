"""RED tests for ``pirate_radio.midnight`` — Phase-4 plan §E / P4-7.

``next_midnight`` is PURE + DST-correct (the seconds-to-sleep is 23 h on spring-forward, 25 h on
fall-back — that's the whole point of computing it from tz-aware datetimes). The ``MidnightTask``
loop sleeps to the next midnight (injected ``Sleeper``), then **per station, isolated**: regenerate
persist the new day's schedule and set its day-roll Event — **file written THEN event set** (Q2). A
regen failure in ONE station is logged CRITICAL and never escapes (H-DA-1): the other stations still
roll, and the failed station keeps today's schedule. Zero wall-clock (VirtualSleeper + FixedClock).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from pirate_radio.clock import FixedClock
from pirate_radio.midnight import MidnightTask, next_midnight, seconds_until_next_midnight

_NY = ZoneInfo("America/New_York")


class _GatedSleeper:
    """Records each requested wait; parks forever after the FIRST sleep so the task's ``while`` loop
    runs exactly ONE iteration under test (VirtualSleeper yields instantly and would spin it)."""

    def __init__(self) -> None:
        self.slept: list[float] = []
        self._gate = asyncio.Event()

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        if len(self.slept) > 1:
            await self._gate.wait()  # never set -> park after one full regen pass
        else:
            await asyncio.sleep(0)


# ---- next_midnight (PURE, DST-correct) ----------------------------------------------------
def test_next_midnight_is_the_following_local_midnight() -> None:
    now = datetime(2026, 6, 11, 9, 30, tzinfo=_NY)
    assert next_midnight(now, _NY) == datetime(2026, 6, 12, 0, 0, tzinfo=_NY)


def test_next_midnight_from_just_after_midnight_is_the_next_day() -> None:
    now = datetime(2026, 6, 11, 0, 0, 30, tzinfo=_NY)
    assert next_midnight(now, _NY) == datetime(2026, 6, 12, 0, 0, tzinfo=_NY)


def test_next_midnight_spring_forward_day_is_23_hours() -> None:
    # 2026-03-08: US DST begins (clocks skip 02:00->03:00) — that calendar day is only 23 h long
    now = datetime(2026, 3, 8, 0, 0, tzinfo=_NY)
    assert next_midnight(now, _NY) == datetime(2026, 3, 9, 0, 0, tzinfo=_NY)
    # the SLEEP must be the real elapsed 23 h (naive same-zone subtraction would wrongly give 24 h)
    assert seconds_until_next_midnight(now, _NY) == 23 * 3600


def test_next_midnight_fall_back_day_is_25_hours() -> None:
    # 2026-11-01: US DST ends (clocks repeat 01:00-02:00) — that calendar day is 25 h long
    now = datetime(2026, 11, 1, 0, 0, tzinfo=_NY)
    assert next_midnight(now, _NY) == datetime(2026, 11, 2, 0, 0, tzinfo=_NY)
    assert seconds_until_next_midnight(now, _NY) == 25 * 3600


# ---- MidnightTask loop --------------------------------------------------------------------
class _FakeStation:
    """Records the order of regen calls (file-then-event) — the only API MidnightTask touches."""

    def __init__(self, name: str, *, fail: bool = False) -> None:
        self.name = name
        self._fail = fail
        self.events: list[str] = []
        self.regen_lock = (
            asyncio.Lock()
        )  # midnight acquires it (shared with API --regenerate, P6-3)

    def prepare_next_day(self) -> None:
        if self._fail:
            raise RuntimeError("bad tomorrow-grid")
        self.events.append("prepared")  # the schedule FILE is written here (in the real Station)

    def signal_day_roll(self) -> None:
        self.events.append("signaled")  # the day-roll Event is set here — AFTER the file


async def _inline_offload(fn, *a, **k):  # noqa: ANN001, ANN002, ANN003 - run prepare on the loop
    return fn(*a, **k)  # deterministic in tests; prod uses asyncio.to_thread (R23, off the loop)


async def _run_one_iteration(task: MidnightTask) -> None:
    t = asyncio.create_task(task.run())
    await asyncio.sleep(0.02)  # let the gated sleep + one regen pass run, then it parks
    t.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await t


async def test_sleeps_the_computed_seconds_to_next_midnight() -> None:
    now = datetime(2026, 6, 11, 9, 0, tzinfo=_NY)
    sleeper = _GatedSleeper()
    task = MidnightTask(
        stations=[_FakeStation("A")],
        clock=FixedClock(now),
        sleeper=sleeper,
        offload=_inline_offload,
    )
    await _run_one_iteration(task)
    assert sleeper.slept[0] == seconds_until_next_midnight(now, _NY)  # 15 h = 54000 s


async def test_regenerates_then_signals_each_station_file_before_event() -> None:
    a, b = _FakeStation("A"), _FakeStation("B")
    task = MidnightTask(
        stations=[a, b],
        clock=FixedClock(datetime(2026, 6, 11, 9, 0, tzinfo=_NY)),
        sleeper=_GatedSleeper(),
        offload=_inline_offload,
    )
    await _run_one_iteration(task)
    assert a.events == ["prepared", "signaled"]  # Q2: file written THEN event set
    assert b.events == ["prepared", "signaled"]


async def test_regen_failure_is_isolated_and_non_fatal(caplog) -> None:
    good, bad, good2 = _FakeStation("Good"), _FakeStation("Bad", fail=True), _FakeStation("Good2")
    task = MidnightTask(
        stations=[good, bad, good2],
        clock=FixedClock(datetime(2026, 6, 11, 9, 0, tzinfo=_NY)),
        sleeper=_GatedSleeper(),
        offload=_inline_offload,
    )
    with caplog.at_level(logging.CRITICAL):
        await _run_one_iteration(task)  # MUST NOT raise — the bad station never escapes (H-DA-1)
    assert good.events == ["prepared", "signaled"]  # sibling rolled
    assert good2.events == [
        "prepared",
        "signaled",
    ]  # the LATER sibling also rolled (loop continued)
    assert bad.events == []  # never signaled (raised before the event) -> keeps today's schedule
    assert any("Bad" in r.message and r.levelno == logging.CRITICAL for r in caplog.records)


async def test_midnight_roll_waits_for_an_in_flight_regen_on_the_shared_lock() -> None:
    # P6-6 / QA H2: the regen-lock-vs-midnight race composed against the REAL MidnightTask. An API
    # regen holds the station's regen_lock across its offloaded write; the midnight roll for that
    # station must BLOCK on the same lock and not write/signal until the regen releases it — proving
    # the two writers never interleave on one schedule file. (The other direction — a regen waiting
    # on a midnight-held lock — is pinned in tests/test_coordinator.py.)
    station = _FakeStation("A")
    await station.regen_lock.acquire()  # an in-flight API regen is holding the lock

    task = MidnightTask(
        stations=[station],
        clock=FixedClock(datetime(2026, 6, 11, 9, 0, tzinfo=_NY)),
        sleeper=_GatedSleeper(),
        offload=_inline_offload,
    )
    roll = asyncio.create_task(task.run())
    await asyncio.sleep(0.02)
    assert station.events == []  # BLOCKED: the roll can't prepare/signal while the regen holds it

    station.regen_lock.release()  # the regen finished -> the roll proceeds, serialized
    await asyncio.sleep(0.02)
    assert station.events == ["prepared", "signaled"]  # rolled only after the lock was free
    roll.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await roll
