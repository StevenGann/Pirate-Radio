"""RED tests for ``pirate_radio.station`` — Phase 4 plan §station-loop / P4-5.

The per-station supervised unit: load-or-generate today's schedule (R6: corruption/absence →
regenerate, never crash-loop), anchor (R12), drive the daily slice via ``play_day``, then await the
day-roll ``asyncio.Event`` and re-slice. Updates its ``StationStatus`` and opens the sink as an
async context manager (the real stream starts in ``__aenter__``). Render-poison is handled in-band
by the producer, so the Station exposes no ``skip_item``. The orchestration is tested with the
persistence/generator/play_day seams monkeypatched so this pins the Station's CONTROL FLOW.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import date, datetime
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

from pirate_radio.audio.buffer import AudioBuffer
from pirate_radio.audio.decode import FakeDecoder
from pirate_radio.catalog.scanner import Catalog
from pirate_radio.clock import FixedClock
from pirate_radio.config import PiperTTSConfig, StationConfig
from pirate_radio.dj.failover import RankedTextGenerator
from pirate_radio.dj.fakes import FakeAudioSink, NullDJ, StubTTS
from pirate_radio.errors import StateCorruptionError
from pirate_radio.pipeline.timing import VirtualSleeper
from pirate_radio.schedule.models import DailySchedule, StationIdItem
from pirate_radio.station import Station
from pirate_radio.status import StationState
from pirate_radio.supervisor import Supervisable

_DAY = date(2026, 6, 10)


def _schedule() -> DailySchedule:
    item = StationIdItem(
        planned_start=datetime(2026, 6, 10, tzinfo=ZoneInfo("UTC")), duration=5.0, block_name="B"
    )
    return DailySchedule(date=_DAY, station="S", seed=1, items=(item,))


def _config(tmp_path: Path) -> StationConfig:
    return StationConfig(
        name="PiRate One",
        schedule_dir=tmp_path / "sched",
        content_dir=tmp_path / "content",
        dj_personality="warm",
        tts=(PiperTTSConfig(backend="piper", voice="v"),),
        audio_device="usb-1",
    )


def _station(tmp_path: Path, **over) -> Station:
    kw: dict = {
        "config": _config(tmp_path),
        "clock": FixedClock(datetime(2026, 6, 10, 9, 30, tzinfo=ZoneInfo("America/New_York"))),
        "sink": FakeAudioSink(),
        "decoder": FakeDecoder(),
        "sleeper": VirtualSleeper(),
        "tts": StubTTS(),
        "text_generator": RankedTextGenerator([NullDJ()]),
        "persona": "warm",
        "backstop": AudioBuffer.silence(seconds=1.0),
        "catalog": cast(Catalog, object()),  # unused: generate is monkeypatched in tests
        "grid_loader": lambda day: object(),  # unused: generate is monkeypatched
        "state_dir": tmp_path / "state",
        "day_roll": asyncio.Event(),
        "refill_budget_seconds": 5.0,
    }
    kw.update(over)
    return Station(**kw)


def test_station_is_supervisable(tmp_path) -> None:
    assert isinstance(_station(tmp_path), Supervisable)
    assert _station(tmp_path).name == "PiRate One"


def test_load_or_generate_uses_persisted_when_present(tmp_path, monkeypatch) -> None:
    sched = _schedule()
    monkeypatch.setattr("pirate_radio.station.load_with_recovery", lambda *a, **k: sched)
    gen_called: list = []
    monkeypatch.setattr("pirate_radio.station.generate_schedule", lambda **k: gen_called.append(1))
    assert _station(tmp_path)._load_or_generate(_DAY) is sched and not gen_called


def test_load_or_generate_regenerates_on_corruption(tmp_path, monkeypatch) -> None:
    def _corrupt(*a, **k):  # R6: corrupt/absent
        raise StateCorruptionError("both gone", path=Path("x"))

    monkeypatch.setattr("pirate_radio.station.load_with_recovery", _corrupt)
    gen = _schedule()
    monkeypatch.setattr("pirate_radio.station.generate_schedule", lambda **k: gen)
    written: list = []
    monkeypatch.setattr(
        "pirate_radio.station.atomic_write_json", lambda p, m, **k: written.append((p, m))
    )
    out = _station(tmp_path)._load_or_generate(_DAY)
    assert out is gen and written and written[0][1] is gen  # regenerated AND persisted (R6)


def test_prepare_next_day_generates_and_persists(tmp_path, monkeypatch) -> None:
    # the midnight task calls this just after the roll; it must write the new day's file (§E/Q2)
    def _corrupt(*a, **k):
        raise StateCorruptionError("absent", path=Path("x"))

    monkeypatch.setattr("pirate_radio.station.load_with_recovery", _corrupt)
    monkeypatch.setattr("pirate_radio.station.generate_schedule", lambda **k: _schedule())
    written: list = []
    monkeypatch.setattr(
        "pirate_radio.station.atomic_write_json", lambda p, m, **k: written.append(p)
    )
    _station(tmp_path).prepare_next_day()
    assert written  # the schedule FILE is written (before the event is ever set)


def test_signal_day_roll_sets_the_event(tmp_path) -> None:
    ev = asyncio.Event()
    _station(tmp_path, day_roll=ev).signal_day_roll()
    assert ev.is_set()  # the run loop, parked on day_roll.wait(), will wake and re-slice


def test_signal_skip_sets_the_skip_event(tmp_path) -> None:
    st = _station(tmp_path)
    assert not st._skip.is_set()
    st.signal_skip()
    assert st._skip.is_set()  # the player drops the next item at the boundary


async def test_run_clears_a_stale_skip_at_each_slice_start(tmp_path, monkeypatch) -> None:
    # P6-6 / DA: a skip set near end-of-day (after the player's last boundary check) must NOT leak
    # across the day-roll and eat the new day's opening item. The slice start clears it, so play_day
    # always begins with a clean flag.
    skip_states: list[bool] = []
    played = asyncio.Event()

    async def _fake_play_day(**kw):
        skip_states.append(kw["skip"].is_set())  # what the slice sees at its start
        played.set()

    monkeypatch.setattr("pirate_radio.station.play_day", _fake_play_day)
    monkeypatch.setattr("pirate_radio.station.load_with_recovery", lambda *a, **k: _schedule())

    st = _station(tmp_path)
    st.signal_skip()  # a stale skip carried into the slice
    assert st._skip.is_set()
    task = asyncio.create_task(st.run())
    await asyncio.wait_for(played.wait(), 2.0)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert skip_states[0] is False  # the slice started with the stale skip cleared, not set


async def test_run_discards_a_stale_day_roll_before_slicing(tmp_path, monkeypatch) -> None:
    # CF 0063 / DA: a day-roll signal left SET from before this slice (the midnight task fired while
    # this station was crashed/restarting or airing a tail past 00:00) must be DISCARDED at slice
    # start, not consumed as an instant spurious same-day re-slice. The next real roll is awaited.
    play_count = 0
    played = asyncio.Event()

    async def _fake_play_day(**kw):
        nonlocal play_count
        play_count += 1
        played.set()

    monkeypatch.setattr("pirate_radio.station.play_day", _fake_play_day)
    monkeypatch.setattr("pirate_radio.station.load_with_recovery", lambda *a, **k: _schedule())

    day_roll = asyncio.Event()
    day_roll.set()  # STALE: set before run() even reaches its wait()
    st = _station(tmp_path, day_roll=day_roll)
    task = asyncio.create_task(st.run())
    await asyncio.wait_for(played.wait(), 2.0)  # first slice played
    await asyncio.sleep(0.05)  # a buggy impl (consume-the-stale-set) would re-slice here
    assert play_count == 1  # the stale signal did NOT trigger a second slice
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_run_reslices_once_when_the_roll_fires_during_play_day(tmp_path, monkeypatch) -> None:
    # CF 0063 / focused panel: a day-roll signalled WHILE play_day runs (an item straddling 00:00)
    # must be observed exactly once -> exactly one re-slice, never lost. The clear-at-top reorder
    # protects this; a spurious clear before the bottom wait() would drop the in-flight roll and
    # strand the station on the old day for ~24h (mutation-proven gap).
    slices = 0
    second = asyncio.Event()
    day_roll = asyncio.Event()

    async def _fake_play_day(**kw):
        nonlocal slices
        slices += 1
        if slices == 1:
            day_roll.set()  # the roll fires DURING the first slice's play_day (the straddle case)
        else:
            second.set()
            await asyncio.Event().wait()  # park the 2nd slice so exactly one re-slice is counted

    monkeypatch.setattr("pirate_radio.station.play_day", _fake_play_day)
    monkeypatch.setattr("pirate_radio.station.load_with_recovery", lambda *a, **k: _schedule())

    st = _station(tmp_path, day_roll=day_roll)
    task = asyncio.create_task(st.run())
    await asyncio.wait_for(second.wait(), 2.0)  # the roll-during-play was observed -> a 2nd slice
    assert slices == 2  # exactly one re-slice; the in-flight roll was not lost
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_run_releases_the_regen_lock_before_play_day(tmp_path, monkeypatch) -> None:
    # the regen lock guards only the daily LOAD, not the broadcast — holding it across play_day
    # would block the midnight roll's prepare_next_day for the whole day. Assert it's free in play.
    played = asyncio.Event()
    locked_during_play: list[bool] = []

    async def _fake_play_day(**kw):
        locked_during_play.append(st.regen_lock.locked())
        played.set()

    monkeypatch.setattr("pirate_radio.station.play_day", _fake_play_day)
    monkeypatch.setattr("pirate_radio.station.load_with_recovery", lambda *a, **k: _schedule())

    st = _station(tmp_path)
    task = asyncio.create_task(st.run())
    await asyncio.wait_for(played.wait(), 2.0)
    assert locked_during_play == [False]  # lock released after the load, before airtime
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_run_daily_load_is_serialized_by_the_regen_lock(tmp_path, monkeypatch) -> None:
    # CF 0063 / DA: the daily reslice load must hold regen_lock so it can't race a concurrent
    # regenerate write (midnight roll / API regenerate) on the same station's schedule file.
    loaded: list[int] = []

    def _load(*_a, **_k):
        loaded.append(1)
        return _schedule()

    async def _fake_play_day(**kw):
        await asyncio.sleep(0)

    monkeypatch.setattr("pirate_radio.station.play_day", _fake_play_day)
    monkeypatch.setattr("pirate_radio.station.load_with_recovery", _load)

    st = _station(tmp_path)
    await st.regen_lock.acquire()  # a concurrent regenerate is holding the lock
    task = asyncio.create_task(st.run())
    await asyncio.sleep(0.05)
    assert loaded == []  # BLOCKED: run() cannot load while the regen lock is held
    st.regen_lock.release()
    await asyncio.sleep(0.05)
    assert loaded  # loaded only after the lock was free (serialized vs the writer)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_run_plays_the_day_then_awaits_dayroll(tmp_path, monkeypatch) -> None:
    played = asyncio.Event()
    calls: list = []

    async def _fake_play_day(**kw):
        calls.append(kw)
        played.set()

    monkeypatch.setattr("pirate_radio.station.play_day", _fake_play_day)
    monkeypatch.setattr("pirate_radio.station.load_with_recovery", lambda *a, **k: _schedule())

    st = _station(tmp_path)
    task = asyncio.create_task(st.run())
    await asyncio.wait_for(played.wait(), 2.0)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert calls[0]["station_name"] == "PiRate One"  # the day was played, station threaded through
    assert calls[0]["persona"] == "warm"


async def test_run_reslices_on_dayroll_signal(tmp_path, monkeypatch) -> None:
    plays = 0
    play_event = asyncio.Event()

    async def _fake_play_day(**kw):
        nonlocal plays
        plays += 1
        play_event.set()

    monkeypatch.setattr("pirate_radio.station.play_day", _fake_play_day)
    monkeypatch.setattr("pirate_radio.station.load_with_recovery", lambda *a, **k: _schedule())

    day_roll = asyncio.Event()
    st = _station(tmp_path, day_roll=day_roll)
    task = asyncio.create_task(st.run())
    await asyncio.wait_for(play_event.wait(), 2.0)  # first day played
    play_event.clear()
    day_roll.set()  # signal the day-roll -> Station re-slices the new day
    await asyncio.wait_for(play_event.wait(), 2.0)  # played again after the roll
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert plays >= 2  # re-sliced and played the new day on the roll signal


async def test_run_reports_status_transitions(tmp_path, monkeypatch) -> None:
    states: list[StationState] = []

    async def _fake_play_day(**kw):
        pass

    monkeypatch.setattr("pirate_radio.station.play_day", _fake_play_day)
    monkeypatch.setattr("pirate_radio.station.load_with_recovery", lambda *a, **k: _schedule())

    st = _station(tmp_path, on_status=lambda s: states.append(s.state))
    task = asyncio.create_task(st.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert StationState.ON_AIR in states  # the operator can see the station went on air


async def test_run_logs_the_operator_starting_and_on_air_vocabulary(
    tmp_path, monkeypatch, caplog
) -> None:
    import logging

    async def _fake_play_day(**kw):
        pass

    monkeypatch.setattr("pirate_radio.station.play_day", _fake_play_day)
    monkeypatch.setattr("pirate_radio.station.load_with_recovery", lambda *a, **k: _schedule())
    st = _station(tmp_path)
    with caplog.at_level(logging.INFO):
        task = asyncio.create_task(st.run())
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    msgs = "\n".join(r.message for r in caplog.records)
    assert "PiRate One starting" in msgs and "PiRate One on air" in msgs  # §H, station-tagged


async def test_run_opens_the_sink_as_a_context_manager(tmp_path, monkeypatch) -> None:
    # deep-dive CRITICAL: the station MUST enter the sink (the real SoundDeviceSink starts its
    # stream in __aenter__); a sink driven only via play() would crash on real hardware.
    async def _fake_play_day(**kw):
        pass

    monkeypatch.setattr("pirate_radio.station.play_day", _fake_play_day)
    monkeypatch.setattr("pirate_radio.station.load_with_recovery", lambda *a, **k: _schedule())
    sink = FakeAudioSink()
    st = _station(tmp_path, sink=sink)
    task = asyncio.create_task(st.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert sink.entered  # the stream was opened before any play()
