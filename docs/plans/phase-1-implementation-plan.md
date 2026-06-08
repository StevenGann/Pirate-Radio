# Phase 1 Implementation Plan — MVP Vertical Slice

> **Status:** For the seven-agent panel.
> **Builds on:** Phase 0 (`config.py`, `clock.py`, `errors.py`, `persistence.py`,
> `catalog/`, `schedule/grid.py`, `audio_devices.py`) — all adopted and merged. This
> plan **does not re-plan Phase 0**; every signature below is wired to the real
> Phase-0 APIs read at authoring time.
> **Governing authority:** `PiRate_Radio_Design_Doc.md` §21 *Review Resolutions* and
> `docs/decisions/0001`–`0008`. Where this plan and §21 disagree, **§21 governs.**

The roadmap (§20) defines Phase 1 as: *"Single station: daily schedule generation
(fill rule + transition silence), producer/player with a stub TTS (logs the
announcements it would make), `sounddevice` output to a real device, `find_now`
resume. Proves gapless playback + broadcast-time + scheduling."* The guiding
principle (§20 close): **prove the hard part — gapless playback through the look-ahead
buffer on a wall-clock schedule — with everything else stubbed**, each future
capability dropping in behind a Protocol without rewiring the core.

---

## 1. Scope & Non-Scope

### 1.1 In scope (testable, CI-runnable core)

