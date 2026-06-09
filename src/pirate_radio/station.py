"""Per-station orchestration (Phase 4) — the supervised unit (``Supervisable``).

Each day: **load-or-generate** the persisted ``DailySchedule`` (R6 — corruption/absence regenerates
from source, never a crash-loop), **anchor** it (R12), drive the daily slice via ``play_day`` (R11
gap + seek + never-dead-air), then **await the day-roll** ``asyncio.Event`` (set by the midnight
task after it has written the new day's file — the write-then-signal ordering, §E) and re-slice.
Cold start and post-crash restart use the identical path (§6): reload from disk + ``find_now`` vs
``clock.now()``. Render-poison is handled IN-BAND by the producer (backstop + station-tagged
CRITICAL), so the Station exposes no ``skip_item`` — a poison item never escapes to need one.
Updates an in-memory ``StationStatus`` for the operator summary.
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
        skip: asyncio.Event | None = None,
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
        self._skip = skip if skip is not None else asyncio.Event()  # control-API skip (P6-3)
        # serializes schedule regeneration (midnight roll + an API --regenerate) for THIS station
        # so two writers never race the same file's .bak rotation (P6-3 / DA).
        self._regen_lock = asyncio.Lock()
        self._refill_budget = refill_budget_seconds
        self._sample_rate = sample_rate
        self._channels = channels
        self._maxsize = maxsize
        self._start_delay = (
            start_delay_seconds  # §A render-stagger (H-RPi-3); applied once at start
        )
        self._on_status = on_status

    def prepare_next_day(self, *, force: bool = False) -> None:
        """Generate + persist the schedule for the clock's current day (the midnight task calls this
        just after the roll, BEFORE ``signal_day_roll`` — the file-then-event ordering, §E/Q2).
        Reuses ``_load_or_generate`` so cold-start, restart, and day-roll share one path. ``force``
        (the ``--regenerate`` oneshot) overwrites an existing file — an operator regenerating after
        grid edit wants the NEW grid, not the cached schedule."""
        self._load_or_generate(self._clock.now().date(), force=force)

    def signal_day_roll(self) -> None:
        """Set the day-roll Event (the midnight task calls this AFTER ``prepare_next_day`` has
        written the new day's file). The ``run`` loop, parked on ``day_roll.wait()`` at end of day,
        wakes and re-slices onto the freshly-written schedule."""
        self._day_roll.set()

    def signal_skip(self) -> None:
        """Request a skip (the control API calls this). The player drops the next item at the next
        boundary and clears the Event — one-shot; does NOT cut the currently-airing item (P6-3)."""
        self._skip.set()

    @property
    def regen_lock(self) -> asyncio.Lock:
        """Per-station regeneration lock — the midnight roll and an API ``--regenerate`` both take
        it so they never race the same schedule file's ``.bak`` rotation (P6-3)."""
        return self._regen_lock

    def _status(self, state: StationState, **kw: object) -> None:
        if self._on_status is not None:
            self._on_status(StationStatus(name=self.name, state=state, **kw))  # type: ignore[arg-type]

    def _schedule_path(self, day: date) -> Path:
        return self._state_dir / self.name / f"{day.isoformat()}.json"

    def _load_or_generate(self, day: date, *, force: bool = False) -> DailySchedule:
        path = self._schedule_path(day)
        if not force:  # force (--regenerate) skips the load so an edited grid is picked up
            try:
                return load_with_recovery(
                    path, DailySchedule, schema_version=SCHEDULE_SCHEMA_VERSION
                )
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
        # Open the audio device/stream ONCE for the station's whole lifetime — the real
        # SoundDeviceSink starts its persistent stream in __aenter__, so ``play`` only ever runs on
        # an open stream; __aexit__ tears it down on exit/crash so a restart can't leak it.
        async with self._sink:
            while True:
                self._status(StationState.STARTING)
                logger.info("station %s starting", self.name)  # operator log vocabulary (§H)
                day = self._clock.now().date()
                schedule = self._load_or_generate(day)
                anchored = anchor(
                    schedule, transition_silence=self._config.transition_silence_seconds
                )
                self._status(StationState.ON_AIR)
                logger.info("station %s on air (schedule %s)", self.name, day.isoformat())
                await play_day(
                    anchored=anchored,
                    now=self._clock.now(),
                    tts=self._tts,
                    decoder=self._decoder,
                    sink=self._sink,
                    backstop=self._backstop,
                    sleeper=self._sleeper,  # forwarded to run_once via play_day (R23 cooperative)
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
                    skip=self._skip,  # control-API skip-at-next-boundary (P6-3)
                )
                self._status(StationState.REGENERATING)  # end of day; awaiting the midnight roll
                await self._day_roll.wait()  # set by midnight AFTER writing the new day's file
                self._day_roll.clear()
