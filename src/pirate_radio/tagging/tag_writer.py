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
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pirate_radio.errors import TaggingFatal
from pirate_radio.tagging.models import TagPlan

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
    shutil.copy2(path, tmp)  # preserve the audio bytes + mtime; tags are written onto the copy
    try:
        write_tags(tmp, changes)
        with open(tmp, "rb") as handle:
            os.fsync(handle.fileno())  # ensure the tag bytes are on disk before the rename
        os.replace(tmp, path)  # atomic same-filesystem replace (never a partial original)
    except BaseException:
        tmp.unlink(missing_ok=True)  # a failed/interrupted write never leaves a stray temp
        raise


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
