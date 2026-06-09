"""The control-API service layer (Phase 6, P6-2/P6-3) — the typed read/control core.

`ControlService` is FastAPI-free: it reads the coordinator's live `StationStatus` registry and the
on-disk schedules (via an INJECTED loader) and exposes typed views. Now-playing is re-derived from
the schedule + the clock (`anchor` + `find_now`), the same A7 "no persisted playhead" path the
daemon resumes from — never a second source of truth. Unknown station → ``StationNotFound``; a valid
station with no schedule for a date → ``ScheduleNotFound`` (both → 404 in the API).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date

from pydantic import BaseModel, ConfigDict

from pirate_radio.clock import Clock
from pirate_radio.config import StationConfig
from pirate_radio.errors import PirateRadioError
from pirate_radio.schedule.models import DailySchedule, ScheduleItem, TrackItem
from pirate_radio.schedule.resume import NowPlaying, anchor
from pirate_radio.status import StationState, StationStatus

LoadSchedule = Callable[[str, date], DailySchedule | None]


class StationNotFound(PirateRadioError):
    """No station with the given name (→ 404)."""


class ScheduleNotFound(PirateRadioError):
    """A known station has no schedule for the requested date (→ 404)."""


class StationView(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    state: str
    restart_count: int
    last_error: str | None


class NowPlayingView(BaseModel):
    model_config = ConfigDict(frozen=True)
    station: str
    playing: bool
    item_kind: str | None
    block: str | None
    offset_seconds: float
    title: str | None
    artist: str | None
    next_item_kind: str | None
    gap_seconds: float


class ScheduleItemView(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: str
    block_name: str
    duration: float
    title: str | None
    artist: str | None


class ScheduleView(BaseModel):
    model_config = ConfigDict(frozen=True)
    station: str
    date: date
    item_count: int
    items: list[ScheduleItemView]


def _track_tags(item: ScheduleItem) -> tuple[str | None, str | None]:
    return (item.track.title, item.track.artist) if isinstance(item, TrackItem) else (None, None)


def _now_view(station: str, np: NowPlaying) -> NowPlayingView:
    next_kind = np.next_item.kind if np.next_item is not None else None
    if np.item is None:  # gap (next set) or past end-of-day (next None) — not airing
        return NowPlayingView(
            station=station,
            playing=False,
            item_kind=None,
            block=None,
            offset_seconds=0.0,
            title=None,
            artist=None,
            next_item_kind=next_kind,
            gap_seconds=np.gap_seconds,
        )
    title, artist = _track_tags(np.item)
    return NowPlayingView(
        station=station,
        playing=True,
        item_kind=np.item.kind,
        block=np.item.block_name,
        offset_seconds=np.offset_seconds,
        title=title,
        artist=artist,
        next_item_kind=next_kind,
        gap_seconds=0.0,
    )


def _item_view(item: ScheduleItem) -> ScheduleItemView:
    title, artist = _track_tags(item)
    return ScheduleItemView(
        kind=item.kind,
        block_name=item.block_name,
        duration=item.duration,
        title=title,
        artist=artist,
    )


class ControlService:
    def __init__(
        self,
        *,
        registry: Mapping[str, StationStatus],
        configs: Mapping[str, StationConfig],
        clock: Clock,
        load_schedule: LoadSchedule,
    ) -> None:
        self._registry = registry
        self._configs = configs
        self._clock = clock
        self._load_schedule = load_schedule

    def _require(self, name: str) -> StationConfig:
        config = self._configs.get(name)
        if config is None:
            raise StationNotFound(f"no station named {name!r}")
        return config

    def list_stations(self) -> list[StationView]:
        """Every configured station (config order) with its status — a station not yet in the
        registry (startup) shows ``starting`` rather than raising."""
        out: list[StationView] = []
        for name in self._configs:
            status = self._registry.get(name) or StationStatus(
                name=name, state=StationState.STARTING
            )
            out.append(
                StationView(
                    name=name,
                    state=status.state.value,
                    restart_count=status.restart_count,
                    last_error=status.last_error,
                )
            )
        return out

    def now_playing(self, name: str) -> NowPlayingView:
        config = self._require(name)
        schedule = self._load_schedule(name, self._clock.now().date())
        if schedule is None:
            return _now_view(name, NowPlaying(None, 0.0, None, 0.0))
        anchored = anchor(schedule, transition_silence=config.transition_silence_seconds)
        return _now_view(name, anchored.find_now(self._clock.now()))

    def schedule(self, name: str, on: date | None = None) -> ScheduleView:
        self._require(name)
        day = on or self._clock.now().date()
        schedule = self._load_schedule(name, day)
        if schedule is None:
            raise ScheduleNotFound(f"station {name!r} has no schedule for {day.isoformat()}")
        return ScheduleView(
            station=name,
            date=day,
            item_count=len(schedule.items),
            items=[_item_view(i) for i in schedule.items],
        )
