# PiRate Radio — Phase 0 Implementation Plan

> **Status:** For review-panel critique.
> **Author:** Implementation planner.
> **Governing sources:** `PiRate_Radio_Design_Doc.md` (esp. §7, §8, §12, §13, §19, §20, and **§21 "Review Resolutions" which GOVERNS on conflict**), plus `docs/decisions/0001-design-review-rev1.md` and `0002-design-review-rev2.md` (R5–R23, D1–D6, F1).
> **Bar:** detailed enough to implement via TDD with no further design decisions; concrete enough that reviewers can attack specific code.

---

## 1. Scope & Non-Scope

### 1.1 In scope (Phase 0 — "Skeleton", §20)

Phase 0 delivers the **pure, deterministic, hardware-free foundation** every later phase builds on:

1. **Cross-cutting seams** that §21 requires the data/config modules to depend on:
   - `errors.py` — Phase-0 exception hierarchy (config, grid-validation, catalog, state-corruption).
   - `clock.py` — injectable `Clock` Protocol + `SystemClock` (tz-aware, system local zone per **D6**) + `FixedClock` for tests (**R18**).
   - `persistence.py` — generic atomic durable JSON save/load over Pydantic models with `.bak` recovery and a `schema_version` envelope (**R5, R6, R17**).
2. **Catalog** (§7, §13):
   - `catalog/models.py` — the `Track` model.
   - `catalog/metadata.py` — `mutagen`-based tag reads, best-effort on sparse/corrupt files (**§9.3**).
   - `catalog/scanner.py` — walk `content_dir`, one group per top-level subfolder, build an in-memory `Catalog` index; deterministic ordering; skip+log unreadable files.
3. **Grid loading + validation** (§8.2, §8.3, §13):
   - `schedule/grid.py` — `Slot`/`Grid` Pydantic models, YAML loader, day-of-week grid **resolution**, and **fail-fast** validation (contiguous tiling 00:00→24:00, `start < end`, group→non-empty-folder, `name` required).
4. **Config + validation** (§12, §13):
   - `config.py` — Pydantic v2 models with **discriminated unions** for TTS and LLM provider configs (**R16**), `StationConfig`, `DaemonConfig`, `config.json` loader, and **all** §12 fail-fast checks including the **R10** stable-audio-device-name validation **seam**.

### 1.2 Explicitly OUT of scope (deferred to later phases)

| Deferred item | Phase | Why deferred |
|---|---|---|
| Daily schedule **generation** (fill rule, transition silence, seedable RNG) | 1 | §20 Phase 1; needs the catalog+grid this phase builds first. The `schedule/generator.py` and `schedule/models.py` (`ScheduleItem`/`DailySchedule`) are **not** written here. |
| `find_now` / resume seek logic (`schedule/resume.py`) | 1 | Depends on `DailySchedule`. |
| Producer / player / look-ahead buffer (`pipeline/`) | 1+ | No audio in Phase 0. |
| Audio decode / `sounddevice` sink / loudness (`audio/`) | 1–2 | The **only** `@pytest.mark.hardware` code lives here (R20); Phase 0 has none. |
| `AudioBuffer` model (R14) | 1 | First needed by the pipeline; no consumer exists in Phase 0. |
| TTS / LLM **engine implementations** + failover (`dj/`) | 2–3 | Phase 0 only models their **config**, never instantiates a backend or imports an SDK. |
| Provider error taxonomy (`ProviderError`/`ProviderUnavailable`/…) — **R15** | 3 | Belongs with the failover wrapper. Phase-0 `errors.py` keeps a **clean base** so R15 grafts on cleanly (see §4.1). |
| Seedable scheduler determinism — **R19** | 1 | The generator is Phase 1; Phase 0 ships no RNG. |
| Coordinator / supervisor / systemd unit — **R7** | 1+ | No long-running process in Phase 0. |
| FastAPI control plane + `GET /logs` — **D4, R8′, R23** | post-Phase-1 | §21/D4 lands it after the MVP slice. |
| DST-fold policy — **R9** residual | 1 | Only matters once `find_now` seeks against wall-clock; Phase 0 establishes tz-awareness so the policy has somewhere to live. |
| Offline tagging tool (`tools/tag_library.py`) | 5 | Standalone, not a runtime dep. |

**Phase 0 imports no audio, RF, network, or LLM/TTS SDK.** Everything is pure Python + Pydantic + mutagen + a YAML reader, and **everything is CI-runnable with zero `@pytest.mark.hardware` tests.**

---

## 2. Which §21 Resolutions Phase 0 Implements

| Resolution | Phase 0 implementation | Module |
|---|---|---|
| **R5** atomic durable writes (temp → fsync → `os.replace` → fsync dir, `.bak`) | Fully implemented as the generic persistence primitive. | `persistence.py` |
| **R6** corruption recovery, no crash-loop (validate → `.bak` → regenerate signal) | Fully implemented in `load_with_recovery`. | `persistence.py` |
| **R10** stable USB audio device naming validation | Implemented as a **mockable resolver seam** (`AudioDeviceResolver` Protocol) validated at config load; the real udev/ALSA lookup is injected, so CI uses a fake. | `config.py` + `audio_devices.py` |
| **R16** no bare dicts; discriminated unions keyed on `backend` | TTS configs (`Piper`/`Espeak`/`ElevenLabs`) and LLM configs (`Claude`/`DeepSeek`/`Ollama`) as `Annotated[Union, Field(discriminator="backend")]`. | `config.py` |
| **R17** `schema_version` envelope on persisted models | The persistence envelope carries `schema_version`; load rejects/upgrades on mismatch. (The `ScheduleItem` union itself is Phase 1, but the envelope mechanism it relies on ships now.) | `persistence.py` |
| **R18** injectable clock; never call `datetime.now()` internally | `Clock` Protocol + `SystemClock` + `FixedClock`. | `clock.py` |
| **D6** system local timezone, trust OS clock, tz-aware datetimes | `SystemClock.now()` returns `datetime.now(tz=...)` with the resolved local zone; no RTC/NTP defensive code. | `clock.py` |

### 2.1 Resolutions deliberately deferred (with reason)

