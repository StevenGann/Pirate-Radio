"""grid + catalog -> DailySchedule (§8.4 fill rule), seedable (R19), clock-injected (R18).

Determinism contract (R19): ``(catalog, grid, seed, clock) -> byte-identical persisted
JSON``. Achieved by (a) the catalog's stable ``(group, path)`` sort (Phase-0 scanner),
(b) a single injected ``random.Random`` seeded once — the ONLY entropy source, and (c)
no ``datetime.now()`` anywhere (the injected clock owns "today" and the zone).

§8.4 walk: for each grid slot in time order, emit a ``block_transition`` at the slot
boundary, then fill the slot with weighted, repeat-avoiding ``track`` picks, dropping a
``station_id`` near each top-of-hour and a ``block_reminder`` periodically. Every element
advances the cursor by its own ``duration`` **plus** ``transition_silence_seconds`` (the
hard-cut gap, §10) — the silence is part of timing AND of the fill calculation. The fill
loop stops when the gap to the boundary is smaller than the shortest item in the pool
(§8.5 soft boundary): the final placed item may run slightly past the boundary.
"""

from __future__ import annotations

import random
import zlib
from datetime import date, datetime, time, timedelta

from pirate_radio.catalog.models import Track
from pirate_radio.catalog.scanner import Catalog
from pirate_radio.clock import Clock
from pirate_radio.config import StationConfig
from pirate_radio.errors import ScheduleError
from pirate_radio.schedule.grid import Grid, Slot
from pirate_radio.schedule.models import (
    BlockReminderItem,
    BlockTransitionItem,
    DailySchedule,
    ScheduleItem,
    StationIdItem,
    TrackItem,
)

# §8.4 timing/cadence constants (H1: named, not magic numbers).
_BLOCK_TRANSITION_SECONDS = 10.0  # DJ patter bridging two blocks (§8.4.1)
_STATION_ID_SECONDS = 5.0  # top-of-hour station identification (§8.4.4)
_BLOCK_REMINDER_SECONDS = 8.0  # "you're listening to <block>" (§8.4.3)
_BLOCK_REMINDER_EVERY = timedelta(minutes=30)  # §8.4 "periodically in long slots"
_RECENT_DOWNWEIGHT = 0.05  # weight for a track played within the repeat window (H2: soft)

_MIDNIGHT = time(0, 0)


def derive_seed(day: date, station: str) -> int:
    """Recommended R19 seed: date- + station-derived, stable-but-varying day to day.

    Deterministic across restarts for the SAME day (a mid-day crash regenerates the
    *same* schedule, so resume is meaningful, §6), yet different from day to day and
    station to station.
    """
    return zlib.crc32(f"{day.isoformat()}:{station}".encode())


def generate_schedule(
    *,
    grid: Grid,
    catalog: Catalog,
    station: StationConfig,
    clock: Clock,
    seed: int,  # recorded on DailySchedule.seed (R19 reproducibility record)
) -> DailySchedule:
    """Realize ``grid`` + ``catalog`` into a ``DailySchedule`` for the clock's day (§8.4)."""
    rng = random.Random(seed)  # the ONLY entropy source (R19)
    day = clock.now().date()
    tz = clock.now().tzinfo  # tz-aware clock (D6); same zone tz() reports
    groups = catalog.groups()  # group -> tuple[Track] (already (group, path) sorted)
    silence = station.transition_silence_seconds
    window = timedelta(minutes=station.repeat_window_minutes)

    items: list[ScheduleItem] = []
    recent: list[tuple[datetime, str]] = []  # (planned_start, path) for the repeat window
    cursor = _bind(day, _MIDNIGHT, tz)  # midnight, tz-aware; carries across slots

    prior: Slot | None = None
    for slot in grid.slots:
        pool = _pool_for(groups, slot)
        shortest = min(t.duration for t in pool)
        boundary = _slot_boundary(day, slot, tz)

        transition = _transition(slot, prior, cursor, day, tz)
        items.append(transition)
        cursor += timedelta(seconds=transition.duration + silence)

        last_id_hour: int | None = None
        last_reminder = cursor
        while (boundary - cursor).total_seconds() >= shortest:
            # §8.4.4 station_id once per hour: fire at the FIRST item of each new clock-hour. NOT
            # gated on a top-of-hour minute window — the soft-boundary cursor drifts past HH:02 over
            # the day, so a window gate silently dropped the id for most hours (code-cycle DA HIGH).
            if cursor.hour != last_id_hour:
                items.append(
                    StationIdItem(
                        planned_start=cursor, duration=_STATION_ID_SECONDS, block_name=slot.name
                    )
                )
                last_id_hour = cursor.hour
                cursor += timedelta(seconds=_STATION_ID_SECONDS + silence)
                continue
            # §8.4.3 block_reminder periodically through long slots.
            if cursor - last_reminder >= _BLOCK_REMINDER_EVERY:
                items.append(
                    BlockReminderItem(
                        planned_start=cursor, duration=_BLOCK_REMINDER_SECONDS, block_name=slot.name
                    )
                )
                cursor += timedelta(seconds=_BLOCK_REMINDER_SECONDS + silence)
                last_reminder = cursor
                continue
            # §8.4.2 weighted pick avoiding recent repeats (soft down-weight, H2).
            track = _pick(pool, recent, cursor, window, rng)
            items.append(
                TrackItem(
                    planned_start=cursor, duration=track.duration, block_name=slot.name, track=track
                )
            )
            recent.append((cursor, str(track.path)))
            cursor += timedelta(seconds=track.duration + silence)

        prior = slot

    return DailySchedule(date=day, station=station.name, seed=seed, items=tuple(items))


