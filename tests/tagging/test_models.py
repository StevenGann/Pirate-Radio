"""RED tests for ``pirate_radio.tagging.models`` — Phase-5 plan P5-1.

The frozen result types the offline tagger passes between its pure stages (R16) + the
``TaggingError`` taxonomy whose sub-leaves let the backoff branch (transient/throttled vs fatal).
``TagPlan`` is
the merge OUTPUT: only the fields it carries (non-None) are written; an all-None plan is a no-op
(below-threshold matches, or a fully-tagged file, produce one — never a destructive empty write).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pirate_radio.errors import PirateRadioError
from pirate_radio.tagging.models import (
    AcoustIdMatch,
    Fingerprint,
    RecordingMetadata,
    TaggingError,
    TaggingFatal,
    TaggingThrottled,
    TaggingUnavailable,
    TagPlan,
)


# ---- error taxonomy ------------------------------------------------------------------------
def test_tagging_errors_are_pirate_radio_errors() -> None:
    assert issubclass(TaggingError, PirateRadioError)
    for leaf in (TaggingUnavailable, TaggingThrottled, TaggingFatal):
        assert issubclass(leaf, TaggingError)


def test_throttled_carries_optional_retry_after() -> None:
    # the backoff path honors Retry-After then re-arms the limiter (H-T1)
    assert TaggingThrottled("429", retry_after_seconds=2.5).retry_after_seconds == 2.5
    assert TaggingThrottled("429").retry_after_seconds is None


# ---- frozen value types --------------------------------------------------------------------
def test_fingerprint_is_frozen_and_typed() -> None:
    fp = Fingerprint(duration=212.0, fingerprint="AQAAA...")
    assert fp.duration == 212.0 and fp.fingerprint.startswith("AQAA")
    with pytest.raises(Exception):  # frozen (pydantic ValidationError on mutation)
        fp.duration = 1.0  # type: ignore[misc]


def test_acoustid_match_clamps_score_range() -> None:
    AcoustIdMatch(recording_id="mbid-1", score=0.83)
    for bad in (-0.1, 1.1):
        with pytest.raises(Exception):
            AcoustIdMatch(recording_id="mbid-1", score=bad)  # score is a 0..1 confidence


def test_recording_metadata_tolerates_missing_fields_and_bounds_year() -> None:
    # MusicBrainz may omit fields; sparse is fine (§9.3). year is bounded like Track (A10).
    sparse = RecordingMetadata()
    assert sparse.title is None and sparse.artist is None
    RecordingMetadata(title="T", artist="A", album="Al", year=1991)
    for bad in (0, 10000):
        with pytest.raises(Exception):
            RecordingMetadata(year=bad)


# ---- TagPlan: the merge output -------------------------------------------------------------
def test_tagplan_noop_when_no_fields() -> None:
    plan = TagPlan(path=Path("/lib/x/a.flac"))
    assert plan.is_noop and plan.changes() == {}


def test_tagplan_changes_lists_only_set_fields() -> None:
    plan = TagPlan(path=Path("/lib/x/a.flac"), title="Song", year=1984)
    assert not plan.is_noop
    assert plan.changes() == {"title": "Song", "year": 1984}  # album/artist omitted (unchanged)