- **R15 (provider error taxonomy)** → Phase 3. It is the failover contract; introducing it now with no failover code to consume it would be speculative generality (Old Man's concern). Phase-0 `errors.py` keeps `PirateRadioError` as a clean root so R15's `ProviderError(PirateRadioError)` subtree attaches with zero churn.
- **R19 (seedable scheduler)** → Phase 1, with the generator.
- **R11/R12 (never-dead-air backstop, drift bound)** → Phase 1, with `find_now`/player.
- **R14 (`AudioBuffer`)** → Phase 1, with the pipeline.
- **R7 (systemd/supervisor)**, **R8′ (logging+/logs)**, **R23 (non-blocking handlers)**, **D4 (API)** → post-Phase-1.
- **R9 residual (DST-fold policy)** → Phase 1. Phase 0 only guarantees datetimes are tz-aware so the fold policy is *expressible*.

---

## 3. New Dependencies (`pyproject.toml`)

Add to `[project].dependencies`:

```toml
dependencies = [
    "pydantic>=2.7,<3",   # R16/R17: typed models, discriminated unions, fail-fast validation
    "mutagen>=1.47",      # §7: tag reads (ID3/Vorbis/MP4/FLAC), pure-Python, no ffmpeg needed for tags
    "PyYAML>=6.0",        # §8.2: read hand-authored grid YAML
]
```

Add to `[project.optional-dependencies].dev`:

```toml
    "types-PyYAML>=6.0",  # mypy stubs for PyYAML (yaml has no inline types)
```

**No audio/RF/network/LLM/TTS deps yet** (no `sounddevice`, `numpy`, `pyloudnorm`, `ffmpeg` wrappers, no SDKs). Those land with the phases that use them (R22).

### 3.1 YAML library choice: **PyYAML** (not ruamel.yaml) — justification

- Phase 0 only **reads** hand-authored grids; it never **round-trips** (read → mutate → re-serialize preserving comments). ruamel.yaml's headline advantage (comment/format-preserving round-trip) is therefore unused.
- PyYAML is the smaller, more ubiquitous dependency; `types-PyYAML` gives clean mypy coverage.
- We will call **`yaml.safe_load`** exclusively (never `yaml.load` / `FullLoader`) so a hand-authored or tampered grid cannot execute arbitrary Python tags — a boundary-validation requirement (coding-style "never trust file content").
- Generated schedule artifacts (Phase 1, §8.4) are **JSON**, not YAML, so there is no future YAML-writing need that would justify ruamel now.
- **Open question for the panel** (see §9): if hand-authored grids should one day be machine-edited with comments preserved, revisit ruamel. Recorded, not blocking.

---

## 4. Module-by-Module Design

All models are **frozen** (`model_config = ConfigDict(frozen=True)`) per the immutability rule; updates use `model_copy(update=...)`. All datetimes are **tz-aware** (D6). Files stay < 400 lines; the larger modules (`config.py`, `grid.py`) are split as noted.

Final Phase-0 tree under `src/pirate_radio/`:

```
pirate_radio/
  errors.py
  clock.py
  persistence.py
  audio_devices.py        # R10 resolver seam (config depends on it)
  config.py
  catalog/
    __init__.py
    models.py             # Track
    metadata.py           # mutagen reads
    scanner.py            # folder scan → Catalog
  schedule/
    __init__.py
    grid.py               # Slot/Grid models + YAML loader + resolution + validation
```

(`schedule/generator.py`, `schedule/models.py`, `schedule/resume.py`, `pipeline/`, `audio/`, `dj/`, `control/`, `coordinator.py`, `supervisor.py`, `station.py`, `logging.py` are **created in later phases** — left absent now to avoid empty stubs.)

---

### 4.1 `errors.py` — Phase-0 exception hierarchy

**Single responsibility:** a clean, flat exception tree for the failure classes Phase 0 can raise, with a single project root so later taxonomies (R15) graft on cleanly.

```python
"""Phase-0 exception hierarchy for PiRate Radio.

A single project root (`PirateRadioError`) lets callers catch everything from the
package with one `except`. Phase-0 leaf types cover the four failure classes this
phase can raise: config, grid validation, catalog scanning, and persisted-state
corruption. The provider/failover taxonomy (R15: ProviderError ->
ProviderUnavailable/ProviderQuotaExceeded/ProviderFatal) is intentionally NOT here
yet — it is Phase 3 and will attach under PirateRadioError without disturbing these.
"""

from __future__ import annotations

from pathlib import Path


class PirateRadioError(Exception):
    """Root of every error raised by PiRate Radio."""


class ConfigError(PirateRadioError):
    """config.json is missing, malformed, or fails fail-fast validation (§12)."""


class GridValidationError(PirateRadioError):
    """A grid file is missing, malformed, or violates §8.3 validation rules."""


class GridResolutionError(PirateRadioError):
    """No applicable grid file could be resolved for a station/day (§8.2)."""


class CatalogError(PirateRadioError):
    """The content directory cannot be scanned (missing root, no groups, etc.)."""


class StateCorruptionError(PirateRadioError):
    """Persisted state and its .bak are both unreadable/invalid (R6 last resort).

    Carries the offending path so the caller can decide to regenerate. Raising this
    is the explicit *signal* that recovery via .bak failed and the caller must
    regenerate from source — it is NOT a crash-loop trigger (R6).
    """

    def __init__(self, message: str, *, path: Path) -> None:
        super().__init__(message)
        self.path = path
```

**Key logic:** validators raise the *most specific* leaf; all carry actionable, non-secret-leaking messages (security rule). `StateCorruptionError` is the only one carrying structured data (the path), because R6 recovery branches on it.

---

### 4.2 `clock.py` — injectable clock (R18, D6)

**Single responsibility:** the only source of "now" in the codebase. Nothing else calls `datetime.now()`.

```python
"""Injectable clock (R18) using the system local timezone (D6).

Every time-dependent unit takes a Clock; production wires SystemClock, tests wire
FixedClock. No module anywhere else may call datetime.now() directly — enforced by
review and a ruff/grep gate (see test plan).
"""

from __future__ import annotations

from datetime import datetime, tzinfo
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo


@runtime_checkable
class Clock(Protocol):
    """A source of the current tz-aware wall-clock time.

    Implementations MUST return timezone-aware datetimes (D6 keeps zoneinfo in
    charge of DST). Returning a naive datetime is a contract violation.
    """

    def now(self) -> datetime:
        """Return the current instant as a tz-aware datetime."""
        ...

    def tz(self) -> tzinfo:
        """Return the timezone this clock reports in."""
        ...


class SystemClock:
    """Clock backed by the OS clock and the system local timezone (D6).

    Trusts the OS clock; no RTC/NTP-step defensive logic (D6). The local zone is
    resolved once at construction. Pass an explicit zone for reproducible tests or
    multi-tz deployments; otherwise the process local zone is used.
    """

    def __init__(self, zone: tzinfo | None = None) -> None:
        self._tz: tzinfo = zone if zone is not None else _resolve_local_zone()

    def now(self) -> datetime:
        return datetime.now(tz=self._tz)

    def tz(self) -> tzinfo:
        return self._tz


class FixedClock:
    """Deterministic Clock for tests. Advances only when told.

    The provided instant MUST be tz-aware; a naive datetime raises ValueError so a
    test can never accidentally assert against a naive time.
    """

    def __init__(self, instant: datetime) -> None:
        if instant.tzinfo is None:
            raise ValueError("FixedClock requires a tz-aware datetime")
        self._instant = instant

    def now(self) -> datetime:
        return self._instant

    def tz(self) -> tzinfo:
        assert self._instant.tzinfo is not None  # guaranteed by __init__
        return self._instant.tzinfo

    def set(self, instant: datetime) -> "FixedClock":
        """Return a new FixedClock at `instant` (immutable update)."""
        return FixedClock(instant)


def _resolve_local_zone() -> tzinfo:
    """Resolve the system local IANA zone, falling back to the fixed UTC offset.

    `datetime.now().astimezone()` attaches the OS-configured local zone. We extract
    a concrete tzinfo from it so SystemClock.tz() is stable for the process.
    """
    local = datetime.now().astimezone().tzinfo
    if local is None:  # pragma: no cover - astimezone always attaches a zone
        return ZoneInfo("UTC")
    return local
```

**Why a `tz()` method:** `find_now`, grid `time`→`datetime` binding, and midnight regen (all Phase 1) need to *construct* tz-aware datetimes in the same zone the clock reports, so the zone must be queryable, not just "now".

---

### 4.3 `persistence.py` — atomic durable JSON over Pydantic models (R5, R6, R17)

**Single responsibility:** safely write/read any frozen Pydantic model to a single JSON file with durability and corruption recovery. Generic — the catalog cache, and (Phase 1) daily schedules and resume state, all go through it.

**Envelope (R17):** every file is `{"schema_version": int, "payload": <model json>}`. Loading checks `schema_version` before validating the payload.

```python
"""Atomic, durable, recoverable JSON persistence for Pydantic models.

Implements R5 (temp -> fsync -> os.replace -> fsync parent dir, with .bak
last-known-good), R6 (validate -> fall back to .bak -> raise StateCorruptionError
so the caller regenerates; never crash-loop), and R17 (a schema_version envelope).

Generic over a single Pydantic model type. No domain knowledge lives here.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from pirate_radio.errors import StateCorruptionError

M = TypeVar("M", bound=BaseModel)

_ENVELOPE_KEY_VERSION = "schema_version"
_ENVELOPE_KEY_PAYLOAD = "payload"


def atomic_write_json(path: Path, model: BaseModel, *, schema_version: int) -> None:
    """Durably write `model` to `path` inside a versioned envelope (R5, R17).

    Sequence: rotate existing file to <path>.bak, write a temp file in the same
    directory, fsync it, os.replace() it into place (atomic on POSIX), then fsync
    the parent directory so the rename itself survives a power loss.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    envelope = {
        _ENVELOPE_KEY_VERSION: schema_version,
        _ENVELOPE_KEY_PAYLOAD: model.model_dump(mode="json"),
    }
    data = json.dumps(envelope, indent=2, sort_keys=True).encode("utf-8")

    # Keep a last-known-good copy before we touch the live file.
    if path.exists():
        _replace_keep_bak(path)

    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)  # atomic rename
        _fsync_dir(path.parent)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def load_with_recovery(path: Path, model_type: type[M], *, schema_version: int) -> M:
    """Load and validate `path`; on failure fall back to <path>.bak (R6).

    Raises StateCorruptionError (carrying `path`) when neither the live file nor the
    .bak validate — the caller treats that as "regenerate from source", never as a
    reason to crash-loop.
    """
    last_error: Exception | None = None
    for candidate in (path, path.with_suffix(path.suffix + ".bak")):
        if not candidate.exists():
            continue
        try:
            return _load_one(candidate, model_type, schema_version)
        except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_error = exc
            continue
    raise StateCorruptionError(
        f"no valid state at {path} or its .bak: {last_error}", path=path
    )


def _load_one(path: Path, model_type: type[M], schema_version: int) -> M:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or _ENVELOPE_KEY_PAYLOAD not in raw:
        raise ValueError(f"{path} is not a versioned persistence envelope")
    found = raw.get(_ENVELOPE_KEY_VERSION)
    if found != schema_version:
        # Phase 0: refuse unknown versions. Migration hooks arrive when a v2 exists.
        raise ValueError(
            f"{path} schema_version {found!r} != expected {schema_version}"
        )
    return model_type.model_validate(raw[_ENVELOPE_KEY_PAYLOAD])


def _replace_keep_bak(path: Path) -> None:
    """Copy current live file to <path>.bak atomically-ish before overwrite."""
    bak = path.with_suffix(path.suffix + ".bak")
    data = path.read_bytes()
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.bak.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, bak)
        _fsync_dir(path.parent)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _fsync_dir(directory: Path) -> None:
    """fsync a directory so a rename within it is durable (R5)."""
    dir_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
```

**Key decisions / attack surface for reviewers:**
- `model_dump(mode="json")` makes `Path`, `time`, `datetime` JSON-native; round-trip uses `model_validate`. Frozen models round-trip cleanly.
- `_replace_keep_bak` copies the *old* good file to `.bak` **before** writing the new one, so a crash mid-new-write leaves a valid `.bak`. (Alternative: rename old→bak then write new — but rename loses the live file if the new write then fails before replace; copy-then-replace is safer. **Reviewers: critique this ordering.**)
- Directory fsync is best-effort POSIX; on a filesystem where `O_RDONLY` dir fsync is unsupported it would raise `OSError` — acceptable to surface loudly on the target Linux/Pi.
- `schema_version` mismatch raises `ValueError`, which `load_with_recovery` treats as corruption → `.bak` → regenerate. **Reviewers: is "refuse unknown version" correct vs "attempt migration"? Phase 0 has only v1, so refuse is defensible.**

---

### 4.4 `catalog/models.py` — `Track` (§13)

```python
"""The Track model (§13): one playable file, tagged by its parent group folder."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class Track(BaseModel):
    """A single audio file indexed by the catalog scanner.

    `duration` comes from metadata and is treated as exact for scheduling (§7).
    Tag fields are optional: a sparsely tagged file is indexed best-effort, never
    skipped (§9.3).
    """

    model_config = ConfigDict(frozen=True)

    path: Path
    group: str = Field(min_length=1)  # parent folder name
    duration: float = Field(gt=0.0)   # seconds; a 0/negative duration is unplayable
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    year: int | None = Field(default=None, ge=0, le=9999)
```

**Note:** `duration` is `gt=0` — a file whose metadata yields a non-positive duration is treated as a *read failure* by the scanner (logged + skipped), not stored as a degenerate Track. This is the one place "best-effort tags" does not apply, because a zero-length track breaks scheduling math.

---

### 4.5 `catalog/metadata.py` — mutagen reads, best-effort (§7, §9.3)

**Single responsibility:** turn one file path into raw metadata (duration + tags) or a structured "unreadable" signal. No filesystem walking here.

```python
"""Best-effort metadata extraction via mutagen (§7), tolerant of sparse tags (§9.3).

Returns a TrackMetadata for any file mutagen can open and that yields a positive
duration; returns None (so the caller can skip+log) for unreadable/corrupt files or
files with no usable duration. Never raises on a bad file — bad input is data, not
an exception (boundary-validation rule).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict
import mutagen


class TrackMetadata(BaseModel):
    """Raw, normalized metadata for one file. duration is required and > 0."""

    model_config = ConfigDict(frozen=True)

    duration: float
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    year: int | None = None


def read_metadata(path: Path) -> TrackMetadata | None:
    """Read metadata for one file. Return None if it cannot be used.

    None means: mutagen could not open it, it has no audio stream, or duration is
    missing/non-positive. The scanner logs and skips on None (§7 "skip/log
    unreadable files"); it does NOT skip merely sparse tags (§9.3).
    """
    try:
        audio = mutagen.File(path)  # type: ignore[attr-defined]
    except Exception:  # mutagen raises a zoo of errors on corrupt files
        return None
    if audio is None or audio.info is None:
        return None

    duration = getattr(audio.info, "length", None)
    if duration is None or duration <= 0:
        return None

    tags = audio.tags or {}
    return TrackMetadata(
        duration=float(duration),
        title=_first(tags, ("title", "TIT2", "\xa9nam")),
        artist=_first(tags, ("artist", "TPE1", "\xa9ART")),
        album=_first(tags, ("album", "TALB", "\xa9alb")),
        year=_parse_year(_first(tags, ("date", "year", "TDRC", "\xa9day"))),
    )


def _first(tags: object, keys: tuple[str, ...]) -> str | None:
    """Return the first present, non-empty tag value across known key spellings.

    Handles ID3 (TIT2), Vorbis (title), and MP4 (\\xa9nam) spellings uniformly.
    Mutagen tag values are usually lists; take element 0 and stringify.
    """
    if not hasattr(tags, "get"):
        return None
    for key in keys:
        value = tags.get(key)  # type: ignore[union-attr]
        if value is None:
            continue
        text = str(value[0]) if isinstance(value, list) and value else str(value)
        text = text.strip()
        if text:
            return text
    return None


def _parse_year(value: str | None) -> int | None:
    """Extract a 4-digit year from a free-form date tag; None if absent/garbage."""
    if not value:
        return None
    for token in value.replace("/", "-").split("-"):
        token = token.strip()
        if len(token) == 4 and token.isdigit():
            return int(token)
    return None
```

**Reviewer attack points:** the broad `except Exception` around `mutagen.File` is deliberate (mutagen raises many unrelated exception types on corrupt input); we narrow consequences by returning `None`, not by guessing the type. The tag-key fallback list covers ID3/Vorbis/MP4 but is not exhaustive — acceptable for Phase 0 since untagged files are the *expected* sparse case (§9.3) and the offline tagger (Phase 5) is the real fix.

---

### 4.6 `catalog/scanner.py` — folder scan → `Catalog` (§7, D3)

**Single responsibility:** walk one station's `content_dir`, build a deterministic in-memory index of one group per top-level subfolder.

**Design choice (open question, see §9):** `Catalog` is a **frozen Pydantic model** (a value object), not a service. Scanning is a free function `scan_catalog(...) -> Catalog`. This keeps the immutability rule, makes the catalog persistable through `persistence.py` for free, and keeps the scan logic testable in isolation.

```python
"""Catalog scanner (§7): content_dir -> one group per top-level subfolder.

Per-station libraries (D3). Deterministic ordering (sorted) so a (tree) -> Catalog
mapping is reproducible. Unreadable files are skipped and logged, never fatal; an
empty or missing content_dir, or one with zero non-empty groups, is fatal
(CatalogError) because §12 requires >= 1 non-empty group.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from pirate_radio.catalog.metadata import read_metadata
from pirate_radio.catalog.models import Track
from pirate_radio.errors import CatalogError

logger = logging.getLogger(__name__)

# Files mutagen can plausibly read; others are skipped without even opening.
_AUDIO_SUFFIXES = frozenset({".mp3", ".flac", ".ogg", ".oga", ".m4a", ".mp4", ".wav", ".opus"})


class Catalog(BaseModel):
    """In-memory index of a station's tracks, grouped by folder name.

    `tracks` is the flat list (stable, sorted by group then path). `groups` is the
    derived group -> tracks view. Frozen value object: rescanning produces a new
    Catalog rather than mutating this one.
    """

    model_config = ConfigDict(frozen=True)

    content_dir: Path
    tracks: tuple[Track, ...]

    def groups(self) -> dict[str, tuple[Track, ...]]:
        """Return group name -> its tracks (computed, never stored)."""
        out: dict[str, list[Track]] = {}
        for track in self.tracks:
            out.setdefault(track.group, []).append(track)
        return {name: tuple(items) for name, items in out.items()}

    def group_names(self) -> frozenset[str]:
        return frozenset(t.group for t in self.tracks)

    def is_group_non_empty(self, group: str) -> bool:
        """True iff `group` exists with >= 1 track — the §8.3/§12 check."""
        return any(t.group == group for t in self.tracks)


def scan_catalog(content_dir: Path) -> Catalog:
    """Scan `content_dir` into a Catalog. Fail fast if it yields no usable groups.

    One group per *top-level* subfolder; nested files inherit the top-level folder
    name as their group. Skips (logs) unreadable files and unknown suffixes.
    """
    content_dir = Path(content_dir)
    if not content_dir.is_dir():
        raise CatalogError(f"content_dir does not exist or is not a directory: {content_dir}")

    tracks: list[Track] = []
    for group_dir in sorted(p for p in content_dir.iterdir() if p.is_dir()):
        group = group_dir.name
        tracks.extend(_scan_group(group_dir, group))

    if not tracks:
        raise CatalogError(
            f"content_dir has no non-empty group subfolders with readable audio: {content_dir}"
        )

    tracks.sort(key=lambda t: (t.group, str(t.path)))
    return Catalog(content_dir=content_dir, tracks=tuple(tracks))


def _scan_group(group_dir: Path, group: str) -> Iterable[Track]:
    for path in sorted(group_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _AUDIO_SUFFIXES:
            continue
        meta = read_metadata(path)
        if meta is None:
            logger.warning("skipping unreadable/duration-less file: %s", path)
            continue
        yield Track(
            path=path,
            group=group,
            duration=meta.duration,
            title=meta.title,
            artist=meta.artist,
            album=meta.album,
            year=meta.year,
        )
```

**Reviewer attack points:** determinism comes from `sorted()` at every level + a final stable sort; the `(group, path)` sort key is the persisted/iteration contract (Phase-1 seedable generation, R19, will depend on it). `rglob` means nested folders collapse into their top-level group — matches §3's "top-level subfolder" definition; reviewers may argue for top-level-only files. Logging goes through stdlib `logging` (journald/stdout per R8′), not print.

---

### 4.7 `schedule/grid.py` — `Slot`/`Grid` models + YAML loader + resolution + validation (§8.2, §8.3)

**Single responsibility:** load and fully validate a hand-authored grid for a station/day. No generation.

This module is the largest; it is internally organized as: models → YAML parsing → day-of-week resolution → validation. If it approaches the 400-line guideline it splits into `schedule/grid_models.py` + `schedule/grid_loader.py`; planned as one file for now.

```python
"""Grid models, YAML loader, day-of-week resolution, and fail-fast validation.

§8.2 format + resolution order; §8.3 validation (contiguous 00:00->24:00 tiling,
start < end, group -> non-empty content folder, required name). A bad grid fails
loudly here, never silently at runtime.
"""

from __future__ import annotations

from datetime import time
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from pirate_radio.errors import GridResolutionError, GridValidationError

# §8.2 resolution priority: exact day -> weekday/weekend -> default.
# Index 0=Monday .. 6=Sunday matches datetime.weekday().
_DAY_FILES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_MIDNIGHT = time(0, 0)


class Slot(BaseModel):
    """One time range bound to a group (§13). end is exclusive; 24:00 -> time(0,0)."""

    model_config = ConfigDict(frozen=True)

    start: time
    end: time
    group: str = Field(min_length=1)
    name: str = Field(min_length=1)            # required (§8.3)
    tagline: str | None = None                 # optional
    description: str | None = None             # optional

    @model_validator(mode="after")
    def _start_before_end(self) -> "Slot":
        # end == 00:00 is the special "24:00" end-of-day marker; allow only as last slot.
        if self.end != _MIDNIGHT and self.start >= self.end:
            raise GridValidationError(
                f"slot '{self.name}': start {self.start} must be < end {self.end}"
            )
        return self


class Grid(BaseModel):
    """A resolved daily grid: an ordered, fully-tiling list of slots (§13)."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    slots: tuple[Slot, ...] = Field(min_length=1)


def resolve_grid_path(schedule_dir: Path, weekday: int) -> Path:
    """Resolve which grid file applies for `weekday` (0=Mon..6=Sun) per §8.2.

    Search order: <day>.yaml -> weekday.yaml/weekend.yaml -> default.yaml.
    Raises GridResolutionError if none exist.
    """
    schedule_dir = Path(schedule_dir)
    candidates = [f"{_DAY_FILES[weekday]}.yaml"]
    candidates.append("weekend.yaml" if weekday >= 5 else "weekday.yaml")
    candidates.append("default.yaml")
    for name in candidates:
        path = schedule_dir / name
        if path.is_file():
            return path
    raise GridResolutionError(
        f"no grid for weekday {weekday} in {schedule_dir}; tried {candidates}"
    )


def load_grid(path: Path) -> Grid:
    """Parse + structurally validate one grid YAML file (no folder cross-check).

    Uses yaml.safe_load (never load/FullLoader) so a grid file cannot execute code.
    Cross-folder validation (group -> non-empty subfolder) is done by
    validate_grid_against_catalog because it needs the catalog.
    """
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise GridValidationError(f"{path}: invalid YAML: {exc}") from exc
    except OSError as exc:
        raise GridValidationError(f"{path}: cannot read: {exc}") from exc

    if not isinstance(raw, dict) or "slots" not in raw:
        raise GridValidationError(f"{path}: expected a mapping with a 'slots' key")

    try:
        grid = Grid(name=raw.get("name", path.stem), slots=tuple(raw["slots"]))
    except GridValidationError:
        raise
    except Exception as exc:  # pydantic ValidationError et al.
        raise GridValidationError(f"{path}: {exc}") from exc

    _validate_tiling(grid, path)
    return grid


def _validate_tiling(grid: Grid, path: Path) -> None:
    """Slots must tile 00:00 -> 24:00 contiguously, no gaps/overlaps (§8.3)."""
    slots = grid.slots
    if slots[0].start != _MIDNIGHT:
        raise GridValidationError(f"{path}: first slot must start at 00:00, got {slots[0].start}")
    for prev, nxt in zip(slots, slots[1:], strict=False):
        if prev.end != nxt.start:
            raise GridValidationError(
                f"{path}: gap/overlap between '{prev.name}' (ends {prev.end}) "
                f"and '{nxt.name}' (starts {nxt.start})"
            )
    if slots[-1].end != _MIDNIGHT:
        raise GridValidationError(
            f"{path}: last slot must end at 24:00 (00:00), got {slots[-1].end}"
        )


def validate_grid_against_catalog(grid: Grid, non_empty_groups: frozenset[str], path: Path) -> None:
    """Every slot.group must map to a non-empty content subfolder (§8.3/§12)."""
    missing = sorted({s.group for s in grid.slots} - non_empty_groups)
    if missing:
        raise GridValidationError(
            f"{path}: slot groups with no non-empty content folder: {missing}"
        )
```

**Reviewer attack points:**
- The 24:00 problem: `datetime.time` has no 24:00, so end-of-day is modeled as `time(0,0)` allowed **only** as the final slot's `end`; `_start_before_end` permits `end==00:00`, and `_validate_tiling` enforces it appears only last (a non-last slot ending at 00:00 would create a `prev.end != nxt.start` failure, except the pathological case of a slot `start=00:00 end=00:00` which `Slot`'s validator already rejects since `start >= end`... unless start is also 00:00 — **reviewers: confirm a midnight-to-midnight single slot is correctly rejected/accepted**). A single all-day slot `start=00:00, end=00:00` is the one ambiguous case; Phase 0 **accepts** it as "all day" since first.start==00:00 and last.end==00:00 both hold and there are no neighbors. This must be an explicit test.
- Two-phase validation (structural in `load_grid`, folder cross-check in `validate_grid_against_catalog`) is deliberate so grid parsing is unit-testable without a content tree, and `config.py` wires the cross-check using `Catalog.group_names()` filtered to non-empty.
- `strict=False` on `zip` is intentional (lists differ by one). Reviewers may prefer explicit pairwise iteration.

