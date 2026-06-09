"""Best-effort metadata extraction via mutagen (§7), tolerant of sparse tags (§9.3).

Returns a ``TrackMetadata`` for any file mutagen can open that yields a positive
duration; returns ``None`` (so the caller can skip+log) for unreadable/corrupt files
or files with no usable duration. Never raises on a bad file — bad input is data,
not an exception (boundary-validation rule).
"""

from __future__ import annotations

from pathlib import Path

import mutagen
from pydantic import BaseModel, ConfigDict

from pirate_radio.yeartag import parse_year


class TrackMetadata(BaseModel):
    """Raw, normalized metadata for one file. ``duration`` is required and > 0."""

    model_config = ConfigDict(frozen=True)

    duration: float
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    year: int | None = None


def read_metadata(path: Path) -> TrackMetadata | None:
    """Read metadata for one file. Return None if it cannot be used.

    None means: mutagen could not open it, it has no audio stream, or duration is
    missing/non-positive. The scanner logs and skips on None (§7); it does NOT skip
    merely sparse tags (§9.3).
    """
    try:
        audio = mutagen.File(path)  # mutagen treated as untyped (mypy follow_imports=skip)
    except Exception:  # noqa: BLE001 - mutagen raises a zoo of errors on corrupt files
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
        year=parse_year(_first(tags, ("date", "year", "TDRC", "\xa9day"))),
    )


def _first(tags: object, keys: tuple[str, ...]) -> str | None:
    """Return the first present, non-empty tag value across known key spellings.

    Handles ID3 (``TIT2``), Vorbis (``title``), and MP4 (``\\xa9nam``) spellings
    uniformly. Vorbis/MP4 tag values are lists (take element 0); ID3 frames stringify
    directly.
    """
    if not hasattr(tags, "get"):
        return None
    for key in keys:
        value = tags.get(key)
        if value is None:
            continue
        text = str(value[0]) if isinstance(value, list) and value else str(value)
        text = text.strip()
        if text:
            return text
    return None
