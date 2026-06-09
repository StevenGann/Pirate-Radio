"""The midnight task — sleep-to-midnight + per-station isolated day-roll (Phase-4 §E).

``next_midnight`` is PURE and DST-correct: it returns the next local midnight as a tz-aware
``datetime``, so the seconds-to-sleep is 23 h on a spring-forward day and 25 h on a fall-back day
(``zoneinfo`` owns the offset — a naive ``+24 h`` would drift the roll an hour twice a year, H24).

``MidnightTask.run`` loops: sleep to the next midnight (the injected ``Sleeper``), then **per
station, isolated**: ``prepare_next_day`` (generate + persist the new day's schedule) **then**
``signal_day_roll`` (set the day-roll Event) — the **file-written-THEN-event-set** ordering contract
(Q2), so the station re-slices onto a schedule already on disk (no stall at the splice). A regen
failure in ONE station is logged CRITICAL and **never escapes** (H-DA-1): siblings still roll,
and the failed station keeps today's schedule (a bad tomorrow-grid must not kill today at 00:00).

The midnight task **never cancels a running ``run_once``** — it only writes a file + flips a signal,
so an item straddling midnight finishes uncut and the station observes the roll afterwards (§8.6).

Audio-buffer prewarm (rendering the opening cluster during the outgoing day's final item) is NOT
done here: it would span the day boundary inside the FROZEN ``run_once`` (Q1 forbids churning it).
The achievable **schedule prewarm** (file ready before the splice) IS delivered; the boundary
residual is the same bounded one-cluster R11 backstop as a cold start (audible-as-bumper, not
silence) — flagged for the P4-9 deep-dive to ratify against the Rev-2 prewarm amendment.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import datetime, time, timedelta, tzinfo
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from pirate_radio.clock import Clock
from pirate_radio.pipeline.timing import Sleeper

logger = logging.getLogger(__name__)

_UTC = ZoneInfo("UTC")


def next_midnight(now: datetime, tz: tzinfo) -> datetime:
    """The next local midnight strictly after ``now`` (tz-aware; DST-correct via ``zoneinfo``)."""
    local = now.astimezone(tz)
    return datetime.combine(local.date() + timedelta(days=1), time(0, 0), tzinfo=tz)


def seconds_until_next_midnight(now: datetime, tz: tzinfo) -> float:
    """The REAL elapsed seconds until the next local midnight (23 h spring-forward, 25 h fall-back).

    Subtracting two same-zone ``zoneinfo`` datetimes directly yields the *naive* wall-clock delta
    (a Python gotcha: it does NOT apply the offset change), so both sides are converted to UTC first
    — that is what makes the day-roll fire at true local midnight across a DST boundary (H24)."""
    target = next_midnight(now, tz)
    return (target.astimezone(_UTC) - now.astimezone(_UTC)).total_seconds()


@runtime_checkable
class DayRollable(Protocol):
    """What the midnight task needs of a station: a name, the per-station ``regen_lock`` (shared
    with an API ``--regenerate`` so they never race), and the two-step roll (file, then event)."""

    name: str

    @property
    def regen_lock(self) -> asyncio.Lock: ...

    def prepare_next_day(self) -> None: ...

    def signal_day_roll(self) -> None: ...


class MidnightTask:
    """Sleeps to each midnight, then rolls every station's schedule (isolated, file-then-event)."""

    def __init__(self, *, stations: Sequence[DayRollable], clock: Clock, sleeper: Sleeper) -> None:
        self._stations = stations
        self._clock = clock
        self._sleeper = sleeper

    async def run(self) -> None:
        while True:
            now = self._clock.now()
            tz = now.tzinfo or self._clock.tz()
            await self._sleeper.sleep(seconds_until_next_midnight(now, tz))  # DST-correct (H24)
            for station in self._stations:
                try:
                    async with station.regen_lock:  # serialize vs an API --regenerate (P6-3)
                        station.prepare_next_day()  # writes the new day's FILE (Q2: file ...)
                    station.signal_day_roll()  # ... THEN sets the day-roll Event
                    logger.info("midnight regen %s done", station.name)
                except Exception as exc:  # noqa: BLE001 - per-station isolation (H-DA-1)
                    # A bad tomorrow-grid / missing content for ONE station must not take down the
                    # others or today's broadcast: log loud, keep today's schedule, never escape.
                    logger.critical(
                        "midnight regen %s FAILED (%s: %s); keeping today's schedule",
                        station.name,
                        type(exc).__name__,
                        exc,
                    )
