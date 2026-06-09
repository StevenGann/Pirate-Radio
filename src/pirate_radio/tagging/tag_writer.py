"""Atomic tag write (Phase 5, P5-6) — the offline tagger's one destructive operation.

A ``TagPlan`` is applied by copying the file to a SAME-DIRECTORY temp, writing tags to the temp,
``fsync``-ing it, then an atomic ``os.replace`` over the original — so a power loss / Ctrl-C
mid-write never leaves a truncated file (H-T4/RPi); the same-filesystem temp makes the rename a true
atomic rename, not a copy+unlink. A no-op plan or ``--dry-run`` writes nothing.

The mutagen mapping (``TagPlan.changes()`` → easy keys, ``year`` → ``date``) is a thin adapter over
``mutagen.File(path, easy=True)``; only the real-container open (``_open_mutagen``) needs a codec —
so it is the lone hardware-smoke seam, and the atomicity + the mapping are unit-tested in CI.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pirate_radio.errors import TaggingFatal
from pirate_radio.tagging.models import RecordingMetadata, TagPlan

_YEAR_RE = re.compile(r"\b(\d{4})\b")

logger = logging.getLogger(__name__)

_TEMP_SUFFIX = ".pirate-tmp"
WriteTags = Callable[[Path, dict[str, str | int]], None]


def apply_tag_plan(
    plan: TagPlan, *, write_tags: WriteTags | None = None, dry_run: bool = False
) -> bool:
    """Apply ``plan`` atomically. Returns True iff the file was written. A no-op plan or ``dry_run``
    writes nothing (the latter logs the intended changes for the operator)."""
    if plan.is_noop:
        return False
    if dry_run:
        logger.info("[dry-run] would tag %s: %s", plan.path, plan.changes())
        return False
    _atomic_apply(plan.path, plan.changes(), write_tags or _mutagen_write)
    return True


def _atomic_apply(path: Path, changes: dict[str, str | int], write_tags: WriteTags) -> None:
    tmp = path.with_name(path.name + _TEMP_SUFFIX)  # same dir -> same filesystem -> atomic rename
    try:
        shutil.copy2(path, tmp)  # preserve the audio bytes + mtime; tags are written onto the copy
        write_tags(tmp, changes)
        with open(tmp, "rb") as handle:
            os.fsync(handle.fileno())  # the tag bytes are on disk before the rename
        os.replace(tmp, path)  # atomic same-filesystem replace (never a partial original)
    except BaseException:
        # ANY failure/interruption (incl. Ctrl-C between copy and replace) leaves no stray temp and
        # never touches the original — os.replace is the only mutation of `path` and it is atomic.
        tmp.unlink(missing_ok=True)
        raise
    _fsync_dir(path.parent)  # persist the rename itself (crash-safe on a power loss, RPi)


def _fsync_dir(directory: Path) -> None:
    """Best-effort ``fsync`` of a directory so an ``os.replace`` rename survives a power loss; some
    filesystems/platforms reject a directory fd — that is harmless, so errors are suppressed."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _open_mutagen(path: Path) -> Any:  # pragma: no cover (R20/R21: real container open needs codec)
    import mutagen  # lazy

    return mutagen.File(path, easy=True)  # type: ignore[attr-defined]  # File re-exported lazily


def _mutagen_write(path: Path, changes: dict[str, str | int]) -> None:
    """Map ``TagPlan.changes()`` onto mutagen easy keys and save. ``year`` → the ``date`` easy key
    (stringified). An unreadable container → ``TaggingFatal`` (skip the file)."""
    audio = _open_mutagen(path)
    if audio is None:
        raise TaggingFatal(f"mutagen cannot read {path} (unknown/corrupt container)")
    for field in ("title", "artist", "album"):
        if field in changes:
            audio[field] = [str(changes[field])]
    if "year" in changes:
        audio["date"] = [str(changes["year"])]
    audio.save()


def read_existing_tags(path: Path) -> RecordingMetadata:
    """Read a file's current tags into ``RecordingMetadata`` (for the skip-gate + the merge). An
    unreadable container is treated as untagged (``RecordingMetadata()``) — never an error here."""
    audio = _open_mutagen(path)
    if audio is None:
        return RecordingMetadata()

    def _first(key: str) -> str | None:
        value = audio.get(key)
        return value[0] if value else None

    date = _first("date")
    year_match = _YEAR_RE.search(date) if date else None
    year = int(year_match.group(1)) if year_match else None
    return RecordingMetadata(
        title=_first("title"),
        artist=_first("artist"),
        album=_first("album"),
        year=year if year is not None and 1 <= year <= 9999 else None,
    )
