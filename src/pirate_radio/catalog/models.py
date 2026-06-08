"""The Track model (§13): one playable file, tagged by its parent group folder."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class Track(BaseModel):
    """A single audio file indexed by the catalog scanner.

    ``duration`` comes from metadata and is treated as exact for scheduling (§7).
    Tag fields are optional: a sparsely tagged file is indexed best-effort, never
    skipped (§9.3). ``year`` is bounded so a nonsense value (e.g. 0) is rejected and
    the schema agrees with what ``metadata._parse_year`` can emit (amendment A10).
    """

    model_config = ConfigDict(frozen=True)

    path: Path
    group: str = Field(min_length=1)  # parent (top-level) folder name
    duration: float = Field(gt=0.0)  # seconds; a 0/negative duration is unplayable
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    year: int | None = Field(default=None, ge=1, le=9999)
