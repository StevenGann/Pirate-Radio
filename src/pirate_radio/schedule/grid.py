"""Grid models, YAML loader, day-of-week resolution, and fail-fast validation.

§8.2 format + resolution order; §8.3 validation (contiguous 00:00->24:00 tiling,
start < end, group -> non-empty content folder, required name). A bad grid fails
loudly here, never silently at runtime.

24:00 is modeled as ``time(0, 0)`` because ``datetime.time`` has no 24:00; per the
Q3 review decision it is legal ONLY as the final slot's ``end``. A single
``00:00->00:00`` slot is "all day"; any other midnight-end (a non-final slot, or two
all-day slots) and any zero-length slot are rejected.
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
    name: str = Field(min_length=1)  # required (§8.3)
    tagline: str | None = None  # optional
    description: str | None = None  # optional

    @model_validator(mode="after")
    def _start_before_end(self) -> Slot:
        # end == 00:00 is the special "24:00" end-of-day marker (tiling enforces it
        # appears only on the final slot); otherwise a zero/negative span is invalid.
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
    """Resolve which grid file applies for ``weekday`` (0=Mon..6=Sun) per §8.2.

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

    Uses ``yaml.safe_load`` (never load/FullLoader) so a grid file cannot execute
    code. The cross-folder check (group -> non-empty subfolder) is done by
    ``validate_grid_against_catalog`` because it needs the catalog.
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
    except Exception as exc:  # pydantic ValidationError, bad time strings, etc.
        raise GridValidationError(f"{path}: {exc}") from exc

    _validate_tiling(grid, path)
    return grid


def _validate_tiling(grid: Grid, path: Path) -> None:
    """Slots must tile 00:00 -> 24:00 contiguously, no gaps/overlaps (§8.3)."""
    slots = grid.slots
    if slots[0].start != _MIDNIGHT:
        raise GridValidationError(f"{path}: first slot must start at 00:00, got {slots[0].start}")

    # Q3: the 24:00 (==00:00) end-marker is legal ONLY on the final slot. A non-final
    # slot ending at midnight (incl. two all-day slots) would otherwise tile via the
    # pairwise check below yet be semantically broken.
    for slot in slots[:-1]:
        if slot.end == _MIDNIGHT:
            raise GridValidationError(
                f"{path}: only the final slot may end at 24:00 (00:00); '{slot.name}' does not"
            )

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