---

### 4.8 `audio_devices.py` — R10 resolver seam (config dependency)

**Single responsibility:** the testable boundary for R10. Config validation must confirm each station's `audio_device` resolves to a **stable** name, but CI has no hardware — so resolution is a Protocol with a real (udev/ALSA) impl and a fake.

```python
"""Stable audio-device-name resolution seam (R10).

R10 requires that each station's configured audio_device resolves to a stable
ALSA/udev name keyed on physical USB port path, and that config validation fails
fast if devices can't be resolved or collide. CI has no hardware, so resolution is
a Protocol: production injects UdevAudioDeviceResolver; tests inject a fake mapping.
Phase 0 ships ONLY the Protocol + a fake + a documented place for the real impl.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AudioDeviceResolver(Protocol):
    """Resolves a configured device name to a stable hardware identity.

    available_devices() returns the set of stable names this host exposes (e.g.
    udev-assigned ALSA names). Config validation checks membership and uniqueness
    against this set. The real impl reads udev/ALSA; Phase 0 ships only the seam.
    """

    def available_devices(self) -> frozenset[str]:
        """Return the set of stable, resolvable audio-device names on this host."""
        ...


class StaticAudioDeviceResolver:
    """Test/dev resolver backed by a fixed name set. CI uses this everywhere.

    Lets config validation tests assert R10 behavior (unknown device -> error,
    collision -> error) with zero hardware.
    """

    def __init__(self, names: frozenset[str]) -> None:
        self._names = names

    def available_devices(self) -> frozenset[str]:
        return self._names


# Real implementation (UdevAudioDeviceResolver) is deferred to Phase 4 multi-station
# bring-up, where it can be tested on real dongles behind @pytest.mark.hardware.
# It belongs here so config.py's import target never changes.
```

