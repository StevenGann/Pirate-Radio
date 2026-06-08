"""Per-station orchestration (Phase 4) — the supervised unit (``Supervisable``).

Each day: **load-or-generate** the persisted ``DailySchedule`` (R6 — corruption/absence regenerates
from source, never a crash-loop), **anchor** it (R12), drive the daily slice via ``play_day`` (R11
gap + seek + never-dead-air), then **await the day-roll** ``asyncio.Event`` (set by the midnight
task after it has written the new day's file — the write-then-signal ordering, §E) and re-slice.
Cold start and post-crash restart use the identical path (§6): reload from disk + ``find_now`` vs
``clock.now()``. ``skip_item`` is the supervisor's advance-past-poison net (the producer also
backstops render-poison in-band). Updates an in-memory ``StationStatus`` for the operator summary.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import date
from pathlib import Path

from pirate_radio.audio.buffer import DEFAULT_SAMPLE_RATE, AudioBuffer
from pirate_radio.audio.decode import Decoder
from pirate_radio.catalog.scanner import Catalog
from pirate_radio.clock import Clock
from pirate_radio.config import StationConfig
from pirate_radio.dj.protocols import AudioSink, TextGenerator, TTSEngine
from pirate_radio.errors import StateCorruptionError
from pirate_radio.persistence import atomic_write_json, load_with_recovery
from pirate_radio.pipeline.daily import play_day
from pirate_radio.pipeline.timing import Sleeper
from pirate_radio.schedule.generator import derive_seed, generate_schedule
from pirate_radio.schedule.grid import Grid
from pirate_radio.schedule.models import SCHEDULE_SCHEMA_VERSION, DailySchedule
from pirate_radio.schedule.resume import anchor
from pirate_radio.status import StationState, StationStatus

logger = logging.getLogger(__name__)

_DEFAULT_MAXSIZE = 2


class Station:
    """A single station's day loop. Built by the coordinator; supervised by the Supervisor."""

    def __init__(
        self,
        *,
        config: StationConfig,
        clock: Clock,
        sink: AudioSink,
        decoder: Decoder,
        sleeper: Sleeper,
        tts: TTSEngine,
        text_generator: TextGenerator,
        persona: str,
        backstop: AudioBuffer,
        catalog: Catalog,
        grid_loader: Callable[[date], Grid],
        state_dir: Path,
        day_roll: asyncio.Event,
        refill_budget_seconds: float,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        channels: int = 1,
        maxsize: int = _DEFAULT_MAXSIZE,
        start_delay_seconds: float = 0.0,
        on_status: Callable[[StationStatus], None] | None = None,
    ) -> None:
        self._config = config
        self.name = config.name
        self._clock = clock
        self._sink = sink
        self._decoder = decoder
        self._sleeper = sleeper
        self._tts = tts
        self._text_generator = text_generator
        self._persona = persona
        self._backstop = backstop
        self._catalog = catalog
        self._grid_loader = grid_loader
        self._state_dir = state_dir
        self._day_roll = day_roll
        self._refill_budget = refill_budget_seconds
        self._sample_rate = sample_rate
        self._channels = channels
        self._maxsize = maxsize
        self._start_delay = (
            start_delay_seconds  # §A render-stagger (H-RPi-3); applied once at start
        )
        self._on_status = on_status
        self._poisoned: set[int] = set()  # supervisor advance-past-poison net (defensive)

    def skip_item(self, index: int) -> None:
        """Record a poison item index (the supervisor calls this after K crashes). The producer
        backstops render-poison in-band; this is the net for a crash that escapes the producer."""
        self._poisoned.add(index)

    def _status(self, state: StationState, **kw: object) -> None:
        if self._on_status is not None:
            self._on_status(StationStatus(name=self.name, state=state, **kw))  # type: ignore[arg-type]

    def _schedule_path(self, day: date) -> Path:
        return self._state_dir / self.name / f"{day.isoformat()}.json"

    def _load_or_generate(self, day: date) -> DailySchedule:
        path = self._schedule_path(day)
        try:
            return load_with_recovery(path, DailySchedule, schema_version=SCHEDULE_SCHEMA_VERSION)
        except StateCorruptionError:
            pass  # R6: absent or corrupt -> regenerate from source (NOT a crash-loop)
        grid = self._grid_loader(day)
        schedule = generate_schedule(
            grid=grid,
            catalog=self._catalog,
            station=self._config,
            clock=self._clock,
            seed=derive_seed(day, self.name),
        )
        path.parent.mkdir(parents=True, exist_ok=True)  # state_dir/<station>/ may not exist yet
        atomic_write_json(path, schedule, schema_version=SCHEDULE_SCHEMA_VERSION)
        return schedule

    async def run(self) -> None:
        if self._start_delay > 0:  # §A stagger: de-sync the first render across stations (H-RPi-3)
            await self._sleeper.sleep(self._start_delay)
        while True:
            self._status(StationState.STARTING)
            day = self._clock.now().date()
            schedule = self._load_or_generate(day)
            anchored = anchor(schedule, transition_silence=self._config.transition_silence_seconds)
            self._status(StationState.ON_AIR)
            await play_day(
                anchored=anchored,
                now=self._clock.now(),
                tts=self._tts,
                decoder=self._decoder,
                sink=self._sink,
                backstop=self._backstop,
                sleeper=self._sleeper,  # forwarded to run_once via play_day (R23 cooperative wait)
                refill_budget_seconds=self._refill_budget,
                text_generator=self._text_generator,
                persona=self._persona,
                station_name=self.name,
                station_tagline=self._config.tagline,
                loudness_target_lufs=self._config.loudness_target_lufs,
                sample_rate=self._sample_rate,
                channels=self._channels,
                transition_silence=self._config.transition_silence_seconds,
                maxsize=self._maxsize,
            )
            self._status(StationState.REGENERATING)  # end of day; awaiting the midnight roll
            await self._day_roll.wait()  # set by the midnight task AFTER writing the new day's file
            self._day_roll.clear()
