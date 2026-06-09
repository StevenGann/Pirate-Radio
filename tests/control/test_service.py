"""RED tests for ``pirate_radio.control.service`` read paths — Phase-6 P6-2.

``ControlService`` is the typed read/control core over the coordinator's live state — pure-tested
with a FAKE registry/configs + an INJECTED schedule loader (no FastAPI, no real FS). Read paths:
list_stations (from the StationStatus registry), now_playing (anchor today's schedule + find_now),
schedule (the day's items). Unknown station → StationNotFound; a valid station with no schedule for
a date → ScheduleNotFound (both map to 404 in the API).
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pirate_radio.catalog.models import Track
from pirate_radio.clock import FixedClock
from pirate_radio.config import PiperTTSConfig, StationConfig
from pirate_radio.control.service import ControlService, ScheduleNotFound, StationNotFound
from pirate_radio.schedule.models import DailySchedule, StationIdItem, TrackItem
from pirate_radio.status import StationState, StationStatus

_TZ = ZoneInfo("America/New_York")
_NOW = datetime(2026, 6, 10, 0, 0, 30, tzinfo=_TZ)  # just inside the day's first item


def _config(name: str) -> StationConfig:
    return StationConfig(
        name=name,
        schedule_dir=Path("/sched"),
        content_dir=Path("/content"),
        dj_personality="warm",
        tts=(PiperTTSConfig(backend="piper", voice="v"),),
        audio_device=f"usb-{name}",
    )


def _schedule(day: date) -> DailySchedule:
    start = datetime(2026, 6, 10, 0, 0, tzinfo=_TZ)
    track = Track(path=Path("/c/g/a.flac"), group="g", duration=600.0, title="Song", artist="Band")
    items = (
        TrackItem(planned_start=start, duration=600.0, block_name="Morning", track=track),
        StationIdItem(planned_start=start, duration=5.0, block_name="Morning"),
    )
    return DailySchedule(date=day, station="Pi0", seed=1, items=items)


def _service(**over) -> ControlService:
    registry = over.pop(
        "registry",
        {
            "Pi0": StationStatus(name="Pi0", state=StationState.ON_AIR),
            "Pi1": StationStatus(
                name="Pi1", state=StationState.CRASHED, restart_count=2, last_error="boom"
            ),
        },
    )
    configs = over.pop("configs", {"Pi0": _config("Pi0"), "Pi1": _config("Pi1")})
    loaded = over.pop("load_schedule", lambda name, day: _schedule(day))
    clock = FixedClock(over.pop("clock_at", _NOW))
    return ControlService(
        registry=registry,
        configs=configs,
        clock=clock,
        load_schedule=loaded,
        skip=over.pop("skip", None),
        regenerate=over.pop("regenerate", None),
    )


# ---- list_stations -------------------------------------------------------------------------
def test_list_stations_uses_config_order_not_registry_order() -> None:
    # DA: a registry iterating Pi1-before-Pi0 must STILL list in config order (deterministic)
    registry = {
        "Pi1": StationStatus(
            name="Pi1", state=StationState.CRASHED, restart_count=2, last_error="boom"
        ),
        "Pi0": StationStatus(name="Pi0", state=StationState.ON_AIR),
    }
    views = _service(registry=registry).list_stations()
    assert [v.name for v in views] == ["Pi0", "Pi1"]  # config order wins over dict order
    assert views[0].state == "on_air"
    assert views[1].restart_count == 2 and views[1].last_error == "boom"


def test_list_stations_station_missing_from_registry_defaults_to_starting() -> None:
    # a config station not yet in the registry (startup) is still listed, not a KeyError
    only_pi0 = {"Pi0": StationStatus(name="Pi0", state=StationState.ON_AIR)}
    views = _service(registry=only_pi0).list_stations()
    assert [v.name for v in views] == ["Pi0", "Pi1"] and views[1].state == "starting"


# ---- now_playing ---------------------------------------------------------------------------
def test_now_playing_reports_the_airing_item() -> None:
    np = _service().now_playing("Pi0")
    assert np.station == "Pi0" and np.playing is True
    assert np.item_kind == "track" and np.block == "Morning"
    assert np.offset_seconds == pytest.approx(30.0)  # 30s into the first item
    assert np.title == "Song" and np.artist == "Band"  # a TrackItem surfaces its tags


def test_now_playing_in_a_gap_reports_next_and_threads_transition_silence() -> None:
    # at T+601s item0 (600s) has ended; with the config's 2s transition_silence the next item starts
    # at T+602, so we are in the gap. (silence=0 would put us INSIDE item1 — so this also pins that
    # the service threads the per-station transition_silence into anchor.) DA/QA gap case.
    np = _service(clock_at=datetime(2026, 6, 10, 0, 10, 1, tzinfo=_TZ)).now_playing("Pi0")
    assert np.playing is False and np.item_kind is None
    assert np.next_item_kind == "station_id" and np.gap_seconds == pytest.approx(1.0)


def test_now_playing_past_end_of_day_has_no_next() -> None:
    np = _service(clock_at=datetime(2026, 6, 10, 0, 30, tzinfo=_TZ)).now_playing("Pi0")
    assert np.playing is False and np.next_item_kind is None and np.gap_seconds == 0.0


def test_now_playing_unknown_station_raises() -> None:
    with pytest.raises(StationNotFound):
        _service().now_playing("Nope")


def test_now_playing_with_no_schedule_is_not_playing() -> None:
    svc = _service(load_schedule=lambda name, day: None)
    np = svc.now_playing("Pi0")
    assert np.playing is False and np.item_kind is None and np.next_item_kind is None


# ---- schedule ------------------------------------------------------------------------------
def test_schedule_returns_the_days_items() -> None:
    view = _service().schedule("Pi0")
    assert view.station == "Pi0"
    assert view.item_count == len(view.items) == 2  # item_count is consistent with items (DA)
    assert view.items[0].kind == "track" and view.items[0].title == "Song"
    assert view.items[1].kind == "station_id" and view.items[1].title is None  # patter has no tags


def test_schedule_unknown_station_does_not_attempt_a_load() -> None:
    # DA: an unknown name must 404 BEFORE any load (no spurious file read)
    loaded: list[str] = []

    def _load(name: str, day: date) -> DailySchedule:
        loaded.append(name)
        return _schedule(day)

    with pytest.raises(StationNotFound):
        _service(load_schedule=_load).schedule("Nope")
    assert loaded == []


def test_schedule_honours_an_explicit_date() -> None:
    seen: list[date] = []

    def _load(name: str, day: date) -> DailySchedule:
        seen.append(day)
        return _schedule(day)

    _service(load_schedule=_load).schedule("Pi0", date(2026, 6, 12))
    assert seen == [date(2026, 6, 12)]  # the requested date, not today


def test_schedule_unknown_station_raises() -> None:
    with pytest.raises(StationNotFound):
        _service().schedule("Nope")


def test_schedule_missing_for_date_raises_schedule_not_found() -> None:
    svc = _service(load_schedule=lambda name, day: None)
    with pytest.raises(ScheduleNotFound):
        svc.schedule("Pi0", date(2025, 1, 1))


# ---- control paths (P6-3) -----------------------------------------------------------------
def test_skip_invokes_the_injected_skip() -> None:
    seen: list[str] = []
    _service(skip=seen.append).skip("Pi0")
    assert seen == ["Pi0"]


def test_skip_unknown_station_raises_before_invoking() -> None:
    seen: list[str] = []
    with pytest.raises(StationNotFound):
        _service(skip=seen.append).skip("Nope")
    assert seen == []


async def test_regenerate_awaits_the_injected_regenerate() -> None:
    seen: list[str] = []

    async def _regen(name: str) -> None:
        seen.append(name)

    await _service(regenerate=_regen).regenerate("Pi0")
    assert seen == ["Pi0"]


async def test_regenerate_unknown_station_raises_before_invoking() -> None:
    seen: list[str] = []

    async def _regen(name: str) -> None:
        seen.append(name)

    with pytest.raises(StationNotFound):
        await _service(regenerate=_regen).regenerate("Nope")
    assert seen == []
