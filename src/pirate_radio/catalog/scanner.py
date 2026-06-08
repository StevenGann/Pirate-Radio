"""Catalog scanner (§7): content_dir -> one group per top-level subfolder.

Per-station libraries (D3). Deterministic ordering (sorted) so a (tree) -> Catalog
mapping is reproducible — Phase-1 seeded generation (R19) depends on this. Unreadable
files are skipped and logged, never fatal; a missing content_dir, or one with zero
non-empty groups, is fatal (CatalogError) because §12 requires >= 1 non-empty group.

Nested subfolders collapse into their top-level group (amendment A9): a file under
``oldies/1960s/`` is indexed under ``oldies``.
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

# Files mutagen can plausibly read; unknown suffixes are skipped without opening
# (avoids opening cover.jpg / .cue / .nfo sidecars on slow SD — amendment A9 note).
_AUDIO_SUFFIXES = frozenset({".mp3", ".flac", ".ogg", ".oga", ".m4a", ".mp4", ".wav", ".opus"})


class Catalog(BaseModel):
    """In-memory index of a station's tracks, grouped by folder name.

    Frozen value object: rescanning produces a *new* Catalog rather than mutating
    this one. ``tracks`` is the flat list, stably sorted by ``(group, path)`` — the
    persisted/iteration contract.
    """

    model_config = ConfigDict(frozen=True)

    content_dir: Path
    tracks: tuple[Track, ...]

    def groups(self) -> dict[str, tuple[Track, ...]]:
        """Return group name -> its tracks (derived from the sorted track list)."""
        out: dict[str, list[Track]] = {}
        for track in self.tracks:
            out.setdefault(track.group, []).append(track)
        return {name: tuple(items) for name, items in out.items()}

    def group_names(self) -> frozenset[str]:
        return frozenset(t.group for t in self.tracks)

    def is_group_non_empty(self, group: str) -> bool:
        """True iff ``group`` exists with >= 1 track — the §8.3/§12 check."""
        return any(t.group == group for t in self.tracks)


def scan_catalog(content_dir: Path) -> Catalog:
    """Scan ``content_dir`` into a Catalog. Fail fast if it yields no usable groups.

    One group per *top-level* subfolder; nested files inherit the top-level folder
    name as their group. Skips (logs) unreadable files and unknown suffixes.
    """
    content_dir = Path(content_dir)
    if not content_dir.is_dir():
        raise CatalogError(f"content_dir does not exist or is not a directory: {content_dir}")

    tracks: list[Track] = []
    for group_dir in sorted(p for p in content_dir.iterdir() if p.is_dir()):
        tracks.extend(_scan_group(group_dir, group_dir.name))

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
