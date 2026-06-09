"""RED tests for ``pirate_radio.coordinator`` — Phase-4 plan §D / P4-6b.

The coordinator owns the build-once shared services (shared-LLM chain reuse, per-station
persona/TTS/catalog/backstop), computes the §A look-ahead budget once (depth = worst cluster + 1;
RAM **FAIL-FAST**; deterministic **stagger**; cold-start WARNING), builds one ``Station`` per config
station wired to an injected ``sink_factory`` (no hardware), owns the ``StationStatus`` registry +
the periodic "N/N ON AIR" summary, and ``run()`` gathers the supervisor + summary. The heavy seams
(catalog scan, grid load, decoder, real sink) are injected so this pins the WIRING with fakes (R21).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pirate_radio.audio.buffer import DEFAULT_SAMPLE_RATE, AudioBuffer
from pirate_radio.audio.decode import FakeDecoder
from pirate_radio.audio_devices import PortId, StaticAudioDeviceResolver
from pirate_radio.catalog.models import Track
from pirate_radio.catalog.scanner import Catalog
from pirate_radio.clock import FixedClock
from pirate_radio.config import (
    DaemonConfig,
    EspeakTTSConfig,
    LLMConfig,
    OllamaLLMConfig,
    StationConfig,
)
from pirate_radio.coordinator import Coordinator
from pirate_radio.dj.fakes import FakeAudioSink
from pirate_radio.errors import ConfigError
from pirate_radio.lookahead import _STAGGER_STEP_SECONDS
from pirate_radio.schedule.grid import Grid, Slot
from pirate_radio.status import StationState, StationStatus

_TZ = ZoneInfo("America/New_York")
_NOW = datetime(2026, 6, 10, 9, 30, tzinfo=_TZ)


def _catalog(content_dir: Path) -> Catalog:
    return Catalog(
        content_dir=content_dir,
        tracks=(Track(path=content_dir / "g" / "a.flac", group="g", duration=200.0, title="A"),),
    )


def _grid(_station: StationConfig, _day: date) -> Grid:
    return Grid(
        name="G", slots=(Slot(start=time(0, 0), end=time(0, 0), group="g", name="All Day"),)
    )


def _llm(model: str = "m") -> LLMConfig:
    return LLMConfig(
        providers=(OllamaLLMConfig(backend="ollama", model=model, endpoint="http://lan:1"),)
    )


def _station(tmp_path: Path, name: str, device: str, llm: LLMConfig) -> StationConfig:
    return StationConfig(
        name=name,
        schedule_dir=tmp_path / name / "sched",
        content_dir=tmp_path / name / "content",
        dj_personality=f"{name} is warm",
        tts=(EspeakTTSConfig(backend="espeak", voice="en"),),
        audio_device=device,
        llm=llm,
    )


def _config(tmp_path: Path, *, n: int = 2, shared_llm: bool = True) -> DaemonConfig:
    base = _llm()
    # shared: every station uses the value-identical `base` (cache hit). distinct: each station gets
    # a DIFFERENT-VALUED llm (distinct model) so the value-keyed cache mints a separate chain.
    stations = tuple(
        _station(tmp_path, f"Pi{i}", f"usb-{i}", base if shared_llm else _llm(f"m{i}"))
        for i in range(n)
    )
    return DaemonConfig(llm=base, state_dir=tmp_path / "state", stations=stations)


def _resolver(n: int = 2) -> StaticAudioDeviceResolver:
    return StaticAudioDeviceResolver({f"usb-{i}": f"port-{i}" for i in range(n)})


def _coord(tmp_path: Path, **over) -> Coordinator:
    from pirate_radio.pipeline.timing import VirtualSleeper

    n = over.pop("n", 2)
    kw: dict = {
        "config": over.pop("config", None) or _config(tmp_path, n=n),
        "clock": FixedClock(_NOW),
        "resolver": over.pop("resolver", None) or _resolver(n),
        "sleeper": VirtualSleeper(),
        "sink_factory": over.pop("sink_factory", None) or (lambda port_id: FakeAudioSink()),
        "on_escalate": lambda: None,
        "catalog_loader": _catalog,
        "grid_loader": _grid,
        "decoder_factory": lambda: FakeDecoder(),
    }
    kw.update(over)
    return Coordinator(**kw)


# ---- build-once shared services -----------------------------------------------------------
def test_builds_one_station_per_config_station(tmp_path) -> None:
    coord = _coord(tmp_path)
    assert [s.name for s in coord.stations] == ["Pi0", "Pi1"]


def test_shares_one_text_generator_for_identical_resolved_llm(tmp_path) -> None:
    # §5.1: two stations with the SAME resolved LLM share one ranked chain (cache hit), not two
    coord = _coord(tmp_path, config=_config(tmp_path, shared_llm=True))
    assert coord.stations[0]._text_generator is coord.stations[1]._text_generator


def test_distinct_llm_gets_distinct_text_generator(tmp_path) -> None:
    coord = _coord(tmp_path, config=_config(tmp_path, shared_llm=False))
    assert coord.stations[0]._text_generator is not coord.stations[1]._text_generator


def test_supplies_real_persona_and_station_identity(tmp_path) -> None:
    # Q4: the coordinator supplies real persona/station so the producer sentinels never fire in prod
    coord = _coord(tmp_path)
    assert coord.stations[0]._persona == "Pi0 is warm"


# ---- §A budget: depth = worst cluster + 1 -------------------------------------------------
def test_lookahead_depth_is_worst_cluster_plus_one(tmp_path) -> None:
    # the all-day grid opens block_transition + station_id (top-of-hour) -> cluster 2 -> depth 3
    coord = _coord(tmp_path)
    assert coord.depth == 3
    assert coord.stations[0]._maxsize == 3  # threaded into run_once(maxsize=depth) via the Station


def test_ram_budget_fail_fast_raises_configerror(tmp_path) -> None:
    # Rev-2 amendment: a budget too small to afford the worst cluster is a boot ConfigError, NOT a
    # silent clamp (which would regress C1). One byte is far below depth-3 × 2 × 200s buffers.
    with pytest.raises(ConfigError):
        _coord(tmp_path, ram_budget_bytes=1)


# ---- stagger (deterministic per index) ----------------------------------------------------
def test_stagger_offsets_are_deterministic_per_index(tmp_path) -> None:
    coord = _coord(tmp_path)
    assert coord.stations[0]._start_delay == 0.0
    assert coord.stations[1]._start_delay == _STAGGER_STEP_SECONDS


# ---- cold-start WARNING (the irreducible residual; R11-covered) ----------------------------
def test_cold_start_warning_is_logged_at_build(tmp_path, caplog) -> None:
    # worst_case_patter_render (Σ chain timeouts) >> the 5s station_id that opens the day with no
    # masking track -> a startup WARNING naming the one-render cold-start residual (R11 backstop).
    with caplog.at_level(logging.WARNING):
        _coord(tmp_path)
    assert any("cold start" in r.message.lower() for r in caplog.records)


# ---- actual-rate: one global format wired everywhere (Q7) ----------------------------------
def test_one_station_format_wired_to_decoder_backstop_station(tmp_path) -> None:
    coord = _coord(tmp_path)
    st = coord.stations[0]
    assert st._sample_rate == DEFAULT_SAMPLE_RATE and st._channels == 1
    assert st._backstop.sample_rate == DEFAULT_SAMPLE_RATE and st._backstop.channels == 1
    assert isinstance(st._backstop, AudioBuffer)


# ---- sink_factory injection seam (no hardware) --------------------------------------------
def test_sink_factory_is_called_with_each_resolved_port_id(tmp_path) -> None:
    seen: list[PortId] = []

    def factory(port_id: PortId) -> FakeAudioSink:
        seen.append(port_id)
        return FakeAudioSink()

    _coord(tmp_path, sink_factory=factory)
    assert sorted(seen) == [PortId("port-0"), PortId("port-1")]  # each station's resolved PortId


def test_unresolvable_audio_device_raises_configerror(tmp_path) -> None:
    # R10: a configured device that does not resolve to a PortId fails fast (never a wrong sink)
    with pytest.raises(ConfigError):
        _coord(tmp_path, resolver=StaticAudioDeviceResolver({"usb-0": "port-0"}))  # usb-1 missing


# ---- StationStatus registry + periodic summary --------------------------------------------
def test_registry_has_every_station_initially(tmp_path) -> None:
    coord = _coord(tmp_path)
    assert set(coord.registry) == {"Pi0", "Pi1"}


def test_summary_counts_on_air_from_the_registry(tmp_path, caplog) -> None:
    coord = _coord(tmp_path)
    coord.registry["Pi0"] = StationStatus(name="Pi0", state=StationState.ON_AIR)
    coord.registry["Pi1"] = StationStatus(name="Pi1", state=StationState.CRASHED)
    with caplog.at_level(logging.INFO):
        coord._log_summary()
    msg = "\n".join(r.message for r in caplog.records)
    assert "1/2 ON AIR" in msg  # answerable from journald alone (Field-Op), no HTTP


# ---- run() wiring -------------------------------------------------------------------------
async def test_run_gathers_the_supervisor_over_all_stations(tmp_path, monkeypatch) -> None:
    coord = _coord(tmp_path)
    supervised: list = []

    async def _fake_supervise(units):
        supervised.append(list(units))

    monkeypatch.setattr(coord._supervisor, "run", _fake_supervise)
    monkeypatch.setattr(coord, "_summary_loop", lambda: _noop())
    monkeypatch.setattr(
        coord._midnight, "run", lambda: _noop()
    )  # P4-7 task; its own suite covers it
    await coord.run()
    assert supervised and [u.name for u in supervised[0]] == ["Pi0", "Pi1"]


async def _noop() -> None:
    return None


# ---- control actions (P6-3) ---------------------------------------------------------------
def test_skip_sets_the_stations_skip_event(tmp_path) -> None:
    coord = _coord(tmp_path)
    station = coord.stations[0]
    assert not station._skip.is_set()
    coord.skip("Pi0")
    assert station._skip.is_set()  # the player will drop the next item at the boundary


async def test_regenerate_station_offloads_under_the_regen_lock(tmp_path) -> None:
    # the regen must run through the injected offload (R23) AND hold the station's regen lock so it
    # can't race the midnight roll (P6-3). Prove the lock gates it: hold it -> regen can't run.
    import asyncio

    offloaded: list = []

    async def _offload(fn, *a, **kw):
        offloaded.append(fn)
        return None  # don't actually generate (no catalog/grid IO in this unit test)

    coord = _coord(tmp_path, offload=_offload)
    station = coord.stations[0]
    await station.regen_lock.acquire()  # simulate the midnight roll holding the lock
    task = asyncio.create_task(coord.regenerate_station("Pi0"))
    await asyncio.sleep(0.02)
    assert offloaded == []  # BLOCKED: the regen waits on the lock the "midnight roll" holds
    station.regen_lock.release()
    await task
    assert offloaded  # ran only after the lock was free (serialized vs midnight)


def test_build_control_service_is_wired_to_the_coordinator(tmp_path) -> None:
    # P6-5: the coordinator builds a ControlService over its registry + skip/regenerate actions.
    coord = _coord(tmp_path)
    svc = coord.build_control_service()
    assert [v.name for v in svc.list_stations()] == ["Pi0", "Pi1"]
    svc.skip("Pi0")  # the service's skip routes to the coordinator -> the station's skip Event
    assert coord.stations[0]._skip.is_set()