| Area | Module(s) | What ships |
|---|---|---|
| Schedule data models | `schedule/models.py` | `ScheduleItem` discriminated union on `kind` (R17), `DailySchedule` (date/station/items) with `SCHEMA_VERSION` |
| Schedule generation | `schedule/generator.py` | grid + catalog → `DailySchedule` via the §8.4 fill rule; seedable RNG (R19); transition silence; block_transition / station_id / block_reminder emission |
| Broadcast-time resume | `schedule/resume.py` | `find_now` with the R11 gap/None path + R12 drift re-anchor; persist/load via `persistence.py` |
| Audio buffer model | `audio/buffer.py` | `AudioBuffer` (R14): NumPy `samples`, `sample_rate`, `channels`, normalized shape |
| Decode seam | `audio/decode.py` | `Decoder` Protocol + `FakeDecoder` (track path → silent `AudioBuffer` of the track's known duration). **Real ffmpeg deferred to Phase 2** (see §3.3) |
| Backend protocols + fakes | `dj/protocols.py`, `dj/fakes.py`, `audio/sink.py` | `TTSEngine`, `TextGenerator`, `AudioSink` Protocols (R15 docstrings); `NullDJ`, `StubTTS`, `FakeAudioSink` |
| Error taxonomy | `errors.py` (extend) | `ProviderError → ProviderUnavailable / ProviderQuotaExceeded / ProviderFatal` (R15), attached under existing `PirateRadioError` |
| Look-ahead pipeline | `pipeline/buffer.py`, `pipeline/producer.py`, `pipeline/player.py`, `pipeline/segment.py` | bounded `asyncio.Queue` (depth 1–2); producer renders ahead; player drains gaplessly; **R11 canned backstop** fires the instant a refill misses its deadline (R21 virtual-time tests) |
| Config addition | `config.py` (extend) | `state_dir` field (A6) with existence + **writability** validation |
| Async timing seam | `pipeline/timing.py` | `Sleeper` Protocol (`real` + virtual-time fake) so pipeline tests use **zero wall-clock sleeps** (R21) |

### 1.2 Stubbed in Phase 1 (behind a Protocol, real impl deferred)

- **TTS** — `StubTTS` logs the announcement it *would* speak and returns a
  deterministic-length silent `AudioBuffer`. Real **Piper/espeak/ElevenLabs** = Phase 2/3.
- **DJ brain (TextGenerator)** — `NullDJ` only (returns empty/canned). Grounded LLM
  patter = Phase 3.
- **Audio decode** — `FakeDecoder` (silent buffer at the track's metadata duration).
  Real ffmpeg subprocess decode + resample = Phase 2 (lands with loudness; §3.3).
- **Loudness normalization** — entirely Phase 2 (`audio/loudness.py` not created now).

### 1.3 Deferred / out of scope (and why)

- **`SoundDeviceSink` (real PortAudio output)** — only the literal `sounddevice` call
  is `@pytest.mark.hardware` (R20). The class is a thin seam over the `AudioSink`
  Protocol; CI exercises `FakeAudioSink`. The roadmap's "`sounddevice` output to a
  real device" is the *one* hardware-bound deliverable and is verified manually on the
  Pi, not in CI.
- **Loudness, real TTS/LLM, failover wrapper, multi-station, supervisor, control API,
  midnight regen daemon loop** — all later phases. Phase 1 ships the *single-station,
  single-day* slice; `coordinator.py`/`supervisor.py`/`station.py` are **not** built
  yet (a thin `run_once` harness in tests drives producer+player against one
  persisted schedule; see §6.7).
- **R13 subprocess spike, R10 real udev resolver, R8′ log store, D4 API** — explicitly
  not Phase 1.

---

## 2. §21 Resolutions: implemented vs deferred in Phase 1

| Resolution | Phase 1? | How / why |
|---|---|---|
| **R11** never-dead-air + `find_now` gap path | **Implement** | Canned `AudioBuffer` backstop in the player; `find_now` returns a typed `NowPlaying` (next-item + wait, never undefined dead air) |
| **R12** bound drift / re-anchor | **Implement** | `find_now` re-anchors on the nearest exact-duration `track` rather than trusting persisted estimated `planned_start` |
| **R14** `AudioBuffer` first-class model | **Implement** | `audio/buffer.py` |
| **R15** Protocol error taxonomy | **Implement (base only)** | `ProviderError` subtree added to `errors.py`; Protocol docstrings state units/threading/idempotency. The *failover wrapper* that branches on retryable is Phase 3 |
| **R17** `ScheduleItem` union + `schema_version` | **Implement** | `schedule/models.py` |
| **R18** injectable clock | **Reuse (done)** | `clock.Clock` injected into generator + `find_now` |
| **R19** seedable scheduler | **Implement** | injected `random.Random`; (catalog+grid+seed+clock) → byte-identical JSON |
| **R20** thin hardware seam + coverage honesty | **Implement** | only `SoundDeviceSink.play` is `@pytest.mark.hardware` + `pragma: no cover`; 80% floor stays package-wide |
| **R21** virtual-time pipeline + failover tests | **Implement (pipeline)** | asyncio + fakes + injected clock + `Sleeper` virtual time; failover-only tests are Phase 3 |
| **A6** `state_dir` off boot SD | **Implement** | Phase 1 is the **first state writer**, so the deferred A6 field lands now with existence + writability validation |
| **A7** persistence not for hot paths | **Honor** | resume-state writes **batch/debounce** (one write per item boundary at most, coalesced; §4.4) — never per-sample |
| **A9** catalog mtime-cached rescan | **Implement (scanner side)** | small `catalog/cache.py` wrapping `scan_catalog` with mtime check; generator consumes a `Catalog` either way |
| R5/R6 atomic+recovery | **Reuse (done)** | schedule + resume persisted via `persistence.py` |
| R7 systemd / R8′ logs / R10 udev / R13 spike / D4 API | **Defer** | later phases (see §1.3) |
| R16 typed configs | **Reuse (done)** | Phase-0 discriminated unions already cover config |

---

## 3. New Dependencies

Keep additions minimal and ARM-clean. **No audio hardware/SDK on the CI test path.**

### 3.1 Runtime
```toml
# pyproject.toml [project].dependencies — ADD:
"numpy>=1.26,<3",        # AudioBuffer samples (R14). Pure compute; wheels on ARM64.
```
`numpy` is the **only** new runtime dep in Phase 1. `sounddevice` is **not** added to
`dependencies`; it is an *optional* extra so CI never imports PortAudio:
```toml
[project.optional-dependencies]
audio = ["sounddevice>=0.4,<0.6"]   # imported only inside SoundDeviceSink (hardware)
```
`SoundDeviceSink` imports `sounddevice` lazily *inside* `play()` so the module imports
without the extra; the hardware test is the only thing that needs it.

### 3.2 Dev
```toml
# [project.optional-dependencies].dev — ADD:
"pytest-asyncio>=0.23",   # async test functions for the pipeline (R21)
```
Configure in `pyproject.toml`:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"     # plain `async def test_...` are collected
```

### 3.3 ffmpeg decode decision — **stub in Phase 1, real in Phase 2**

**Recommendation: ship a `Decoder` Protocol + `FakeDecoder` now; defer the real
ffmpeg subprocess to Phase 2.** Justification:

1. **Phase 1's thesis is timing, not fidelity.** The hard part (§5.3) is gapless
   look-ahead on a wall-clock schedule. That is fully exercised with silent buffers of
   the *correct duration* — decode correctness adds nothing to the timing proof and a
   lot of test fragility (golden audio, ffmpeg-on-CI).
2. **R22 already pairs decode with loudness in Phase 2** ("drop pydub, use direct
   ffmpeg subprocess; one loudness path = pyloudnorm"). Decode + resample + EBU-R128
   normalization are one coherent unit of work; splitting decode into Phase 1 would
   ship a buffer at the *wrong* loudness, then immediately rework it.
3. **R20 wants the hardware/native seam thin.** A `Decoder` Protocol keeps the ffmpeg
   subprocess behind one interface (same pattern as `AudioSink`), so Phase 2 drops in
   `FfmpegDecoder` with no pipeline rewrite.

The `FakeDecoder` reads `Track.duration` (exact, from metadata — §7) and synthesizes a
silent `AudioBuffer` of exactly that many samples, so the player's timing math is real.

---

## 4. Module-by-Module Design

All models are **frozen** (`ConfigDict(frozen=True)`), fully type-hinted, no bare
dicts (R16), and fail-fast at boundaries — matching Phase-0 style (small files,
immutable, typed). `from __future__ import annotations` at the top of every module.

### 4.1 `errors.py` (extend) — R15 provider taxonomy base

Phase-0 `errors.py` already says the provider subtree "is intentionally NOT here yet —
it is Phase 3". Phase 1 needs the **base classes** now (StubTTS/NullDJ live behind the
Protocols, and the pipeline catches `ProviderError` to fire the R11 backstop), so we
land the *taxonomy* now and the *failover wrapper that branches on it* in Phase 3.

```python
# appended to src/pirate_radio/errors.py

class ProviderError(PirateRadioError):
    """Base for any TTS/LLM/decode backend failure (R15).

    Failover (Phase 3) retries only the *retryable* branch
    (``ProviderUnavailable`` / ``ProviderQuotaExceeded``); ``ProviderFatal`` is
    terminal for that provider. In Phase 1 the pipeline treats ANY ProviderError as
    "render failed -> fire the R11 backstop, never dead air".
    """

class ProviderUnavailable(ProviderError):
    """Transient: connection refused/timeout, 5xx, model loading. Retryable."""

class ProviderQuotaExceeded(ProviderError):
    """Rate/credit limit hit (HTTP 429 / quota). Retryable against the NEXT provider."""

class ProviderFatal(ProviderError):
    """Non-retryable for this provider: bad request, auth failure, unsupported input."""
```

### 4.2 `audio/buffer.py` — `AudioBuffer` (R14)

```python
"""AudioBuffer: the one buffer shape every pipeline stage produces/consumes (R14).

Normalized shape: float32 samples in [-1.0, 1.0], 2-D (frames, channels). A mono
buffer is (frames, 1) -- never 1-D -- so the player/sink never branch on rank.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True)
class AudioBuffer:
    samples: npt.NDArray[np.float32]   # shape (frames, channels), dtype float32
    sample_rate: int                   # Hz, > 0
    channels: int                      # >= 1, == samples.shape[1]

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError(f"sample_rate must be > 0, got {self.sample_rate}")
        if self.samples.ndim != 2:
            raise ValueError(f"samples must be 2-D (frames, channels), got ndim={self.samples.ndim}")
        if self.samples.shape[1] != self.channels:
            raise ValueError(
                f"channels={self.channels} != samples.shape[1]={self.samples.shape[1]}"
            )
        if self.samples.dtype != np.float32:
            raise ValueError(f"samples must be float32, got {self.samples.dtype}")

    @property
    def frames(self) -> int:
        return int(self.samples.shape[0])

    @property
    def duration_seconds(self) -> float:
        return self.frames / self.sample_rate

    @classmethod
    def silence(cls, *, seconds: float, sample_rate: int = 48_000, channels: int = 1) -> AudioBuffer:
        frames = max(0, round(seconds * sample_rate))
        return cls(np.zeros((frames, channels), dtype=np.float32), sample_rate, channels)
```
`AudioBuffer` is a `dataclass`, not a Pydantic model: NumPy arrays are not natural
Pydantic fields and this object never round-trips through JSON (it stays in RAM). It is
still frozen + validated, consistent with the immutability rule.

### 4.3 `schedule/models.py` — `ScheduleItem` union (R17) + `DailySchedule`

R17: a discriminated union on `kind` so invalid states are unrepresentable (a `track`
item must carry a `Track`; a `block_transition` must not). All variants share
`planned_start` (tz-aware) + `duration` + `block_name`.

```python
"""ScheduleItem discriminated union (R17) + DailySchedule (persisted, schema_version)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pirate_radio.catalog.models import Track

SCHEDULE_SCHEMA_VERSION = 1   # R17 envelope version for persistence.py

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class _ItemBase(BaseModel):
    model_config = _FROZEN
    planned_start: datetime          # tz-aware estimate (R12: estimate for patter)
    duration: float = Field(gt=0.0)  # seconds, incl. nothing else (silence is separate)
    block_name: str = Field(min_length=1)

    @field_validator("planned_start")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("planned_start must be tz-aware (D6)")
        return v


class TrackItem(_ItemBase):
    kind: Literal["track"] = "track"
    track: Track                     # required -> R17 invalid states unrepresentable
    intro: bool = False
    outro: bool = False


class StationIdItem(_ItemBase):
    kind: Literal["station_id"] = "station_id"


class BlockTransitionItem(_ItemBase):
    kind: Literal["block_transition"] = "block_transition"
    next_block_name: str = Field(min_length=1)
    next_block_starts_at: datetime


class BlockReminderItem(_ItemBase):
    kind: Literal["block_reminder"] = "block_reminder"


ScheduleItem = Annotated[
    TrackItem | StationIdItem | BlockTransitionItem | BlockReminderItem,
    Field(discriminator="kind"),
]


class DailySchedule(BaseModel):
    model_config = _FROZEN
    date: date
    station: str = Field(min_length=1)
    seed: int                         # the RNG seed used (R19 reproducibility record)
    items: tuple[ScheduleItem, ...] = Field(min_length=1)
```
`duration` on a `TrackItem` is the *content* duration; the inter-element
`transition_silence_seconds` is timing the generator applies between items (§8.4) and
the player renders as a silent gap — it is **not** folded into `duration`, so
`find_now`'s exact-track re-anchor (R12) stays exact.

> **Design note for the panel (R17 vs §13).** §13 sketches a single flat
> `ScheduleItem` with optional fields and an `ItemKind` including `"bumper"`. R17
> *governs* and mandates the union. Phase 1 omits the `"bumper"` kind (no bumper
> content in the MVP); it can be added as another union arm later without touching
> persisted v1 schedules generated without it. `dj_context` (§13) is **not** a field
> in Phase 1 — `NullDJ` needs no context — and arrives as a typed model in Phase 3
> (R16), bumping `SCHEDULE_SCHEMA_VERSION`.

### 4.4 `schedule/persistence.py` glue (no new file — thin helpers in `resume.py`)

Persist/load via the Phase-0 primitive. One generated schedule per day, mirroring
§8.4's path convention:

```python
# in schedule/resume.py
from pirate_radio.persistence import atomic_write_json, load_with_recovery
from pirate_radio.schedule.models import DailySchedule, SCHEDULE_SCHEMA_VERSION

def schedule_path(state_dir: Path, station: str, day: date) -> Path:
    return state_dir / "schedules" / _slug(station) / f"{day.isoformat()}.json"

def save_schedule(state_dir: Path, schedule: DailySchedule) -> None:
    atomic_write_json(
        schedule_path(state_dir, schedule.station, schedule.date),
        schedule,
        schema_version=SCHEDULE_SCHEMA_VERSION,
    )

def load_schedule(state_dir: Path, station: str, day: date) -> DailySchedule:
    return load_with_recovery(
        schedule_path(state_dir, station, day),
        DailySchedule,
        schema_version=SCHEDULE_SCHEMA_VERSION,
    )
```
> **A8′/A6 path note.** §8.4 says `<schedule_dir>/generated/<date>.json`. Phase 0's A6
> resolution puts **all mutable state under `state_dir`, off the boot SD**, and
> `schedule_dir` holds **hand-authored, possibly read-only** grids. These conflict.
> **Phase 1 writes generated schedules under `state_dir/schedules/<station>/<date>.json`
> (A6 governs over §8.4's prose).** Flagged for the panel as a §8.4 doc correction.

**A7 batch/debounce — resume state.** Phase 1 persists the *daily schedule* once at
generation (cold path). The roadmap's "resume" reads that schedule back via `find_now`;
Phase 1 does **not** write per-item playhead state to disk (that would be a hot-path
write A7 forbids). Resume is reconstructed purely from `(persisted schedule, clock.now())`
— which is also exactly why cold-start == post-crash-resume (§6). If a future phase
wants a persisted playhead, A7 requires it be debounced to ≤ once per item boundary.

### 4.5 `schedule/generator.py` — §8.4 fill rule + R19 seedable

```python
"""grid + catalog -> DailySchedule (§8.4 fill rule), seedable (R19), clock-injected (R18).

Determinism contract (R19): (catalog, grid, seed, clock) -> byte-identical persisted
JSON. Achieved by (a) the catalog's stable (group, path) sort (Phase-0 scanner), (b)
a single injected random.Random seeded once, (c) no datetime.now() (clock only).
"""
from __future__ import annotations

import random
import zlib
from datetime import date, datetime, time, timedelta

from pirate_radio.catalog.scanner import Catalog
from pirate_radio.clock import Clock
from pirate_radio.config import StationConfig
from pirate_radio.schedule.grid import Grid, Slot
from pirate_radio.schedule.models import (
    BlockReminderItem, BlockTransitionItem, DailySchedule, StationIdItem, TrackItem,
)

_BLOCK_REMINDER_EVERY = timedelta(minutes=30)   # §8.4 step 3 "periodically in long slots"


def derive_seed(day: date, station: str) -> int:
    """Recommended R19 seed source: date-derived + station -> stable-but-varying days.

    Deterministic across restarts for the SAME day (so a mid-day crash regenerates the
    *same* schedule -> resume is meaningful, §6), yet different day-to-day."""
    return zlib.crc32(f"{day.isoformat()}:{station}".encode())


def generate_schedule(
    *,
    grid: Grid,
    catalog: Catalog,
    station: StationConfig,
    clock: Clock,
    seed: int,                      # recorded on DailySchedule.seed (R19 reproducibility)
) -> DailySchedule:
    rng = random.Random(seed)       # the ONLY entropy source (R19)
    day = clock.now().date()
    tz = clock.tz()
    groups = catalog.groups()                      # group -> tuple[Track] (sorted)
    silence = station.transition_silence_seconds
    window = timedelta(minutes=station.repeat_window_minutes)

    items: list = []
    recent: list[tuple[datetime, str]] = []        # (planned_start, track.path) for repeat window
    cursor = _bind(day, time(0, 0), tz)            # midnight, tz-aware

    for slot in grid.slots:
        boundary = _slot_boundary(day, slot, tz)
        pool = groups[slot.group]
        shortest = min(t.duration for t in pool)

        items.append(_transition(slot, cursor, grid, day, tz))
        cursor += timedelta(seconds=items[-1].duration + silence)

        last_id_hour: int | None = None
        last_reminder = cursor
        while (boundary - cursor).total_seconds() >= shortest:
            # §8.4.4 station_id near each top-of-hour
            if cursor.minute < 2 and cursor.hour != last_id_hour:
                items.append(StationIdItem(planned_start=cursor, duration=5.0,
                                           block_name=slot.name))
                cursor += timedelta(seconds=5.0 + silence)
                last_id_hour = cursor.hour
                continue
            # §8.4.3 block_reminder periodically in long slots
            if cursor - last_reminder >= _BLOCK_REMINDER_EVERY:
                items.append(BlockReminderItem(planned_start=cursor, duration=8.0,
                                               block_name=slot.name))
                cursor += timedelta(seconds=8.0 + silence)
                last_reminder = cursor
                continue
            # §8.4.2 weighted pick avoiding recent repeats within repeat_window_minutes
            track = _pick(pool, recent, cursor, window, rng)
            items.append(TrackItem(planned_start=cursor, duration=track.duration,
                                   block_name=slot.name, track=track))
            recent.append((cursor, str(track.path)))
            cursor += timedelta(seconds=track.duration + silence)

    return DailySchedule(date=day, station=station.name,
                         seed=seed, items=tuple(items))
```

`_pick` (the weighted, repeat-avoiding chooser — the determinism-critical core):

```python
def _pick(pool, recent, cursor, window, rng) -> Track:
    """Weighted random track from `pool`, down-weighting tracks played within `window`.

    Determinism (R19): iterate `pool` in its already-sorted order, build a weights
    list, and draw with the INJECTED rng via random.Random.choices. Same (pool, recent,
    seed) -> same pick on every machine."""
    recent_paths = {p for (start, p) in recent if cursor - start < window}
    weights = [0.05 if str(t.path) in recent_paths else 1.0 for t in pool]
    if all(w == 0.05 for w in weights):   # window covers the whole pool -> uniform
        weights = [1.0] * len(pool)
    return rng.choices(pool, weights=weights, k=1)[0]
```

Key §8.4 details captured: cursor advances by `duration + transition_silence_seconds`
for **every** element (the silence is part of timing *and* the fill calc); the loop
**stops when the remaining gap < shortest item in the pool** (soft boundaries §8.5 —
the last track may run past `boundary`); long-form tails pad from the same pool because
`_pick` keeps drawing until nothing fits.

### 4.6 `schedule/resume.py` — `find_now` (R11 gap path + R12 re-anchor)

The design's §6 `find_now` returns `(ScheduleItem | None, float)`. R11 forbids an
*undefined* `None` and R12 forbids trusting estimated `planned_start`. So Phase 1
returns a **typed result**:

```python
"""find_now: 'what airs now, at what offset' (§6) with R11 gap path + R12 re-anchor.

Cold start == post-crash resume (§6): both call find_now against the persisted
schedule with clock.now(). No persisted playhead (A7: no hot-path writes)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from pirate_radio.clock import Clock
from pirate_radio.schedule.models import DailySchedule, ScheduleItem, TrackItem


@dataclass(frozen=True)
class NowPlaying:
    """Result of find_now. Exactly one of (item playing now) or (gap before next)."""
    item: ScheduleItem | None     # the item airing now, or None if in a silence gap
    offset_seconds: float         # seek offset into `item` (0.0 when item is None)
    next_item: ScheduleItem | None  # the next item (for gap-wait / end-of-day)
    gap_seconds: float            # seconds of silence to play before `next_item` (R11)


def find_now(schedule: DailySchedule, clock: Clock, *, transition_silence: float) -> NowPlaying:
    now = clock.now()
    anchored = _reanchor(schedule, transition_silence)   # R12: rebuild starts from exact tracks
    for idx, (item, start) in enumerate(anchored):
        end = start + timedelta(seconds=item.duration)
        if start <= now < end:                            # airing now
            return NowPlaying(item, (now - start).total_seconds(), _nth(anchored, idx + 1), 0.0)
        if now < start:                                   # R11: we're in the silence gap before it
            return NowPlaying(None, 0.0, item, (start - now).total_seconds())
    return NowPlaying(None, 0.0, None, 0.0)               # past end-of-day -> caller regenerates
```

**R12 re-anchor (`_reanchor`).** Persisted `planned_start` for patter is an *estimate*
(real announcement length is unknown until synthesis). Phase 1 does **not** trust it:
`_reanchor` walks the items and recomputes each start from the **previous exact-duration
`track`** plus known silences, so drift cannot compound — the design's "re-anchor on
the nearest exact-duration track" (R12, second option). Because Phase 1's `StubTTS`
returns a *deterministic* length, the estimate and reality already coincide; re-anchor
is the mechanism that keeps it true once real TTS arrives (Phase 2), and the test
proves it by feeding a schedule whose patter durations are deliberately "wrong".

**R11 gap path made explicit.** When `now` falls in a `transition_silence` gap,
`find_now` returns `item=None` + `next_item` + `gap_seconds`. The player plays that many
seconds of silence then advances — **never undefined dead air**, and never a raw `None`
the caller must guess about.

### 4.7 `dj/protocols.py` + `dj/fakes.py` + `audio/sink.py`, `audio/decode.py`

Protocols carry R15 docstrings (units, threading via `asyncio.to_thread`, idempotency):

```python
# dj/protocols.py
from typing import Protocol, runtime_checkable
from pirate_radio.audio.buffer import AudioBuffer

@runtime_checkable
class TextGenerator(Protocol):
    """The DJ brain. `patter` returns plain text to be spoken (no SSML in v1).

    Raises ProviderError on backend failure (R15). MUST be awaitable; network impls
    do their own I/O, local impls that block MUST hop via asyncio.to_thread."""
    async def patter(self, item_kind: str, context: "DjContext | None") -> str: ...

@runtime_checkable
class TTSEngine(Protocol):
    """Text -> AudioBuffer (R14 normalized shape). Raises ProviderError (R15).
    Idempotent for identical text+config. Blocking native synths MUST use to_thread."""
    async def synthesize(self, text: str) -> AudioBuffer: ...

@runtime_checkable
class AudioSink(Protocol):
    """Play one AudioBuffer to completion, gaplessly after the previous call (§10).
    Awaiting `play` returns only when the buffer has been fully consumed."""
    async def play(self, buf: AudioBuffer) -> None: ...
```

```python
# dj/fakes.py
class NullDJ:
    """The DJ-brain floor (§9.3 / D2): produces no patter."""
    async def patter(self, item_kind: str, context=None) -> str:
        return ""

class StubTTS:
    """Phase-1 TTS stub (§20): LOGS the announcement it WOULD speak, returns a
    deterministic-length silent AudioBuffer (so timing is real, audio is silent)."""
    def __init__(self, *, words_per_minute: float = 150.0, sample_rate: int = 48_000):
        self._wpm = words_per_minute; self._sr = sample_rate
    async def synthesize(self, text: str) -> AudioBuffer:
        seconds = max(0.5, len(text.split()) / self._wpm * 60.0)
        logger.info("StubTTS would speak (%.1fs): %r", seconds, text)
        return AudioBuffer.silence(seconds=seconds, sample_rate=self._sr)

class FakeAudioSink:
    """Records every buffer + its duration; asserts gapless ordering in tests (R21)."""
    def __init__(self) -> None:
        self.played: list[AudioBuffer] = []
    async def play(self, buf: AudioBuffer) -> None:
        self.played.append(buf)
    @property
    def total_seconds(self) -> float:
        return sum(b.duration_seconds for b in self.played)
```

```python
# audio/decode.py
@runtime_checkable
class Decoder(Protocol):
    """Track file -> AudioBuffer (R14). Phase 2 = FfmpegDecoder (subprocess, to_thread)."""
    async def decode(self, track: Track) -> AudioBuffer: ...

class FakeDecoder:
    """Phase-1 decode stub: silent buffer at the track's EXACT metadata duration (§7),
    so the player's timing math is real even though the audio is silence."""
    def __init__(self, *, sample_rate: int = 48_000, channels: int = 1): ...
    async def decode(self, track: Track) -> AudioBuffer:
        return AudioBuffer.silence(seconds=track.duration,
                                   sample_rate=self._sr, channels=self._ch)
```

```python
# audio/sink.py — the ONE hardware-bound class
class SoundDeviceSink:
    """Real PortAudio output to a specific device (§10). The sounddevice call is the
    ONLY @pytest.mark.hardware code (R20); imported lazily so CI never loads PortAudio."""
    def __init__(self, device: str, *, sample_rate: int, channels: int): ...
    async def play(self, buf: AudioBuffer) -> None:  # pragma: no cover (hardware, R20)
        import sounddevice as sd
        await asyncio.to_thread(self._blocking_play, sd, buf)
```

### 4.8 `pipeline/` — look-ahead producer/consumer (R11 backstop, R21 testable)

```
pipeline/
  timing.py     # Sleeper Protocol: RealSleeper (asyncio.sleep) + VirtualSleeper (test)
  segment.py    # RenderedSegment: AudioBuffer + the source ScheduleItem
  buffer.py     # LookAheadBuffer: bounded asyncio.Queue wrapper (depth 1-2)
  producer.py   # renders items ahead -> pushes RenderedSegment into the buffer
  player.py     # drains buffer -> AudioSink; R11 backstop on missed deadline
```

`pipeline/buffer.py`:
```python
class LookAheadBuffer:
    """Bounded look-ahead queue (§5.3). Depth 1-2 is sufficient; producer blocks on a
    full queue (back-pressure), player blocks on empty (until the deadline -> R11)."""
    def __init__(self, *, maxsize: int = 2) -> None:
        self._q: asyncio.Queue[RenderedSegment] = asyncio.Queue(maxsize=maxsize)
    async def put(self, seg: RenderedSegment) -> None: await self._q.put(seg)
    async def get(self, *, timeout: float) -> RenderedSegment | None:
        try:
            return await asyncio.wait_for(self._q.get(), timeout)
        except asyncio.TimeoutError:
            return None      # signals the player to fire the R11 backstop
    @property
    def depth(self) -> int: return self._q.qsize()
```

`pipeline/producer.py`:
```python
class Producer:
    """Renders schedule items just ahead of the playhead (§5.3): item -> [TTS|decode]
    -> RenderedSegment -> buffer. A slow render stalls REFILL, never playback (§5.3)."""
    def __init__(self, *, items, tts, decoder, buffer): ...
    async def run(self) -> None:
        for item in self._items:
            buf = await self._render(item)          # may raise ProviderError
            await self._buffer.put(RenderedSegment(item=item, audio=buf))
    async def _render(self, item) -> AudioBuffer:
        if item.kind == "track":
            return await self._decoder.decode(item.track)
        return await self._tts.synthesize(self._announcement_text(item))
```

`pipeline/player.py` — **the R11 backstop**:
```python
class Player:
    """Drains the look-ahead buffer to the sink gaplessly (§5.3). If a refill misses
    its deadline, plays the canned backstop INSTEAD of dead air (R11)."""
    def __init__(self, *, buffer, sink, sleeper, clock,
                 refill_budget_seconds: float, backstop: AudioBuffer): ...
    async def run(self, *, count: int) -> None:
        for _ in range(count):
            seg = await self._buffer.get(timeout=self._refill_budget)
            if seg is None:                          # R11: refill missed deadline
                logger.warning("refill missed %.2fs budget -> backstop (R11)",
                               self._refill_budget)
                await self._sink.play(self._backstop)  # canned audio, NOT dead air
                continue
            await self._sink.play(seg.audio)
            if self._silence > 0:                    # §10 transition silence between elements
                await self._sink.play(AudioBuffer.silence(seconds=self._silence, ...))
```
The R11 "worst-case refill budget" is `refill_budget_seconds` (config-derived later);
the player fires the backstop the instant `buffer.get` times out — proven in tests with
a deliberately slow producer + virtual time (no wall-clock sleep).

### 4.9 `config.py` (extend) — `state_dir` (A6)

```python
# StationConfig OR DaemonConfig gains:  (A6 places ALL mutable state off the boot SD)
class DaemonConfig(BaseModel):
    ...
    state_dir: Path     # mutable state root (schedules, future resume/catalog cache)
```
Validation in `_validate_config` (A6: exists + **writable**, not just `is_dir`):
```python
def _check_state_dir(config: DaemonConfig) -> None:
    sd = config.state_dir
    if not sd.is_dir():
        raise ConfigError(f"state_dir missing or not a directory: {sd}")
    if not os.access(sd, os.W_OK):
        raise ConfigError(f"state_dir is not writable: {sd}")
    logger.info("state_dir resolved to %s", sd)   # A6: log where writes land
```
A6 also asks the writability check be applied to `content_dir`/`schedule_dir`; Phase 1
adds `os.access(..., os.W_OK)` is **not** required for those (read-only grids/library
are valid) — only `state_dir` must be writable. Flag for panel: A6 says "apply
writability to all three"; we read it as "state_dir writable; the other two readable".

---

## 5. Cross-Cutting Concerns

- **Immutability.** Every model frozen (`ConfigDict(frozen=True)` / `@dataclass(frozen=True)`).
  Generator builds a local `list` then freezes into a `tuple` on the `DailySchedule` —
  no caller ever mutates a schedule.
- **Injectable clock (R18).** `clock.Clock` is threaded into `generate_schedule` and
  `find_now`. **No `datetime.now()` anywhere outside `clock.py`** — preserved from
  Phase 0. `derive_seed` takes `day` (from the clock), never reads the clock itself.
- **Seedable RNG (R19).** A single injected `random.Random` is the only entropy source
  in the generator; combined with the catalog's stable sort, `(catalog+grid+seed+clock)
  → byte-identical persisted JSON`. The seed is recorded in `DailySchedule.seed`.
- **Asyncio discipline (R21).** Pipeline is pure asyncio; **zero wall-clock sleeps in
  tests** via the `Sleeper` seam and a virtual clock. Bounded queue = back-pressure.
  Any blocking native call (real decode/sink, Phase 2+) goes through `asyncio.to_thread`
  — documented in the Protocol docstrings (R15).
- **R15 error taxonomy.** `ProviderError` subtree lands in `errors.py` under the
  existing `PirateRadioError` root; the pipeline catches `ProviderError` and fires the
  R11 backstop. The retryable-branch *failover wrapper* is deferred to Phase 3.
- **No bare dicts (R16).** `ScheduleItem` union (R17), `NowPlaying` dataclass,
  `RenderedSegment` dataclass, `AudioBuffer` dataclass. The only `dict` is the catalog's
  internal `groups()` lookup (Phase 0, value-derived). `dj_context` stays out of Phase 1.
- **Fail-fast.** `AudioBuffer.__post_init__` validates shape/dtype; `find_now` rejects
  naive datetimes via the model validator; `state_dir` validated at config load.
- **Small files.** Each pipeline concern is its own <150-line module (style rule).

---

## 6. Per-Module TDD Test Plan

Strict spec-driven TDD: RED tests first, then GREEN. Mirrors Phase 0's
`tests/<area>/test_<module>.py` layout. Reuses Phase-0 fixtures (`content_tree`,
`grid_yaml`, `fixed_clock`, `make_wav`). Coverage: **package-wide `--cov-fail-under=80`
stays honest** — the only `pragma: no cover` is `SoundDeviceSink.play` (R20); everything
else (generator, find_now, buffer, pipeline) is pure and fully covered.

### 6.1 `tests/audio/test_buffer.py`
- `silence()` yields exact frame count (`round(seconds*sr)`), float32, shape `(n,1)`.
- `duration_seconds` round-trips; rejects 1-D arrays, wrong dtype, sr<=0, channel
  mismatch (one RED test each).

### 6.2 `tests/schedule/test_models.py`
- `TrackItem` requires a `Track`; constructing `track` kind without one raises.
- Discriminator routes `{"kind":"block_transition", ...}` → `BlockTransitionItem`.
- `planned_start` naive datetime rejected; `DailySchedule` round-trips through
  `model_dump(mode="json")` → `model_validate` unchanged.

### 6.3 `tests/schedule/test_generator.py` — **R19 determinism is the headline test**
```python
def test_seeded_generation_is_byte_identical(content_tree, grid_yaml, fixed_clock):
    catalog = scan_catalog(content_tree)
    grid = load_grid(grid_yaml / "default.yaml")
    station = _station(content_tree, grid_yaml)
    a = generate_schedule(grid=grid, catalog=catalog, station=station,
                          clock=fixed_clock, seed=1234)
    b = generate_schedule(grid=grid, catalog=catalog, station=station,
                          clock=fixed_clock, seed=1234)
    assert a.model_dump_json() == b.model_dump_json()        # R19: byte-identical

def test_different_seed_differs(...):    # seed=1 vs seed=2 -> different order
def test_slots_tile_and_silence_in_timing(...):
    # every cursor advance == duration + transition_silence; last track may pass boundary
def test_stops_when_gap_below_shortest(...):   # §8.4 stop rule (soft boundary §8.5)
def test_avoids_recent_repeats_within_window(...):  # repeat_window_minutes honored
def test_block_transition_at_each_slot_boundary(...)
def test_station_id_near_top_of_hour(...)
def test_block_reminder_in_long_slot(...)
```

### 6.4 `tests/schedule/test_resume.py` — R11 gap path + R12 re-anchor
- `find_now` mid-track returns the item + correct offset (the §6 example).
- **R11:** `now` inside a transition-silence gap → `item is None`, `next_item` set,
  `gap_seconds > 0` (never undefined dead air).
- `now` past end-of-day → all `None` (caller regenerates).
- **R12:** schedule whose persisted patter `planned_start`s are deliberately drifted;
  assert `find_now` re-anchors on the nearest exact `track` so the airing item is
  correct despite the bad estimates.
- save → load round-trip via `persistence.py`; corrupted file falls back to `.bak`
  (reuses R6 behavior).

### 6.5 `tests/dj/test_fakes.py`
- `StubTTS.synthesize` logs (`caplog`) the would-speak text and returns a silent buffer
  whose duration scales with word count.
- `NullDJ.patter` returns `""`. `FakeAudioSink` records buffers; `total_seconds` sums.
- `FakeDecoder.decode` returns a buffer of exactly `track.duration`.

### 6.6 `tests/pipeline/test_pipeline.py` — **R21 virtual-time tests (the core proof)**
All `async def`, `Sleeper`=virtual, `clock`=`FixedClock`, **no wall-clock sleeps**:
```python
async def test_gapless_ordering(...):
    # producer renders 5 items, player drains; FakeAudioSink.played order == schedule
    # order; total_seconds == sum(durations) + silences -> gapless, no dead air.

async def test_bounded_queue_depth(...):
    # with maxsize=2, assert buffer.depth never exceeds 2 (back-pressure on producer).

async def test_slow_producer_fires_backstop_not_dead_air(...):
    # producer delayed past refill budget (virtual time) -> player plays the CANNED
    # backstop buffer (R11), NOT silence/dead air; assert backstop in FakeAudioSink.played.

async def test_producer_error_triggers_backstop(...):
    # FailingTTS raises ProviderUnavailable -> producer render fails -> backstop fires.

async def test_stall_isolation(...):
    # a stalled render does not corrupt ordering of already-buffered segments.
```
Ship in-repo `FailingTTS` / `FailingDecoder` (R20) raising `ProviderError` subtypes.

### 6.7 `tests/pipeline/test_run_once.py` — end-to-end slice (CI, no hardware)
A thin `run_once(schedule, sink, ...)` harness wires generator→find_now→producer→player
against `FakeAudioSink` for one day's first N items, proving the **full vertical slice**
(generate → persist → resume → render → play gaplessly) with zero hardware.

### 6.8 `tests/config/test_state_dir.py`
- valid writable `state_dir` passes; missing → `ConfigError`; read-only (chmod 0o555)
  → `ConfigError` (writability, A6); resolved path logged (`caplog`).

### 6.9 Hardware (deferred, not in CI floor)
- `tests/audio/test_sink_hardware.py` — `@pytest.mark.hardware`, single smoke test
  that `SoundDeviceSink.play` emits a 0.1s tone to a named device. CI runs
  `-m "not hardware"`; `play` is `pragma: no cover`. **80% package floor unaffected.**

---

## 7. TDD Implementation Order (dependency-sorted)

Each step imports only previously-built modules (mirrors Phase 0's discipline).

1. **`errors.py` extension** — `ProviderError` subtree (no deps). RED → GREEN.
2. **`audio/buffer.py`** — `AudioBuffer` (deps: numpy). Headline shape/validation tests.
3. **`schedule/models.py`** — `ScheduleItem` union + `DailySchedule` (deps: catalog `Track`).
4. **`schedule/generator.py`** — fill rule + seedable RNG (deps: grid, catalog, config,
   models, clock). **R19 determinism test is the gate.**
5. **`schedule/resume.py`** — `find_now` + save/load (deps: models, persistence, clock).
   R11 + R12 tests.
6. **`dj/protocols.py` + `audio/decode.py` (Protocols)** — pure interfaces (deps: buffer).
7. **`dj/fakes.py` + `FakeDecoder` + `FakeAudioSink`** — (deps: protocols, buffer, errors).
8. **`pipeline/timing.py` + `pipeline/segment.py` + `pipeline/buffer.py`** — (deps: buffer).
9. **`pipeline/producer.py`** — (deps: buffer, fakes, models).
10. **`pipeline/player.py`** — R11 backstop (deps: buffer, sink, timing, clock).
11. **`audio/sink.py` `SoundDeviceSink`** — hardware seam, lazy import, `pragma: no cover`.
12. **`config.py` `state_dir`** — A6 (can land in parallel with 1–2; gates step 5's path).
13. **`pipeline/test_run_once.py` harness** — the full-slice integration proof.

> `catalog/cache.py` (A9 mtime-cached rescan) slots in after step 3 as an independent
> wrapper over `scan_catalog`; not on the critical path for the timing proof.

---

## 8. PR-Sized Task Breakdown

| PR | Scope | Acceptance criteria |
|---|---|---|
| **P1-1** | `errors.py` ProviderError subtree + `audio/buffer.py` + numpy dep | All buffer shape/dtype/validation tests green; `ProviderError` subtypes importable; coverage 100% on both |
| **P1-2** | `schedule/models.py` (R17 union + `DailySchedule`) | Discriminator routing + tz-aware + JSON round-trip tests green |
| **P1-3** | `config.py` `state_dir` (A6) | Missing/non-writable → `ConfigError`; valid passes; path logged |
| **P1-4** | `schedule/generator.py` (§8.4 + R19) | **(catalog+grid+seed+clock)→byte-identical JSON**; stop-rule, repeat-window, transition/id/reminder emission all green |
| **P1-5** | `schedule/resume.py` (`find_now` R11+R12, save/load) | mid-track offset; gap→None+next+gap_seconds; re-anchor on exact track; `.bak` recovery |
| **P1-6** | `dj/protocols.py`, `dj/fakes.py`, `audio/decode.py`, `audio/sink.py` | StubTTS logs+silent buffer; NullDJ empty; FakeDecoder exact duration; FakeAudioSink records; SoundDeviceSink imports without `sounddevice` |
| **P1-7** | `pipeline/` (timing, segment, buffer, producer, player) + pytest-asyncio | Virtual-time: gapless ordering, bounded depth ≤2, slow-producer→backstop (not dead air), ProviderError→backstop, stall isolation |
| **P1-8** | `run_once` harness + `catalog/cache.py` (A9) + hardware smoke (`@pytest.mark.hardware`) | Full slice green in CI (`-m "not hardware"`); package `--cov-fail-under=80` holds; cache returns same `Catalog` until mtime changes |

Each PR is TDD (RED tests committed first), passes `ruff` + `mypy --strict` (matching
Phase-0 config), and ends with a `docs/decisions/000X-phase1-tests-<area>.md` mirroring
the Phase-0 test-decision record cadence.

---

## 9. Open Questions & Risks for the Panel

1. **§8.4 path vs A6 `state_dir` (resolved here, needs ratification).** §8.4 says
   `<schedule_dir>/generated/<date>.json`; A6 mandates all mutable state under
   `state_dir` off the boot SD, with `schedule_dir` holding (possibly read-only)
   hand-authored grids. This plan writes generated schedules to
   `state_dir/schedules/<station>/<date>.json`. **Confirm A6 governs §8.4's prose.**

2. **R12 re-anchor strategy.** This plan re-anchors `find_now` on the nearest exact
   `track` (R12's *second* option) rather than pulling the hourly station-ID re-anchor
   into v1 (R12's *first* option). Given Phase 1's `StubTTS` is deterministic, the
   distinction is invisible until Phase 2 real TTS — but the choice shapes
   `find_now`'s contract now. **Is exact-track re-anchor the right v1 commitment, or
   should the hourly-ID re-anchor be specified now to avoid a `find_now` rewrite in
   Phase 2?**

3. **R11 "worst-case refill budget" derivation.** The player fires the backstop on a
   `refill_budget_seconds` timeout, but Phase 1 has no real render-latency data (StubTTS
   is instant, FakeDecoder is instant). **Should the budget be a fixed config default
   for now (e.g. derived from look-ahead depth × an assumed per-item render ceiling),
   or does the panel want a Phase-1 latency-measurement spike to set it empirically
   before Phase 2 adds real TTS/decode?** Related: should the "deeper/warm buffer at
   block boundaries" (R11) be implemented now or deferred with the budget?

Secondary risks (noted, mitigated): numpy float32 silence buffers are cheap but a full
day rendered ahead would be huge — mitigated by depth-1–2 look-ahead (only ~2 segments
in RAM); `pytest-asyncio` `auto` mode interaction with the existing sync suite —
mitigated by per-test `async def` only in `tests/pipeline/`; `bumper` kind + `dj_context`
omission means a `SCHEMA_VERSION` bump in Phase 3 — acceptable, the envelope (R17)
exists precisely for this.
```

---

## Review Amendments (Rev 1 — adopted 6 AYE / 0 NAY, 1 abstain)

Full record: `docs/decisions/0009-phase1-plan-review-rev1.md`. **Where these conflict
with the plan body above, this section governs.**

### Open questions resolved
- **Q1 — `state_dir` (A6) governs.** Generated schedules → `state_dir/schedules/<station>/<date>.json` (NOT `schedule_dir/generated/`; §8.4 prose corrected). A6 writability ratified-narrowed: `state_dir` writable; `content_dir`/`schedule_dir` read-only OK. Config logs the device/mount `state_dir` resolves to.
- **Q2 — Exact-track re-anchor** (not hourly-ID). Freeze the `find_now`/`NowPlaying` contract now; document that Phase 2 re-synthesizes patter durations (not persisted estimates).
- **Q3 — Fixed config-derived `refill_budget_seconds`**; no measurement spike now (instant fakes); empirical calibration + warm/deeper-boundary buffer deferred to Phase 2.

### Must-fix before GREEN
- **P1** Player must NOT drop the slow item on backstop — decouple gap-fill from item-advance; the real segment still plays. Test: ordering `[…, backstop, real-item, …]`, played-real-count == item-count, zero lost.
- **P2** Backstop deadline via the injected `Sleeper`/`Clock` seam (race `queue.get()` vs `sleeper.sleep(budget)`), NOT `asyncio.wait_for`. Specify the virtual-time contract (single loop, Sleeper as sole time-advancer, producer-wakeup composition) and ship it with `pipeline/timing.py` before P1-7 tests.
- **P3** Generator `_slot_boundary` rolls `time(0,0)` → next-day midnight (else the final block emits zero tracks); RED test that the PM block fills.
- **P4** Gaplessness tested as ordered sequence + no-backstop WARNING, not a duration sum.
- **P5** R19 determinism tested on persisted on-disk bytes + a committed golden JSON + save→load→regenerate round-trip.
- **P6** `find_now`×re-anchor parametrized `now`-sweep (mid-track/exact-start/in-gap/past-end) after a non-trivial re-anchor; R12 test feeds genuinely-offset `planned_start`s and asserts the re-anchored item differs from the naive one.
- **P7** Scope the pipeline `ProviderError` catch as provisional with a `producer.py` TODO (Phase 3 branches `ProviderFatal` vs retryable).

### Hardening (adopt)
H1 name generator magic numbers as constants/config · H2 document `repeat_window` soft-down-weight semantics · H3 typed error (not KeyError) on missing group pool · H4 anchor the timeline once at load + binary-search `find_now` · H5 one shared sample-rate constant · H6 dispatch on `ScheduleItem` variant type + player ordering-invariant assert · H7 whole-track-buffer → Phase-2 streaming/chunk + R128 reconciliation note · H8 numpy 64-bit arm64 Bookworm pin · H9 A9 mtime invalidation granularity documented · H10 state Phase 1 is NOT a deployable radio (name the regen/crash-restart phase) · H11 backstop-exhaustion counting/escalation · H12 missing-content-file-at-airtime → backstop-not-crash contract · H13 record `NowPlaying` as a §6 design-doc correction.

Per-module ≥90% coverage on real-logic modules (generator/resume/buffer/producer/player) in PR acceptance; only `SoundDeviceSink.play` is `@pytest.mark.hardware`.