**Why this satisfies R10 testably:** the *policy* (every `audio_device` must be a known, unique stable name) lives in `config.py` and is fully unit-tested via `StaticAudioDeviceResolver`. The *mechanism* (reading udev) is the only hardware-bound part and is deferred to Phase 4 with a `@pytest.mark.hardware` test. Phase 0 thus enforces R10's contract with **no hardware test**.

---

### 4.9 `config.py` — Pydantic v2 config with discriminated unions (R16) + fail-fast validation (§12)

**Single responsibility:** model, load, and fully validate `config.json`. Split note: if it exceeds ~400 lines, extract the provider-config unions into `config_providers.py`. Planned as one file.

```python
"""config.json models, loader, and fail-fast validation (§12, R16, R10).

Discriminated unions keyed on `backend` (R16) make a typo'd provider param fail at
load, not mid-broadcast. All §12 checks run at load: unique station names, distinct
audio_device, exactly one of dj_personality/_file, every *_env present in os.environ,
schedule_dir/content_dir exist with >= 1 valid grid / >= 1 non-empty group, and R10
stable-device resolution (via an injected AudioDeviceResolver seam).
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pirate_radio.audio_devices import AudioDeviceResolver
from pirate_radio.catalog.scanner import scan_catalog
from pirate_radio.errors import ConfigError
from pirate_radio.schedule.grid import (
    load_grid,
    resolve_grid_path,
    validate_grid_against_catalog,
)

_FROZEN = ConfigDict(frozen=True, extra="forbid")  # extra="forbid": typos are errors


# ---- TTS provider configs (R16: discriminated union on `backend`) ---------------
class PiperTTSConfig(BaseModel):
    model_config = _FROZEN
    backend: Literal["piper"]
    voice: str
    speed: float = 1.0


class EspeakTTSConfig(BaseModel):
    model_config = _FROZEN
    backend: Literal["espeak"]
    voice: str
    speed: float = 1.0
    pitch: int = 50


class ElevenLabsTTSConfig(BaseModel):
    model_config = _FROZEN
    backend: Literal["elevenlabs"]
    voice_id: str
    stability: float = 0.5
    similarity_boost: float = 0.75


TTSConfig = Annotated[
    Union[PiperTTSConfig, EspeakTTSConfig, ElevenLabsTTSConfig],
    Field(discriminator="backend"),
]


# ---- LLM provider configs (R16: discriminated union on `backend`, D2) -----------
class ClaudeLLMConfig(BaseModel):
    model_config = _FROZEN
    backend: Literal["claude"]
    model: str
    api_key_env: str


class DeepSeekLLMConfig(BaseModel):
    model_config = _FROZEN
    backend: Literal["deepseek"]
    model: str
    api_key_env: str


class OllamaLLMConfig(BaseModel):
    model_config = _FROZEN
    backend: Literal["ollama"]
    model: str
    endpoint: str  # self-hosted LAN server (D2), not on-Pi inference


LLMProviderConfig = Annotated[
    Union[ClaudeLLMConfig, DeepSeekLLMConfig, OllamaLLMConfig],
    Field(discriminator="backend"),
]


class LLMConfig(BaseModel):
    model_config = _FROZEN
    providers: tuple[LLMProviderConfig, ...] = Field(min_length=1)
    max_requests_per_minute: int = Field(default=20, gt=0)


class StationConfig(BaseModel):
    """Per-station settings (§13). schedule_dir/content_dir are filesystem-validated
    later by validate_config (Pydantic only checks shape here)."""

    model_config = _FROZEN
    name: str = Field(min_length=1)
    tagline: str | None = None
    description: str | None = None
    schedule_dir: Path
    content_dir: Path
    dj_personality: str | None = None
    dj_personality_file: Path | None = None
    tts: tuple[TTSConfig, ...] = Field(min_length=1)
    audio_device: str = Field(min_length=1)
    llm: LLMConfig | None = None  # optional per-station override (§12)
    transition_silence_seconds: float = Field(default=2.0, ge=0)
    loudness_target_lufs: float = -16.0
    repeat_window_minutes: int = Field(default=120, ge=0)

    @model_validator(mode="after")
    def _exactly_one_persona(self) -> "StationConfig":
        has_inline = self.dj_personality is not None
        has_file = self.dj_personality_file is not None
        if has_inline == has_file:  # both or neither
            raise ConfigError(
                f"station '{self.name}': set exactly one of "
                f"dj_personality / dj_personality_file"
            )
        return self


class DaemonConfig(BaseModel):
    model_config = _FROZEN
    llm: LLMConfig
    tts_providers: dict[str, dict] = Field(default_factory=dict)  # shared creds; typed in Phase 2
    stations: tuple[StationConfig, ...] = Field(min_length=1)


def load_config(
    path: Path,
    *,
    resolver: AudioDeviceResolver,
    clock_weekday: int | None = None,
) -> DaemonConfig:
    """Load + fully validate config.json (§12). `resolver` injects R10 device names.

    `clock_weekday` selects which grid to resolve for the grid-existence check; when
    None, today's weekday from the system clock is used (only place a weekday is
    needed at config time). Kept injectable for deterministic tests (R18 spirit).
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc

    try:
        config = DaemonConfig.model_validate(raw)
    except ConfigError:
        raise
    except Exception as exc:  # pydantic ValidationError
        raise ConfigError(f"{path}: invalid config: {exc}") from exc

    weekday = clock_weekday if clock_weekday is not None else datetime.now().weekday()
    _validate_config(config, resolver=resolver, weekday=weekday)
    return config


def _validate_config(
    config: DaemonConfig, *, resolver: AudioDeviceResolver, weekday: int
) -> None:
    """All §12 fail-fast cross-field/filesystem/env checks."""
    _check_unique_station_names(config)
    _check_distinct_audio_devices(config)
    _check_audio_devices_resolve(config, resolver)
    _check_env_vars_present(config)
    for station in config.stations:
        _check_station_dirs(station, weekday)


def _check_unique_station_names(config: DaemonConfig) -> None:
    names = [s.name for s in config.stations]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ConfigError(f"duplicate station names: {dupes}")


def _check_distinct_audio_devices(config: DaemonConfig) -> None:
    devices = [s.audio_device for s in config.stations]
    dupes = sorted({d for d in devices if devices.count(d) > 1})
    if dupes:
        raise ConfigError(f"two stations claim the same audio_device: {dupes}")


def _check_audio_devices_resolve(config: DaemonConfig, resolver: AudioDeviceResolver) -> None:
    """R10: each audio_device must be a known stable name on this host."""
    available = resolver.available_devices()
    unknown = sorted({s.audio_device for s in config.stations} - available)
    if unknown:
        raise ConfigError(
            f"audio_device(s) do not resolve to a stable device name (R10): {unknown}; "
            f"available: {sorted(available)}"
        )


def _check_env_vars_present(config: DaemonConfig) -> None:
    """Every referenced *_env var must exist in the environment (§12)."""
    needed: set[str] = set()
    chains = [config.llm.providers]
    chains += [s.llm.providers for s in config.stations if s.llm is not None]
    for providers in chains:
        for prov in providers:
            env_name = getattr(prov, "api_key_env", None)
            if env_name:
                needed.add(env_name)
    missing = sorted(n for n in needed if n not in os.environ)
    if missing:
        raise ConfigError(f"required environment variables not set: {missing}")


def _check_station_dirs(station: StationConfig, weekday: int) -> None:
    """schedule_dir/content_dir exist; >= 1 resolvable+valid grid; >= 1 non-empty group."""
    if not station.schedule_dir.is_dir():
        raise ConfigError(f"station '{station.name}': schedule_dir missing: {station.schedule_dir}")
    if not station.content_dir.is_dir():
        raise ConfigError(f"station '{station.name}': content_dir missing: {station.content_dir}")
    if station.dj_personality_file is not None:
        persona_path = station.schedule_dir / station.dj_personality_file
        if not persona_path.is_file():
            raise ConfigError(
                f"station '{station.name}': dj_personality_file not found: {persona_path}"
            )

    catalog = scan_catalog(station.content_dir)  # raises CatalogError if no non-empty group
    non_empty = frozenset(g for g in catalog.group_names() if catalog.is_group_non_empty(g))

    grid_path = resolve_grid_path(station.schedule_dir, weekday)  # raises if none
    grid = load_grid(grid_path)
    validate_grid_against_catalog(grid, non_empty, grid_path)
```