def _pool_for(groups: dict[str, tuple[Track, ...]], slot: Slot) -> tuple[Track, ...]:
    """The track pool for ``slot``'s group, or a typed error (H3) — never a bare KeyError."""
    pool = groups.get(slot.group)
    if not pool:
        raise ScheduleError(
            f"grid slot '{slot.name}' references group '{slot.group}' which has no tracks "
            f"in the catalog (groups: {sorted(groups)})"
        )
    return pool


def _bind(day: date, t: time, tz: object) -> datetime:
    """Wall-clock ``day`` + ``t`` in the clock's zone (D6: zoneinfo owns DST)."""
    return datetime.combine(day, t, tzinfo=tz)  # type: ignore[arg-type]


def _slot_boundary(day: date, slot: Slot, tz: object) -> datetime:
    """The slot's end as a tz-aware datetime; a ``00:00`` end means NEXT-day midnight (P3).

    Without rolling ``time(0,0)`` to the following midnight the final all-day/PM slot
    would compute a negative span and emit zero tracks.
    """
    if slot.end == _MIDNIGHT:
        return _bind(day + timedelta(days=1), _MIDNIGHT, tz)
    return _bind(day, slot.end, tz)


def _transition(
    slot: Slot, prior: Slot | None, cursor: datetime, day: date, tz: object
) -> BlockTransitionItem:
    """A ``block_transition`` announcing ``slot`` (§8.4.1).

    ``next_block_*`` describe the block being entered (anchored at the slot's scheduled
    start, not the drifting cursor). ``block_name`` names the block the announcement airs
    *within* — the prior block being closed, or, for the day's opening transition (no
    prior), the block it opens.
    """
    return BlockTransitionItem(
        planned_start=cursor,
        duration=_BLOCK_TRANSITION_SECONDS,
        block_name=(prior.name if prior is not None else slot.name),
        next_block_name=slot.name,
        next_block_starts_at=_bind(day, slot.start, tz),
    )


def _pick(
    pool: tuple[Track, ...],
    recent: list[tuple[datetime, str]],
    cursor: datetime,
    window: timedelta,
    rng: random.Random,
) -> Track:
    """Weighted random track from ``pool``, soft-down-weighting recent plays (H2).

    Determinism (R19): iterate ``pool`` in its already-sorted order to build the weights,
    and draw with the INJECTED ``rng``. ``recent`` is used only for membership, never
    iterated, so there is no set-ordering / hash-seed dependence. The down-weight is
    soft — a recently played track CAN still be chosen — and if the window covers the
    entire pool the draw falls back to uniform so generation never stalls.
    """
    recent_paths = {path for (start, path) in recent if cursor - start < window}
    weights = [_RECENT_DOWNWEIGHT if str(t.path) in recent_paths else 1.0 for t in pool]
    if all(w == _RECENT_DOWNWEIGHT for w in weights):  # whole pool is "recent" -> uniform
        weights = [1.0] * len(pool)
    return rng.choices(pool, weights=weights, k=1)[0]
