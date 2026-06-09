"""The offline tagger orchestration (Phase 5, P5-7) — walk the library and tag each file, isolated.

`tag_library` walks the content tree in STABLE order and runs each file through the pipeline:
skip-tagged gate → fingerprint → AcoustID → (confident?) MusicBrainz → choose_best → atomic write.
Every file is ISOLATED — a raising file is logged (scrubbed) and the batch continues, so one bad
file never aborts a long run (H-T4). `dry_run` writes nothing, a deterministic `--limit` caps the
run, and the process drops to low CPU/IO priority once at the start so a tag run can't starve a live
broadcast (H-T6/RPi). All collaborators are injected seams → CI-tested with fakes, no network or
binary. A `TagSummary` (tagged/skipped/failed/total) is returned and logged for the operator.
"""

from __future__ import annotations

import contextlib
import logging
import os
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pirate_radio.errors import TaggingError
from pirate_radio.scrub import scrub_secrets
from pirate_radio.tagging.models import AcoustIdMatch, Fingerprint, RecordingMetadata, TagPlan
from pirate_radio.tagging.selection import _MIN_ACOUSTID_SCORE, best_match, choose_best
from pirate_radio.tagging.tag_writer import apply_tag_plan, read_existing_tags

logger = logging.getLogger(__name__)

_AUDIO_EXTS = {".flac", ".mp3", ".ogg", ".opus", ".m4a", ".aac", ".wma", ".wav"}


class Fingerprinter(Protocol):
    def fingerprint(self, path: Path) -> Fingerprint: ...


class AcoustIdLookup(Protocol):
    def lookup(self, fingerprint: Fingerprint) -> tuple[AcoustIdMatch, ...]: ...


class MusicBrainzLookup(Protocol):
    def recording(self, mbid: str) -> RecordingMetadata: ...


@dataclass(frozen=True)
class TagSummary:
    tagged: int
    skipped: int
    failed: int
    total: int


def _has(value: str | None) -> bool:
    return bool(value and value.strip())


def _walk_audio(content_dir: Path) -> list[Path]:
    """Audio files under ``content_dir`` in STABLE sorted order (so ``--limit`` is stable)."""
    return sorted(
        p for p in content_dir.rglob("*") if p.is_file() and p.suffix.lower() in _AUDIO_EXTS
    )


def _default_lower_priority() -> None:  # pragma: no cover (mutates the real process priority)
    with contextlib.suppress(OSError, AttributeError):
        os.nice(19)  # de-prioritise CPU so a live broadcast keeps its cores (H-T6)
    with contextlib.suppress(OSError):  # best-effort idle IO class (no shell; ionice may be absent)
        subprocess.run(["ionice", "-c3", "-p", str(os.getpid())], check=False, capture_output=True)


def tag_library(
    *,
    content_dir: Path,
    fingerprinter: Fingerprinter,
    acoustid: AcoustIdLookup,
    musicbrainz: MusicBrainzLookup,
    read_tags: Callable[[Path], RecordingMetadata] = read_existing_tags,
    write: Callable[..., bool] = apply_tag_plan,
    walk: Callable[[Path], Iterable[Path]] = _walk_audio,
    lower_priority: Callable[[], None] = _default_lower_priority,
    force: bool = False,
    dry_run: bool = False,
    limit: int | None = None,
    min_score: float = _MIN_ACOUSTID_SCORE,
) -> TagSummary:
    lower_priority()  # once, before the long run — keep a live broadcast's cores/IO (H-T6)
    paths = list(walk(content_dir))
    if limit is not None:
        paths = paths[:limit]
    tagged = skipped = failed = 0
    for path in paths:
        try:
            wrote = _tag_one(
                path,
                fingerprinter=fingerprinter,
                acoustid=acoustid,
                musicbrainz=musicbrainz,
                read_tags=read_tags,
                write=write,
                force=force,
                dry_run=dry_run,
                min_score=min_score,
            )
        except TaggingError as exc:
            logger.warning("tagging failed for %s: %s", path, scrub_secrets(str(exc)))
            failed += 1
        except Exception as exc:  # noqa: BLE001 — per-file isolation: one bad file never aborts
            logger.critical("tagging crashed for %s: %s", path, scrub_secrets(str(exc)))
            failed += 1
        else:
            tagged += 1 if wrote else 0
            skipped += 0 if wrote else 1
    summary = TagSummary(tagged=tagged, skipped=skipped, failed=failed, total=len(paths))
    logger.info(
        "tagging complete: %d tagged, %d skipped, %d failed of %d",
        summary.tagged,
        summary.skipped,
        summary.failed,
        summary.total,
    )
    return summary


def _tag_one(
    path: Path,
    *,
    fingerprinter: Fingerprinter,
    acoustid: AcoustIdLookup,
    musicbrainz: MusicBrainzLookup,
    read_tags: Callable[[Path], RecordingMetadata],
    write: Callable[..., bool],
    force: bool,
    dry_run: bool,
    min_score: float,
) -> bool:
    existing = read_tags(path)
    if not force and _has(existing.title) and _has(existing.artist):
        return False  # skip-tagged gate: cheap, BEFORE the expensive fingerprint
    fingerprint = fingerprinter.fingerprint(path)
    matches = acoustid.lookup(fingerprint)
    chosen = best_match(matches, min_score=min_score)
    if chosen is None:
        return False  # no confident match -> no MusicBrainz lookup, write nothing
    recording = musicbrainz.recording(chosen.recording_id)
    plan: TagPlan = choose_best(
        matches, recording, existing, path=path, force=force, min_score=min_score
    )
    return write(plan, dry_run=dry_run)