**Reviewer attack points:**
- `extra="forbid"` on every config model turns an unknown/typo'd key (e.g. `simillarity_boost`) into a load-time error — this is how R16's "fail-fast, no silent drift" is realized beyond the discriminator.
- `_check_station_dirs` validates **only today's** grid (the one that would be loaded now). §12 says "≥ 1 valid grid" — reviewers should decide whether Phase 0 should validate **all present** grid files (mon–sun/weekday/weekend/default) at load, not just today's. **This is an open question (§9).** Current plan: validate today's (guarantees the daemon can start) + a separate `validate_all_grids` helper is a candidate Phase-0 addition if the panel wants it.
- `tts_providers` stays a typed-later `dict[str, dict]` because it holds shared **credentials/endpoints** consumed only when engines are built (Phase 2); modeling it now would be speculative (it has no Phase-0 reader). Flagged, defensible.
- `load_config` takes `resolver` as a required keyword — production wires `UdevAudioDeviceResolver()`, tests wire `StaticAudioDeviceResolver(frozenset({...}))`. No hardware in the test path.

---

## 5. Cross-Cutting Conventions

- **Immutability:** every model is `frozen=True`; collections are `tuple`/`frozenset`, not `list`/`set`, so a frozen model truly can't be mutated in place. Updates use `model_copy(update=...)`. (Coding-style "never mutate".)
- **Timezone-awareness (D6):** the *only* `datetime.now()` calls live in `clock.py` (`SystemClock`) and the single weekday lookup in `load_config` (documented, injectable). Everything that needs "now" takes a `Clock`. `FixedClock` rejects naive datetimes so naive time can't leak into a test.
- **No bare dicts in the model layer (R16/R17):** provider configs are discriminated unions; the persistence envelope is structured. The two remaining `dict`s (`tts_providers`, the not-yet-built `dj_context`) are explicitly annotated as Phase-2/Phase-1 typing debt with no current reader.
- **Clock threading:** Phase 0 needs the clock only for `load_config`'s weekday; the seam exists now so Phase 1 (`find_now`, midnight regen) threads the *same* `Clock` instance from the coordinator down. No global clock singleton.
- **Error handling / logging:** every boundary (file read, YAML parse, tag read, JSON parse) is wrapped and re-raised as a typed `PirateRadioError` subclass with an actionable, secret-free message. Diagnostics go through stdlib `logging` to stdout/journald (R8′) — never `print`. Bad *data* (a corrupt audio file) returns `None`/skips; bad *config/grid* raises and fails fast (§8.3, §12). Errors are never silently swallowed.
- **Input validation at boundaries:** `yaml.safe_load` only; `extra="forbid"` on config models; `json.loads` wrapped; all external paths checked for existence before use.

---

## 6. Test Plan (TDD)

Layout: `tests/<module>/test_*.py` mirroring `src`. Shared fixtures in `tests/conftest.py`. **Phase 0 has zero `@pytest.mark.hardware` tests** — every test is pure and CI-runnable. The one hardware-bound concern (R10 udev resolution) is kept testable by the `AudioDeviceResolver` seam: tests inject `StaticAudioDeviceResolver`, so config validation including R10 runs in CI with no device. The 80% floor is honest because there is no hardware code inflating the denominator this phase (R20).

### 6.0 Shared fixtures (`tests/conftest.py`)

```python
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pirate_radio.audio_devices import StaticAudioDeviceResolver
from pirate_radio.clock import FixedClock


@pytest.fixture
def fixed_clock() -> FixedClock:
    # A Wednesday (weekday()==2) at 09:30 local, tz-aware.
    return FixedClock(datetime(2026, 6, 10, 9, 30, tzinfo=ZoneInfo("America/New_York")))


@pytest.fixture
def resolver() -> StaticAudioDeviceResolver:
    return StaticAudioDeviceResolver(frozenset({"usb-port-1", "usb-port-2"}))


@pytest.fixture
def content_tree(tmp_path: Path) -> Path:
    """A content_dir with two non-empty groups of tiny real audio files."""
    root = tmp_path / "library"
    for group, count in (("classical", 2), ("oldies", 2)):
        d = root / group
        d.mkdir(parents=True)
        for i in range(count):
            _write_silent_wav(d / f"track{i}.wav", seconds=1)
    (root / "empty_group").mkdir()  # present but empty -> must be ignored
    return root


@pytest.fixture
def grid_yaml(tmp_path: Path) -> Path:
    schedule_dir = tmp_path / "stations" / "pirate-one"
    schedule_dir.mkdir(parents=True)
    (schedule_dir / "default.yaml").write_text(
        "slots:\n"
        '  - {start: "00:00", end: "06:00", group: classical, name: "Night Music"}\n'
        '  - {start: "06:00", end: "00:00", group: oldies, name: "Day"}\n',
        encoding="utf-8",
    )
    return schedule_dir
```

`_write_silent_wav` writes a real 1-second WAV via the stdlib `wave` module (no extra dep), giving `mutagen` a genuine file with a real `info.length` — so metadata tests use **real mutagen on tiny real fixtures**, not mocks.

### 6.1 `errors.py` — RED tests

