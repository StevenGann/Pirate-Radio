"""find_now: "what airs now, at what offset" (§6) — R11 gap path + R12 re-anchor + H4.

Cold start and post-crash resume use the IDENTICAL path (§6): both load today's persisted
schedule and ask ``find_now`` against ``clock.now()``. There is no persisted playhead
(A7: no hot-path writes), so the answer is derived purely from the schedule + the clock.

The design's bare ``tuple[ScheduleItem | None, float]`` is upgraded to a typed
``NowPlaying`` so two rules are explicit rather than implied:

  - **R11 (never undefined dead air).** When ``now`` falls in a transition-silence gap,
    ``find_now`` returns ``item=None`` together with ``next_item`` and ``gap_seconds`` —
    the player plays exactly that much silence and then advances. A bare ``None`` the
    caller has to guess about is forbidden.
  - **R12 (exact-track re-anchor).** Persisted ``planned_start`` values are estimates
    (real TTS length is unknown until synthesis). The timeline is rebuilt from the
    anchor (``items[0].planned_start``, an exact instant for Phase-1 schedules) plus each
    item's duration and the known ``transition_silence``, so a drifted/edited stored
    ``planned_start`` cannot mislead playback.

  - **H4 (anchor once, search many).** ``anchor()`` builds the re-anchored timeline a
    single time; ``AnchoredSchedule.find_now`` answers each tick with a binary search
    over the (strictly increasing) start instants.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import datetime, timedelta

from pirate_radio.clock import Clock
from pirate_radio.schedule.models import DailySchedule, ScheduleItem


@dataclass(frozen=True)
class NowPlaying:
    """The resume answer. Either an item is airing now, or we are in a gap before the next.

    - airing: ``item`` set, ``offset_seconds`` = seek depth, ``gap_seconds`` = 0.
    - gap (R11): ``item`` is ``None``, ``next_item`` + ``gap_seconds`` say how long to
      play silence before it.
    - past end-of-day: everything ``None``/``0`` — the caller regenerates.
    """

    item: ScheduleItem | None
    offset_seconds: float
    next_item: ScheduleItem | None
    gap_seconds: float


@dataclass(frozen=True)
class _Located:
    """Where ``now`` falls on the timeline — the single bisect result both ``find_now`` and
    ``slice_from`` build their (differently-shaped) answers from. ``index`` is the airing item
    (``airing``), the next item (a gap), or ``len(items)`` (past end-of-day → empty slice)."""

    airing: bool
    index: int
    offset: float
    gap: float


@dataclass(frozen=True)
class AnchoredSchedule:
    """A schedule with its R12-re-anchored timeline precomputed once (H4).

    ``starts``/``ends`` are the re-anchored air windows of ``items[i]``; ``starts`` is
    strictly increasing (duration > 0, silence >= 0), which is the binary-search
    precondition ``find_now`` relies on.
    """

    items: tuple[ScheduleItem, ...]
    starts: tuple[datetime, ...]
    ends: tuple[datetime, ...]

    def _locate(self, now: datetime) -> _Located:
        """The ONE bisect: classify ``now`` as airing / in-a-gap / past-end (H4). Both ``find_now``
        and ``slice_from`` derive from this so the timeline logic lives in a single place."""
        # Rightmost item whose start is <= now (start-inclusive); end-exclusive airing check.
        idx = bisect.bisect_right(self.starts, now) - 1
        if idx >= 0 and now < self.ends[idx]:  # now is inside items[idx]
            return _Located(True, idx, (now - self.starts[idx]).total_seconds(), 0.0)
        nxt = bisect.bisect_right(self.starts, now)  # first item starting after now
        if nxt < len(self.items):  # before-first / in a silence gap (R11): play the gap, then go on
            return _Located(False, nxt, 0.0, (self.starts[nxt] - now).total_seconds())
        return _Located(False, len(self.items), 0.0, 0.0)  # past the last item -> regenerate

    def find_now(self, now: datetime) -> NowPlaying:
        loc = self._locate(now)
        if loc.airing:
            nxt = self.items[loc.index + 1] if loc.index + 1 < len(self.items) else None
            return NowPlaying(self.items[loc.index], loc.offset, nxt, 0.0)
        if loc.index < len(self.items):  # R11 gap before items[index]
            return NowPlaying(None, 0.0, self.items[loc.index], loc.gap)
        return NowPlaying(None, 0.0, None, 0.0)

    def slice_from(self, now: datetime) -> tuple[list[ScheduleItem], float, float]:
        """``(items from now to end-of-day, seek offset into the first, leading gap seconds)`` —
        the play-slice view of ``_locate`` (``find_now`` is the resume view of the same bisect)."""
        loc = self._locate(now)
        return list(self.items[loc.index :]), loc.offset, loc.gap


def anchor(schedule: DailySchedule, *, transition_silence: float) -> AnchoredSchedule:
    """Rebuild ``schedule``'s timeline from the anchor + exact durations + silence (R12).

    Ignores every stored ``planned_start`` except the first item's (the anchor): for
    Phase-1 schedules that anchor is an exact midnight / slot boundary, so the rebuilt
    timeline is exact. ``transition_silence`` is re-applied here because the models store
    ``duration`` as content-only (the silence was never folded in).
    """
    items = schedule.items
    cursor = items[0].planned_start
    starts: list[datetime] = []
    ends: list[datetime] = []
    for item in items:
        end = cursor + timedelta(seconds=item.duration)
        starts.append(cursor)
        ends.append(end)
        cursor = end + timedelta(seconds=transition_silence)
    return AnchoredSchedule(items=items, starts=tuple(starts), ends=tuple(ends))


def find_now(schedule: DailySchedule, clock: Clock, *, transition_silence: float) -> NowPlaying:
    """Convenience: anchor the schedule and answer for ``clock.now()`` in one call."""
    return anchor(schedule, transition_silence=transition_silence).find_now(clock.now())
