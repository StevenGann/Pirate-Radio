"""The coordinator — shared services, DJ inputs, the §A look-ahead budget, status (Phase-4 §D).

Build-once (§5.1): per station resolve the LLM and build the ranked text chain **cached per
identical resolved LLM** (shared chains, not one-per-station), resolve the persona, build the TTS
chain, load the catalog, and mint one pre-normalized backstop — all from the **one global audio
format** (``DEFAULT_SAMPLE_RATE``, mono) so decoder/TTS/backstop agree by construction (Q7). Compute
the §A budget once: ``depth = max worst-consecutive-patter + 1`` across stations, **RAM FAIL-FAST**
(a budget too small to afford the worst cluster is a boot ``ConfigError``, not a silent clamp — C1),
a deterministic per-station **stagger**, and a cold-start **WARNING** for the irreducible
opening-cluster residual (R11-covered). Build one ``Station`` per config station wired to the
injected ``sink_factory`` (the coordinator never imports ``sounddevice``), own the ``StationStatus``
registry + the periodic "N/N ON AIR" summary, and ``run()`` gathers the supervisor + the midnight
task (P4-7, schedule day-roll) + the summary, concurrently.

Audio-buffer day-roll **prewarm** (rendering the opening cluster during the outgoing day's final
item) is deferred — it would span the day boundary inside the FROZEN ``run_once`` (Q1). The midnight
task delivers the **schedule prewarm** (new day's file ready before the splice); the residual
is the same bounded one-cluster R11 backstop as a cold start. Flagged for the P4-9 deep-dive.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from datetime import date
from pathlib import Path

from pirate_radio.audio.buffer import DEFAULT_SAMPLE_RATE, AudioBuffer
from pirate_radio.audio.decode import Decoder
from pirate_radio.audio_devices import AudioDeviceResolver, PortId
from pirate_radio.catalog.cache import CatalogCache
from pirate_radio.catalog.scanner import Catalog
from pirate_radio.clock import Clock
from pirate_radio.config import DaemonConfig, StationConfig
from pirate_radio.dj.build import (
    build_text_generator,
    build_tts_engine,
    resolve_persona,
    resolve_station_llm,
)
from pirate_radio.dj.failover import RankedTextGenerator
from pirate_radio.dj.protocols import AudioSink
from pirate_radio.errors import ConfigError
from pirate_radio.lookahead import (
    _LOOKAHEAD_RAM_BUDGET_BYTES,
    lookahead_depth,
    resolve_lookahead_depth,
    stagger_offset,
    worst_case_patter_render,
)
from pirate_radio.pipeline.timing import Sleeper
from pirate_radio.schedule.generator import derive_seed, generate_schedule
from pirate_radio.schedule.grid import (
    Grid,
    load_grid,
    resolve_grid_path,
    validate_grid_against_catalog,
)
from pirate_radio.schedule.models import DailySchedule, TrackItem
from pirate_radio.station import Station
from pirate_radio.status import StationState, StationStatus

logger = logging.getLogger(__name__)

_BACKSTOP_SECONDS = (
    5.0  # the R11 silence backstop length (v1; a canned bumper asset is a later nicety)
)
_SUMMARY_PERIOD_SECONDS = 60.0  # how often the "N/N ON AIR" operator summary is logged (Field-Op)


def _default_on_escalate() -> None:  # pragma: no cover - the prod process-exit path (R7 tier-1)
    # The supervisor breached its restart ceiling: exit so the systemd tier restarts the daemon.
    # os._exit (NOT sys.exit) because a SystemExit raised inside asyncio.gather is converted to a
    # CancelledError and swallowed (P4-3 finding) — only os._exit reliably ends the process.
    logger.critical("coordinator: supervisor escalation -> process exit for the systemd tier")
    os._exit(1)


def _default_grid_loader(station: StationConfig, day: date, *, catalog: Catalog) -> Grid:
    # §8.2 resolution + §8.3 validation against THIS station's catalog (fail loud at boot, not 3am).
    path = resolve_grid_path(station.schedule_dir, day.weekday())
    grid = load_grid(path)
    validate_grid_against_catalog(grid, catalog.group_names(), path)
    return grid


class Coordinator:
    """Owns the daemon's shared services, the §A budget, the status registry, and ``run()``."""

    def __init__(
        self,
        *,
        config: DaemonConfig,
        clock: Clock,
        resolver: AudioDeviceResolver,
        sleeper: Sleeper,
        sink_factory: Callable[[PortId], AudioSink],
        on_escalate: Callable[[], None] | None = None,
        catalog_loader: Callable[[Path], Catalog] | None = None,
        grid_loader: Callable[[StationConfig, date], Grid] | None = None,
        decoder_factory: Callable[[], Decoder] | None = None,
        summary_period_seconds: float = _SUMMARY_PERIOD_SECONDS,
        ram_budget_bytes: int = _LOOKAHEAD_RAM_BUDGET_BYTES,
    ) -> None:
        self._config = config
        self._clock = clock
        self._resolver = resolver
        self._sleeper = sleeper
        self._sink_factory = sink_factory
        self._on_escalate = on_escalate or _default_on_escalate
        self._summary_period = summary_period_seconds
        cache = CatalogCache()
        self._catalog_loader: Callable[[Path], Catalog] = catalog_loader or cache.load
        self._grid_loader = grid_loader
        self._decoder = (decoder_factory or self._build_decoder)()
        self._llm_cache: dict[object, RankedTextGenerator] = {}  # §5.1 shared-chain cache

        from pirate_radio.midnight import MidnightTask
        from pirate_radio.supervisor import Supervisor

        self._supervisor = Supervisor(sleeper=sleeper, on_escalate=self._on_escalate)
        self.registry: dict[str, StationStatus] = {}
        self.depth: int = 1
        self.stations: list[Station] = self._build_stations(ram_budget_bytes)
        # The midnight task rolls every station's schedule at 00:00 (DST-correct, per-station
        # isolated, file-then-event). It shares the Stations' own day-roll Events (§E/Q2).
        self._midnight = MidnightTask(stations=self.stations, clock=clock, sleeper=sleeper)

    # ---- build-once -----------------------------------------------------------------------
    def _build_decoder(self) -> Decoder:  # pragma: no cover - the real-decoder boot line (R20-ish)
        from pirate_radio.audio.decode import FfmpegDecoder

        binary = str(self._config.ffmpeg_binary) if self._config.ffmpeg_binary else "ffmpeg"
        return FfmpegDecoder(
            binary=binary,
            sample_rate=DEFAULT_SAMPLE_RATE,
            channels=1,
            timeout_seconds=self._config.decode_timeout_seconds,
        )

    def _text_generator_for(self, station: StationConfig) -> RankedTextGenerator:
        llm = resolve_station_llm(
            station, self._config
        )  # §12 per-station override or daemon global
        cached = self._llm_cache.get(llm)
        if cached is None:
            cached = build_text_generator(llm)  # reads secrets by env-name at build (H22)
            self._llm_cache[llm] = cached
        return cached

    def _resolve_sink(self, station: StationConfig) -> AudioSink:
        port_id = self._resolver.resolve(station.audio_device)
        if port_id is None:  # R10: never hand the sink a name that didn't resolve to a port
            raise ConfigError(
                f"station {station.name!r}: audio_device {station.audio_device!r} does not "
                f"resolve to a device on this host"
            )
        return self._sink_factory(port_id)

    def _grid_for(self, station: StationConfig, catalog: Catalog) -> Callable[[date], Grid]:
        if self._grid_loader is not None:
            loader = self._grid_loader
            return lambda day: loader(station, day)
        return lambda day: _default_grid_loader(station, day, catalog=catalog)

    def _build_stations(self, ram_budget_bytes: int) -> list[Station]:
        n = len(self._config.stations)
        stations_cfg = self._config.stations
        catalogs = [self._catalog_loader(s.content_dir) for s in stations_cfg]
        grid_loaders = [self._grid_for(s, c) for s, c in zip(stations_cfg, catalogs, strict=True)]
        backstop = AudioBuffer.silence(
            seconds=_BACKSTOP_SECONDS, sample_rate=DEFAULT_SAMPLE_RATE, channels=1
        )

        # §A budget: measure the worst patter cluster from each station's generated schedule.
        depths: list[int] = []
        shortest_patter = float("inf")
        worst_case_render = 0.0
        for station, catalog, grid_loader in zip(stations_cfg, catalogs, grid_loaders, strict=True):
            schedule = self._generate_for_budget(station, catalog, grid_loader)
            depths.append(lookahead_depth(schedule.items))
            for item in schedule.items:
                if not isinstance(item, TrackItem):
                    shortest_patter = min(shortest_patter, item.duration)
            llm = resolve_station_llm(station, self._config)
            worst_case_render = max(
                worst_case_render,
                worst_case_patter_render(
                    [llm.request_timeout_seconds] * len(llm.providers),
                    [self._config.tts_timeout_seconds] * len(station.tts),
                ),
            )

        needed = max(depths) if depths else 1
        worst_track = max((t.duration for c in catalogs for t in c.tracks), default=1.0)
        self.depth = (
            resolve_lookahead_depth(  # FAIL-FAST ConfigError if RAM can't afford the cluster
                needed_depth=needed,
                worst_track_seconds=worst_track,
                n_stations=n,
                ram_budget_bytes=ram_budget_bytes,
                sample_rate=DEFAULT_SAMPLE_RATE,
                channels=1,
            )
        )
        if shortest_patter != float("inf") and worst_case_render > shortest_patter:
            logger.warning(
                "cold start residual: worst-case patter render %.0fs exceeds the shortest opening "
                "patter item %.0fs; a daemon COLD START (no prior audio) airs the R11 backstop for "
                "one cluster render before the buffer warms (not dead air; not a sustained loop)",
                worst_case_render,
                shortest_patter,
            )

        stations: list[Station] = []
        for index, (station, catalog, grid_loader) in enumerate(
            zip(self._config.stations, catalogs, grid_loaders, strict=True)
        ):
            self.registry[station.name] = StationStatus(
                name=station.name, state=StationState.STARTING
            )
            stations.append(
                Station(
                    config=station,
                    clock=self._clock,
                    sink=self._resolve_sink(station),
                    decoder=self._decoder,
                    sleeper=self._sleeper,
                    tts=build_tts_engine(
                        station, self._config, sample_rate=DEFAULT_SAMPLE_RATE, channels=1
                    ),
                    text_generator=self._text_generator_for(station),
                    persona=resolve_persona(station),
                    backstop=backstop,
                    catalog=catalog,
                    grid_loader=grid_loader,
                    state_dir=self._config.state_dir,
                    day_roll=asyncio.Event(),
                    refill_budget_seconds=worst_case_render,
                    sample_rate=DEFAULT_SAMPLE_RATE,
                    channels=1,
                    maxsize=self.depth,
                    start_delay_seconds=stagger_offset(index),
                    on_status=self._record,
                )
            )
        return stations

    def _generate_for_budget(
        self, station: StationConfig, catalog: Catalog, grid_loader: Callable[[date], Grid]
    ) -> DailySchedule:
        day = self._clock.now().date()
        return generate_schedule(
            grid=grid_loader(day),
            catalog=catalog,
            station=station,
            clock=self._clock,
            seed=derive_seed(day, station.name),
        )

    # ---- status registry + summary --------------------------------------------------------
    def _record(self, status: StationStatus) -> None:
        self.registry[status.name] = status

    def _log_summary(self) -> None:
        on_air = sum(1 for s in self.registry.values() if s.state == StationState.ON_AIR)
        total = len(self.registry)
        states = ", ".join(f"{s.name}={s.state.value}" for s in self.registry.values())
        logger.info("%d/%d ON AIR — %s", on_air, total, states)

    async def _summary_loop(self) -> None:
        while (
            True
        ):  # pragma: no cover - exercised via _log_summary; the loop is a thin sleeper wrap
            self._log_summary()
            await self._sleeper.sleep(self._summary_period)

    async def run(self) -> None:
        """Supervise every station + roll schedules at midnight + log the periodic summary,
        concurrently (R7 tier-2). A crash/escalation in one never cancels the siblings."""
        await asyncio.gather(
            self._supervisor.run(self.stations),
            self._midnight.run(),
            self._summary_loop(),
        )