```python
from pathlib import Path
import pytest
from pirate_radio.errors import PirateRadioError, ConfigError, StateCorruptionError


def test_all_errors_subclass_root():
    assert issubclass(ConfigError, PirateRadioError)


def test_state_corruption_carries_path():
    err = StateCorruptionError("boom", path=Path("/x/state.json"))
    assert err.path == Path("/x/state.json")
    assert isinstance(err, PirateRadioError)
```

### 6.2 `clock.py` — RED tests (use real, not mocked)

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytest
from pirate_radio.clock import SystemClock, FixedClock, Clock


def test_systemclock_now_is_tz_aware():
    assert SystemClock().now().tzinfo is not None


def test_systemclock_honours_injected_zone():
    clk = SystemClock(zone=ZoneInfo("UTC"))
    assert clk.tz() == ZoneInfo("UTC")
    assert clk.now().utcoffset() == timedelta(0)


def test_fixedclock_rejects_naive():
    with pytest.raises(ValueError):
        FixedClock(datetime(2026, 1, 1))  # naive


def test_fixedclock_is_deterministic_and_satisfies_protocol():
    t = datetime(2026, 6, 10, 9, 30, tzinfo=ZoneInfo("UTC"))
    clk = FixedClock(t)
    assert isinstance(clk, Clock)
    assert clk.now() == clk.now() == t
    assert clk.set(t + timedelta(hours=1)).now() == t + timedelta(hours=1)
```

### 6.3 `persistence.py` — RED tests (real filesystem via `tmp_path`)

```python
import json
from pathlib import Path
import pytest
from pydantic import BaseModel
from pirate_radio.persistence import atomic_write_json, load_with_recovery
from pirate_radio.errors import StateCorruptionError


class _Doc(BaseModel):
    n: int
    label: str


def test_round_trip(tmp_path: Path):
    p = tmp_path / "state.json"
    atomic_write_json(p, _Doc(n=1, label="a"), schema_version=1)
    assert load_with_recovery(p, _Doc, schema_version=1) == _Doc(n=1, label="a")


def test_envelope_has_version(tmp_path: Path):
    p = tmp_path / "state.json"
    atomic_write_json(p, _Doc(n=1, label="a"), schema_version=1)
    assert json.loads(p.read_text())["schema_version"] == 1


def test_recovers_from_bak_when_live_corrupt(tmp_path: Path):
    p = tmp_path / "state.json"
    atomic_write_json(p, _Doc(n=1, label="good"), schema_version=1)   # creates live
    atomic_write_json(p, _Doc(n=2, label="newer"), schema_version=1)  # rotates good -> .bak
    p.write_text("{ truncated", encoding="utf-8")                     # corrupt live
    assert load_with_recovery(p, _Doc, schema_version=1).label == "good"


def test_raises_when_both_corrupt(tmp_path: Path):
    p = tmp_path / "state.json"
    atomic_write_json(p, _Doc(n=1, label="a"), schema_version=1)
    p.write_text("bad", encoding="utf-8")
    p.with_suffix(".json.bak").write_text("also bad", encoding="utf-8")
    with pytest.raises(StateCorruptionError) as ei:
        load_with_recovery(p, _Doc, schema_version=1)
    assert ei.value.path == p


def test_version_mismatch_is_corruption(tmp_path: Path):
    p = tmp_path / "state.json"
    atomic_write_json(p, _Doc(n=1, label="a"), schema_version=1)
    with pytest.raises(StateCorruptionError):
        load_with_recovery(p, _Doc, schema_version=2)


def test_no_temp_files_left_behind(tmp_path: Path):
    p = tmp_path / "state.json"
    atomic_write_json(p, _Doc(n=1, label="a"), schema_version=1)
    assert not list(tmp_path.glob("*.tmp"))
```

A durability test simulating crash-mid-write (monkeypatch `os.replace` to raise, assert the live file/`.bak` is still valid) is added to cover the `except BaseException` cleanup path.

### 6.4 `catalog/metadata.py` — RED tests (real mutagen on tiny fixtures)

```python
from pathlib import Path
from pirate_radio.catalog.metadata import read_metadata


def test_reads_duration_from_real_wav(content_tree: Path):
    meta = read_metadata(content_tree / "classical" / "track0.wav")
    assert meta is not None and meta.duration > 0


def test_sparse_tags_are_none_not_skipped(content_tree: Path):
    meta = read_metadata(content_tree / "classical" / "track0.wav")
    assert meta is not None
    assert meta.title is None  # untagged silence -> best-effort, still returned


def test_corrupt_file_returns_none(tmp_path: Path):
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"not audio")
    assert read_metadata(bad) is None


def test_missing_file_returns_none(tmp_path: Path):
    assert read_metadata(tmp_path / "nope.flac") is None
```

A small ID3-tagged MP3 fixture (committed under `tests/fixtures/`) covers the tag-extraction + `_parse_year` paths; if generating one is awkward, `mutagen` is used to *write* tags onto a generated file in a fixture factory (still real mutagen, no mock).

### 6.5 `catalog/scanner.py` — RED tests

```python
import pytest
from pathlib import Path
from pirate_radio.catalog.scanner import scan_catalog, Catalog
from pirate_radio.errors import CatalogError


def test_one_group_per_top_level_folder(content_tree: Path):
    cat = scan_catalog(content_tree)
    assert cat.group_names() == frozenset({"classical", "oldies"})  # empty_group dropped


def test_deterministic_ordering(content_tree: Path):
    assert scan_catalog(content_tree).tracks == scan_catalog(content_tree).tracks


def test_group_track_counts(content_tree: Path):
    groups = scan_catalog(content_tree).groups()
    assert len(groups["classical"]) == 2 and len(groups["oldies"]) == 2


def test_missing_content_dir_raises(tmp_path: Path):
    with pytest.raises(CatalogError):
        scan_catalog(tmp_path / "nope")


def test_no_groups_raises(tmp_path: Path):
    (tmp_path / "library").mkdir()
    with pytest.raises(CatalogError):
        scan_catalog(tmp_path / "library")


def test_unreadable_file_skipped_not_fatal(content_tree: Path):
    (content_tree / "classical" / "broken.mp3").write_bytes(b"junk")
    cat = scan_catalog(content_tree)  # must not raise
    assert all(t.path.name != "broken.mp3" for t in cat.tracks)
```

### 6.6 `schedule/grid.py` — RED tests

```python
import pytest
from datetime import time
from pathlib import Path
from pirate_radio.schedule.grid import (
    load_grid, resolve_grid_path, validate_grid_against_catalog,
)
from pirate_radio.errors import GridValidationError, GridResolutionError


def _write(p: Path, body: str) -> Path:
    p.write_text(body, encoding="utf-8"); return p


def test_resolution_prefers_exact_day(tmp_path: Path):
    d = tmp_path; (d / "default.yaml").touch(); (d / "wednesday.yaml").touch()
    assert resolve_grid_path(d, weekday=2).name == "wednesday.yaml"


def test_resolution_weekend_then_default(tmp_path: Path):
    d = tmp_path; (d / "default.yaml").touch(); (d / "weekend.yaml").touch()
    assert resolve_grid_path(d, weekday=6).name == "weekend.yaml"   # Sunday
    # remove weekend -> falls to default
    (d / "weekend.yaml").unlink()
    assert resolve_grid_path(d, weekday=6).name == "default.yaml"


def test_resolution_none_raises(tmp_path: Path):
    with pytest.raises(GridResolutionError):
        resolve_grid_path(tmp_path, weekday=0)


def test_valid_grid_tiles_full_day(tmp_path: Path):
    g = load_grid(_write(tmp_path / "default.yaml",
        'slots:\n'
        '  - {start: "00:00", end: "12:00", group: a, name: "AM"}\n'
        '  - {start: "12:00", end: "00:00", group: b, name: "PM"}\n'))
    assert g.slots[0].start == time(0, 0) and g.slots[-1].end == time(0, 0)


def test_gap_rejected(tmp_path: Path):
    with pytest.raises(GridValidationError, match="gap/overlap"):
        load_grid(_write(tmp_path / "g.yaml",
            'slots:\n'
            '  - {start: "00:00", end: "06:00", group: a, name: "x"}\n'
            '  - {start: "07:00", end: "00:00", group: b, name: "y"}\n'))


def test_overlap_rejected(tmp_path: Path):
    with pytest.raises(GridValidationError):
        load_grid(_write(tmp_path / "g.yaml",
            'slots:\n'
            '  - {start: "00:00", end: "06:00", group: a, name: "x"}\n'
            '  - {start: "05:00", end: "00:00", group: b, name: "y"}\n'))


def test_must_start_at_midnight(tmp_path: Path):
    with pytest.raises(GridValidationError, match="00:00"):
        load_grid(_write(tmp_path / "g.yaml",
            'slots:\n  - {start: "01:00", end: "00:00", group: a, name: "x"}\n'))


def test_start_not_before_end_rejected(tmp_path: Path):
    with pytest.raises(GridValidationError):
        load_grid(_write(tmp_path / "g.yaml",
            'slots:\n  - {start: "06:00", end: "03:00", group: a, name: "x"}\n'))


def test_missing_name_rejected(tmp_path: Path):
    with pytest.raises(GridValidationError):
        load_grid(_write(tmp_path / "g.yaml",
            'slots:\n  - {start: "00:00", end: "00:00", group: a}\n'))


def test_yaml_safe_load_only(tmp_path: Path):
    # A python/object tag must be rejected by safe_load (no code execution).
    with pytest.raises(GridValidationError):
        load_grid(_write(tmp_path / "g.yaml", "slots: !!python/object/apply:os.system ['echo hi']\n"))


