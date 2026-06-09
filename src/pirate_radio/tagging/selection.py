"""PURE tag selection (Phase 5, P5-2) — the corruption-safety heart of the offline tagger.

Three deterministic (R19), IO-free functions:
- ``best_match`` — the AcoustID candidate to trust, or ``None`` below the confidence floor (so the
  caller can skip the MusicBrainz lookup AND write nothing).
- ``merge_tags`` — the per-field policy: **fill missing only** by default, ``force`` overwrites, but
  **never write a missing/blank value over a present one**, and never a redundant identical write.
- ``choose_best`` — the AUTHORITATIVE gate the writer's plan comes from: it re-checks the floor
  (below-floor / empty → a no-op ``TagPlan``), so a below-confidence match can never corrupt a file
  even if the orchestrator already fetched its recording (H-T2 — enforced here, not by discipline).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from pirate_radio.tagging.models import AcoustIdMatch, RecordingMetadata, TagPlan

# Conservative AcoustID confidence floor: below this, the match is not trusted to touch a file. A
# wrong fill is worse than no fill (the radio tolerates sparse tags, §9.3) — H-T2.
_MIN_ACOUSTID_SCORE = 0.85

_FIELDS = ("title", "artist", "album", "year")


def _present(value: str | int | None) -> bool:
    """A field counts as present only if non-None and (for text) non-blank — a whitespace tag is
    effectively missing, and a blank candidate is 'no value' that must never be written."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def best_match(
    matches: Sequence[AcoustIdMatch], *, min_score: float = _MIN_ACOUSTID_SCORE
) -> AcoustIdMatch | None:
    """The match to trust: highest score, ties broken by lexicographically lowest ``recording_id``
    (deterministic, input-order-independent, R19). ``None`` if empty or the best is sub-floor."""
    if not matches:
        return None
    # max by score, then by REVERSED id so the lowest id wins the tie (sort key negates via min-id).
    best = min(matches, key=lambda m: (-m.score, m.recording_id))
    return best if best.score >= min_score else None


def merge_tags(
    recording: RecordingMetadata,
    existing: RecordingMetadata,
    *,
    path: Path,
    force: bool = False,
) -> TagPlan:
    """PURE field merge → a ``TagPlan`` of ONLY the changed fields. Per field: take the candidate
    only if present (non-blank) AND (``force`` OR the existing field is missing) AND it differs
    from the current. Never erases a present field; never writes a blank; never churns an equal."""
    changes: dict[str, str | int] = {}
    for field in _FIELDS:
        candidate = getattr(recording, field)
        current = getattr(existing, field)
        if not _present(candidate):
            continue  # MB had nothing usable -> never erase/blank a field
        if candidate == current:
            continue  # already correct -> no redundant write
        if force or not _present(current):
            changes[field] = candidate
    return TagPlan.model_validate({"path": path, **changes})


def choose_best(
    matches: Sequence[AcoustIdMatch],
    recording: RecordingMetadata,
    existing: RecordingMetadata,
    *,
    path: Path,
    force: bool = False,
    min_score: float = _MIN_ACOUSTID_SCORE,
) -> TagPlan:
    """The authoritative plan: if no match clears the confidence floor, a NO-OP ``TagPlan`` (write
    nothing) — even when ``recording`` is perfect. Otherwise the ``merge_tags`` policy. Re-checking
    the floor here makes the corruption gate a property of selection, not orchestrator ordering."""
    if best_match(matches, min_score=min_score) is None:
        return TagPlan(path=path)
    return merge_tags(recording, existing, path=path, force=force)
