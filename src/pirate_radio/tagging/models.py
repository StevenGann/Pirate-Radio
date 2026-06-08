"""Frozen result types for the offline tagger (Phase 5, R16) — passed between the pure stages.

``Fingerprint`` (from ``fpcalc``) → ``AcoustIdMatch`` tuples (AcoustID) → ``RecordingMetadata`` (one
MusicBrainz recording) → ``TagPlan`` (the merge output: the field changes to write). The error
taxonomy (``TaggingError`` + leaves) lives in ``errors.py`` and is re-exported here for convenience.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from pirate_radio.errors import (
    TaggingError,
    TaggingFatal,
    TaggingThrottled,
    TaggingUnavailable,
)

__all__ = [
    "AcoustIdMatch",
    "Fingerprint",
    "RecordingMetadata",
    "TagPlan",
    "TaggingError",
    "TaggingFatal",
    "TaggingThrottled",
    "TaggingUnavailable",
]

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class Fingerprint(BaseModel):
    """A Chromaprint acoustic fingerprint + the decoded duration ``fpcalc`` reports (both go to the
    AcoustID lookup, which scores against duration)."""

    model_config = _FROZEN
    duration: float = Field(gt=0.0)
    fingerprint: str = Field(min_length=1)


class AcoustIdMatch(BaseModel):
    """One AcoustID candidate: a MusicBrainz recording id + the lookup confidence (0..1)."""

    model_config = _FROZEN
    recording_id: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)


class RecordingMetadata(BaseModel):
    """The fields the catalog/grounding cares about, from one MusicBrainz recording. All optional —
    a sparse recording is fine (§9.3); ``year`` is bounded like ``Track`` (A10)."""

    model_config = _FROZEN
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    year: int | None = Field(default=None, ge=1, le=9999)


class TagPlan(BaseModel):
    """The merge OUTPUT: which tag fields to write to ``path``. A ``None`` field means LEAVE IT
    UNCHANGED — only the set fields are written, so a below-threshold match or a fully-tagged file
    yields an all-None (``is_noop``) plan and never an empty/destructive write (H-T2)."""

    model_config = _FROZEN
    path: Path
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    year: int | None = None

    @property
    def is_noop(self) -> bool:
        return all(v is None for v in (self.title, self.artist, self.album, self.year))

    def changes(self) -> dict[str, str | int]:
        """The non-None fields to write, as a flat mapping (the writer applies exactly these)."""
        out: dict[str, str | int] = {}
        if self.title is not None:
            out["title"] = self.title
        if self.artist is not None:
            out["artist"] = self.artist
        if self.album is not None:
            out["album"] = self.album
        if self.year is not None:
            out["year"] = self.year
        return out