def test_group_not_in_catalog_rejected(tmp_path: Path):
    g = load_grid(_write(tmp_path / "g.yaml",
        'slots:\n  - {start: "00:00", end: "00:00", group: jazz, name: "x"}\n'))
    with pytest.raises(GridValidationError, match="jazz"):
        validate_grid_against_catalog(g, frozenset({"classical"}), tmp_path / "g.yaml")


def test_single_all_day_slot_accepted(tmp_path: Path):
    g = load_grid(_write(tmp_path / "g.yaml",
        'slots:\n  - {start: "00:00", end: "00:00", group: a, name: "All Day"}\n'))
    assert len(g.slots) == 1   # documents the 24:00-as-00:00 edge case decision
```

### 6.7 `config.py` — RED tests (inject `StaticAudioDeviceResolver`, no hardware)

```python
import json
import pytest
from pathlib import Path
from pirate_radio.config import load_config
from pirate_radio.audio_devices import StaticAudioDeviceResolver
from pirate_radio.errors import ConfigError


def _valid_config(content_tree: Path, grid_yaml: Path) -> dict:
    return {
        "llm": {"providers": [
            {"backend": "claude", "model": "x", "api_key_env": "ANTHROPIC_API_KEY"}]},
        "tts_providers": {},
        "stations": [{
            "name": "PiRate One",
            "schedule_dir": str(grid_yaml),
            "content_dir": str(content_tree),
            "dj_personality": "calm",
            "tts": [{"backend": "piper", "voice": "en_US-ryan-high"}],
            "audio_device": "usb-port-1",
        }],
    }


def _write_cfg(tmp_path, data) -> Path:
    p = tmp_path / "config.json"; p.write_text(json.dumps(data)); return p


def test_loads_valid_config(tmp_path, content_tree, grid_yaml, resolver, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    cfg = load_config(_write_cfg(tmp_path, _valid_config(content_tree, grid_yaml)),
                      resolver=resolver, clock_weekday=2)
    assert cfg.stations[0].tts[0].backend == "piper"   # discriminated union resolved


def test_typo_in_tts_param_rejected(tmp_path, content_tree, grid_yaml, resolver, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    data = _valid_config(content_tree, grid_yaml)
    data["stations"][0]["tts"][0]["speeed"] = 1.0  # typo -> extra="forbid"
    with pytest.raises(ConfigError):
        load_config(_write_cfg(tmp_path, data), resolver=resolver, clock_weekday=2)


def test_unknown_tts_backend_rejected(tmp_path, content_tree, grid_yaml, resolver, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    data = _valid_config(content_tree, grid_yaml)
    data["stations"][0]["tts"][0] = {"backend": "festival", "voice": "x"}
    with pytest.raises(ConfigError):
        load_config(_write_cfg(tmp_path, data), resolver=resolver, clock_weekday=2)


def test_both_persona_fields_rejected(tmp_path, content_tree, grid_yaml, resolver, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    data = _valid_config(content_tree, grid_yaml)
    data["stations"][0]["dj_personality_file"] = "persona.md"  # now both set
    with pytest.raises(ConfigError, match="exactly one"):
        load_config(_write_cfg(tmp_path, data), resolver=resolver, clock_weekday=2)


def test_missing_env_var_rejected(tmp_path, content_tree, grid_yaml, resolver, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="environment"):
        load_config(_write_cfg(tmp_path, _valid_config(content_tree, grid_yaml)),
                    resolver=resolver, clock_weekday=2)


def test_duplicate_station_names_rejected(tmp_path, content_tree, grid_yaml, resolver, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    data = _valid_config(content_tree, grid_yaml)
    dup = dict(data["stations"][0]); dup["audio_device"] = "usb-port-2"
    data["stations"].append(dup)
    with pytest.raises(ConfigError, match="duplicate station"):
        load_config(_write_cfg(tmp_path, data), resolver=resolver, clock_weekday=2)


def test_same_audio_device_rejected(tmp_path, content_tree, grid_yaml, resolver, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    data = _valid_config(content_tree, grid_yaml)
    dup = dict(data["stations"][0]); dup["name"] = "Two"
    data["stations"].append(dup)  # same audio_device usb-port-1
    with pytest.raises(ConfigError, match="same audio_device"):
        load_config(_write_cfg(tmp_path, data), resolver=resolver, clock_weekday=2)


def test_unresolvable_device_rejected(tmp_path, content_tree, grid_yaml, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    bad_resolver = StaticAudioDeviceResolver(frozenset({"usb-port-9"}))  # R10
    with pytest.raises(ConfigError, match="R10"):
        load_config(_write_cfg(tmp_path, _valid_config(content_tree, grid_yaml)),
                    resolver=bad_resolver, clock_weekday=2)


def test_missing_content_dir_rejected(tmp_path, grid_yaml, resolver, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    data = _valid_config(tmp_path / "nope", grid_yaml)
    with pytest.raises(ConfigError):
        load_config(_write_cfg(tmp_path, data), resolver=resolver, clock_weekday=2)
```

### 6.8 What to fake vs use real

| Concern | Approach |
|---|---|
| Clock | Real `SystemClock` (assert tz-aware) + `FixedClock`. Never mock `datetime`. |
| Filesystem | Real, via `tmp_path`. |
| Audio metadata | **Real mutagen** on tiny generated WAVs + one committed tagged MP3 fixture. No mocking of mutagen. |
| Audio device resolution (R10) | `StaticAudioDeviceResolver` fake — the seam that keeps it CI-runnable. The real udev impl is Phase 4 + `@pytest.mark.hardware`. |
| Env vars | `monkeypatch.setenv/delenv`. |
| YAML/JSON | Real parsers on real temp files (including a malicious `!!python` tag test). |

### 6.9 Coverage honesty

No `@pytest.mark.hardware` code exists in Phase 0, so `--cov-fail-under=80` (package-wide) is not inflated by hardware lines (R20). The only `pragma: no cover` lines are the genuinely-unhittable `_resolve_local_zone` fallback and `__main__` guards. Target: each module ≥ 90%, package ≥ 80% with the uncovered-lines report audited, not just the percentage.

---

## 7. TDD Implementation Order (dependency-sorted)

Each step is full RED → GREEN → REFACTOR. Order follows the dependency DAG so nothing imports an unwritten module.

1. **`errors.py`** — no deps. RED: hierarchy + `StateCorruptionError.path`. GREEN: classes. REFACTOR: docstrings.
2. **`clock.py`** — no deps. RED: tz-aware, naive-rejection, determinism, Protocol conformance. GREEN. REFACTOR.
3. **`persistence.py`** — deps: `errors`. RED: round-trip, envelope/version, `.bak` recovery, both-corrupt raise, no temp leftovers, crash-mid-write durability. GREEN. REFACTOR.
4. **`catalog/models.py`** — deps: none (Pydantic). RED: `duration>0`, frozen, optional tags. GREEN.
5. **`catalog/metadata.py`** — deps: `models`. RED: real-WAV duration, sparse→None tags, corrupt→None, year parse. GREEN. REFACTOR `_first`/`_parse_year`.
6. **`catalog/scanner.py`** — deps: `metadata`, `models`, `errors`. RED: one-group-per-folder, determinism, empty/missing fatal, unreadable skipped. GREEN. REFACTOR.
7. **`schedule/grid.py`** — deps: `errors`. RED: resolution priority, tiling/gap/overlap/midnight/`start<end`/name, safe_load, catalog cross-check, all-day edge. GREEN. REFACTOR (split file if > 400 lines).
8. **`audio_devices.py`** — deps: none. RED: Protocol conformance, fake returns its set. GREEN.
9. **`config.py`** — deps: `errors`, `audio_devices`, `catalog.scanner`, `schedule.grid`. RED: valid load, every §12 failure mode, R16 union + typo rejection, R10 via fake resolver. GREEN. REFACTOR (extract provider unions if > 400 lines).
10. **Cleanup:** remove the placeholder `hello()` from `__init__.py` once real modules ship (or keep `__version__` only); update `tests/test_smoke.py` to import a real module.

---

## 8. Task / PR Breakdown

Small, independently-reviewable PRs. Each: tests-first, green CI, ruff + mypy clean, coverage ≥ 80% package-wide at all times.

| # | PR | Acceptance criteria |
|---|---|---|
| 1 | **chore: add Phase-0 deps** (`pydantic`, `mutagen`, `PyYAML`, `types-PyYAML`) | `pip install -e .[dev]` succeeds; mypy resolves `pydantic`/`yaml`; smoke test still green. |
| 2 | **feat: errors.py** | `PirateRadioError` root + 5 leaves; `StateCorruptionError.path`; 100% covered; mypy clean. |
| 3 | **feat: clock.py (R18/D6)** | `Clock` Protocol, `SystemClock` tz-aware, `FixedClock` rejects naive; tests prove determinism + Protocol conformance. |
| 4 | **feat: persistence.py (R5/R6/R17)** | atomic write (temp→fsync→replace→dir fsync), `.bak` rotation, recovery + both-corrupt raise, version envelope, no temp leftovers, crash-mid-write durability test. |
| 5 | **feat: catalog models + metadata (§7/§9.3)** | `Track` (`duration>0`, frozen); `read_metadata` real-WAV duration, sparse→None tags, corrupt/missing→None, year parse. |
| 6 | **feat: catalog scanner (§7/D3)** | one group per top-level folder, deterministic order, empty/missing fatal, unreadable skipped+logged; `Catalog.is_group_non_empty`. |
| 7 | **feat: schedule/grid loader + validation (§8.2/§8.3)** | models + `safe_load` + resolution priority + full tiling/`start<end`/name validation + catalog cross-check + all-day edge documented by test. |
| 8 | **feat: audio_devices resolver seam (R10)** | `AudioDeviceResolver` Protocol + `StaticAudioDeviceResolver`; documented deferral of real udev impl. |
| 9 | **feat: config.py (§12/R16/R10)** | discriminated TTS+LLM unions, `extra="forbid"`, `load_config`, every §12 check incl. R10 via injected resolver; full failure-mode test matrix. |
| 10 | **chore: retire placeholder** | `hello()` removed/replaced; smoke test imports a real module; README/`__init__` docstring updated. |

PRs 2–4 are independent and can land in any order; 5→6 sequential; 7 independent of 5/6 until 9; 9 depends on 6+7+8. Branch per PR off `main` (never commit to `main` directly).

---

## 9. Open Questions & Risks for the Panel

1. **`Catalog`: model vs service?** Plan makes it a **frozen Pydantic value object** (persistable via §4.3 for free, immutable). Alternative: a service class that lazily rescans. Risk: a huge library makes the flat `tuple[Track,...]` + per-call `groups()` recompute O(n) on every access — Phase 1 generation may want a cached group index. **Decision needed:** value object now, optimize later, or build the index in now?
2. **Validate today's grid only, or all present grids, at config load?** §12 says "≥ 1 valid grid." Current plan validates the grid that *would load today* (guarantees startup) and proposes an optional `validate_all_grids`. Validating all mon–sun files at boot catches a broken `saturday.yaml` on Tuesday — friendlier, slightly slower, and may reject a grid referencing a group the *current* catalog lacks but a future one will. **Which does the panel want?**
3. **24:00 / single all-day slot semantics.** Modeling end-of-day as `time(0,0)` makes a single `00:00→00:00` slot ambiguous (all-day vs zero-length). Plan **accepts** it as all-day and pins it with a test. Reviewers should confirm this is correct, or prefer a sentinel (e.g. a custom `DayTime` type or storing minutes-from-midnight 0–1440) — which would touch `Slot`, validation, and Phase-1 `find_now` time binding.
4. **R10 udev-name testing strategy.** Plan defers the real `UdevAudioDeviceResolver` to Phase 4 behind `@pytest.mark.hardware`, validating only the *policy* in Phase 0 via `StaticAudioDeviceResolver`. Is the panel comfortable that R10's mechanism ships untested until Phase 4, given the contract is enforced now? Alternative: a Phase-0 resolver that parses a saved `aplay -L` / udev fixture file (testable, no hardware) to exercise the parsing too.
5. **Timezone source under D6.** `SystemClock` extracts the local zone via `datetime.now().astimezone().tzinfo`. On a host with only a fixed UTC offset (no IANA zone), DST math is degenerate — acceptable under D6 ("trust the OS"), but the panel may want an explicit `PIRATE_RADIO_TZ` override env var for deterministic multi-tz deployments. Recorded, not blocking.
6. **`tts_providers` / `dj_context` left as `dict` for now.** R16 says "no bare dicts in the model layer." Plan keeps `tts_providers: dict[str,dict]` (shared creds, no Phase-0 reader) and omits `dj_context` entirely (Phase 1). Is deferring these typings acceptable, or does R16 demand they be modeled the moment they appear in `DaemonConfig`?
7. **YAML lib.** PyYAML chosen for read-only grids. If grids will ever be machine-edited with comment preservation, ruamel.yaml is the better long-term call. Confirm read-only is the lasting requirement.

---

## 10. Review Amendments (Rev 1 — adopted 7–0)

The seven-agent panel reviewed this plan and adopted the amendments below
unanimously. Full rationale and the vote record are in
`docs/decisions/0003-phase0-plan-review-rev1.md`. **Where an amendment conflicts
with §1–§9 above, this section governs.** The Fact Checker verified every
code-level API claim in §4 with **no refutations**.

### 10.1 Open questions resolved
- **Q1 (Catalog):** Frozen **value object**. Its internal representation is the
  **`group → tuple[Track]` mapping the scanner already produces**, so `groups()`
  and per-group access are **dict lookups, not per-call recompute**. **No** separate
  cache/service and **no** mtime-invalidation in Phase 0 (mtime-cached rescan →
  Phase 1). *(Closes the recompute smell without a speculative service.)*
- **Q2 (grid validation scope):** Validate **all present grid files** at config
  load. Structural checks (tiling, `start<end`, `name`, YAML safety) are **fatal for
  every** grid. The **group→content-folder** cross-check is **fatal for today's**
  grid and **warn-not-fatal for other days'** grids that reference a group absent
  from the current catalog. `validate_all_grids` is wired into the boot path. *(PR7
  acceptance criteria updated accordingly.)*
- **Q3 (24:00 / `time(0,0)`):** Keep `time(0,0)` as end-of-day for Phase 0, **plus
  new validation rules:** `end==00:00` legal **only on the final slot**; reject
  **non-final slot ending 00:00**, reject **zero-length slot** (`start==end`,
  end≠00:00), reject the **multi-slot midnight collision** `[00:00→00:00,
  00:00→00:00]`. Companion RED tests for each. A minutes-from-midnight / `DayTime`
  type is a **Phase-1 revisit** if `find_now` binding gets awkward.
- **Q4:** Defer the real `UdevAudioDeviceResolver` to Phase 4 (acceptable) — but per
  **A2** the contract is now pinned and the Static resolver becomes meaningful.
- **Q5:** Adopt the **`PIRATE_RADIO_TZ`** override env var (A8).
- **Q6:** **Do not** leave `tts_providers` as an unvalidated dict — see **A3**.
- **Q7:** **PyYAML** confirmed (read-only grids; `safe_load`-only).

### 10.2 Must-fix amendments (before GREEN)
- **A1 — Reject empty/blank `*_env` secrets.** `_check_env_vars_present` →
  `not os.environ.get(n, "").strip()`; add `test_empty_env_var_rejected` and
  `test_whitespace_env_var_rejected`. *(§4.9)*
- **A2 — R10 resolves to physical identity, not strings.** `AudioDeviceResolver`
  becomes `resolve(name) -> PortId`; distinctness checked on the **resolved PortId**
  (catches two config names aliasing one physical port). `StaticAudioDeviceResolver`
  maps names→PortIds (test no longer tautological); add a **two-names-same-port →
  reject** test. **Contract:** *stable name = udev-assigned ALSA card id keyed on
  the physical USB port path* (not USB serial — CM108/CM109 dongles share/omit
  serials); real resolver bridges **PortAudio name → `hw:CARD=`**. Real udev impl
  stays Phase 4 behind `@pytest.mark.hardware`. *(§4.8, §4.9)*
- **A3 — Close the `tts_providers` R16 hole now.** Add a `model_validator` on
  `DaemonConfig` checking each `tts_providers` entry against the **known per-backend
  key sets** (`extra="forbid"` does not recurse into dict values). Add a test
  asserting a typo'd nested key is rejected. *(§4.9)*
- **A4 — One clock site.** `load_config` takes a `Clock` and derives the weekday
  from it; remove the `datetime.now().weekday()` default so `clock.py` is the only
  `datetime.now()` call site. *(§4.9, §5)*
- **A5 — Test-quality fixes.** (a) Real **crash-injection** RED test for
  `persistence.py` (raise on `os.replace` **and** `os.fsync`; assert live-or-`.bak`
  valid, **no `.tmp` leak**, `_replace_keep_bak` failure path). (b) **`caplog`
  WARNING assertion** on every scanner skip-and-log path. (c) **De-tautologize**
  `test_deterministic_ordering` (assert expected `(group, path)` order + a
  non-sorted-creation-order case). (d) **Mandatory tagged-metadata fixture**
  asserting real title/artist/year (drop the "if awkward" hedge). *(§6)*

### 10.3 Documentation / forward notes
- **A6 — `state_dir` convention.** Add a `state_dir` config field (or documented
  default) placing mutable state **off the boot SD**; validate it **exists and is
  writable** at load; apply the writability check to `content_dir`/`schedule_dir`/
  `state_dir`; log the resolved device once. *(§4.3, §4.9)*
- **A7 — Persistence caveats.** Docstring states required FS (**ext4/f2fs**; not
  vfat/overlay-on-SD for state), dir-`fsync` may silently no-op on some FS, a
  **"not for hot paths"** rule (Phase-1 resume state must batch/debounce or use
  tmpfs), the single-generation `.bak` window, and that read-whole-file is fine for
  small state. *(§4.3)*
- **A8 — D6 / time.** Phase-1 systemd unit orders `After=time-sync.target` (no RTC
  on headless Pi → wrong-day risk at boot); adopt `PIRATE_RADIO_TZ`; no pip
  `tzdata` dep needed on Bookworm. *(§4.2)*
- **A9 — Catalog forward notes.** Eager scan acceptable now; Phase-1 mtime-cached
  rescan for SD latency; `rglob` collapses nested subfolders into the top-level
  group — **document/log** it so flattening isn't silent. *(§4.6)*
- **A10 — Minors.** `Track.year` → `ge=1000` (or document the loose bound);
  document grid `name` stem-fallback as a decision; `FixedClock` uses `cast`/guard
  not `assert` (`-O` safety); note the `StateCorruptionError`→regenerate consumer is
  Phase 1, so "never crash-loop" is fully real only once Phase 1 wires it.

### 10.4 Accepted as-is (strengths)
Copy-then-replace `.bak` ordering + `BaseException` tmp cleanup; discriminated
unions + `extra="forbid"`; `yaml.safe_load` + `!!python` rejection; injected
resolver/clock determinism; dependency-sorted TDD order; minimal ARM-clean deps
(`pydantic`, `mutagen`, `PyYAML`). All code-level API usage Fact-Checker-verified.
