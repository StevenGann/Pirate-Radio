"""RED tests for ``pirate_radio.tagging.selection`` — Phase-5 plan P5-2 (the correctness heart).

Two PURE functions (R19, deterministic): ``best_match`` picks the AcoustID candidate to trust (or
None below the confidence floor), and ``merge_tags`` builds the ``TagPlan`` — **fill-not-overwrite**
by default, ``force`` overwrites, and a low-confidence or fully-tagged case yields a NO-OP plan
so good tags are never clobbered (H-T2). The corruption-safety of the whole tool lives here.
"""

from __future__ import annotations

from pathlib import Path

from pirate_radio.tagging.models import AcoustIdMatch, RecordingMetadata, TagPlan
from pirate_radio.tagging.selection import (
    _MIN_ACOUSTID_SCORE,
    best_match,
    choose_best,
    merge_tags,
)

_PATH = Path("/lib/x/a.flac")


def _m(rid: str, score: float) -> AcoustIdMatch:
    return AcoustIdMatch(recording_id=rid, score=score)


# ---- best_match: confidence floor + deterministic tie-break --------------------------------
def test_best_match_empty_is_none() -> None:
    assert best_match([]) is None


def test_best_match_below_floor_is_none() -> None:
    # a low-confidence match must NOT be trusted -> caller writes nothing (H-T2)
    assert best_match([_m("a", _MIN_ACOUSTID_SCORE - 0.01)]) is None


def test_best_match_at_the_floor_is_accepted() -> None:
    assert best_match([_m("a", _MIN_ACOUSTID_SCORE)]) == _m("a", _MIN_ACOUSTID_SCORE)


def test_best_match_picks_highest_score() -> None:
    chosen = best_match([_m("a", 0.90), _m("b", 0.97), _m("c", 0.88)])
    assert chosen is not None and chosen.recording_id == "b"


def test_best_match_tie_breaks_on_lowest_mbid() -> None:
    # deterministic (R19): equal scores -> lexicographically lowest recording_id, never input order
    chosen = best_match([_m("zzz", 0.95), _m("aaa", 0.95), _m("mmm", 0.95)])
    assert chosen is not None and chosen.recording_id == "aaa"


def test_best_match_is_input_order_independent() -> None:
    # R19: every permutation of equal-score matches yields the SAME pick (not input order)
    import itertools

    picks = {
        best_match(list(p)).recording_id  # type: ignore[union-attr]
        for p in itertools.permutations([_m("b", 0.9), _m("a", 0.9), _m("c", 0.9)])
    }
    assert picks == {"a"}  # always the lowest MBID regardless of order


def test_best_match_at_floor_with_a_tie_picks_lowest_mbid() -> None:
    chosen = best_match([_m("y", _MIN_ACOUSTID_SCORE), _m("x", _MIN_ACOUSTID_SCORE)])
    assert chosen is not None and chosen.recording_id == "x"


def test_best_match_honours_an_explicit_min_score() -> None:
    # a hardcoded-floor impl ignoring the kwarg would fail this
    assert best_match([_m("a", 0.5)], min_score=0.4) == _m("a", 0.5)
    assert best_match([_m("a", 0.5)], min_score=0.6) is None


def test_best_match_default_floor_is_the_named_constant() -> None:
    assert _MIN_ACOUSTID_SCORE == 0.85  # conservative AcoustID confidence floor


# ---- merge_tags: fill-not-overwrite (the default) -----------------------------------------
def test_merge_fills_only_missing_fields() -> None:
    recording = RecordingMetadata(title="Real Title", artist="Band", album="LP", year=1984)
    existing = RecordingMetadata(title="Real Title", artist="Band")  # album/year missing
    plan = merge_tags(recording, existing, path=_PATH)
    assert plan.changes() == {"album": "LP", "year": 1984}  # only the gaps filled


def test_merge_never_overwrites_a_present_field_in_fill_mode() -> None:
    recording = RecordingMetadata(title="MB Title", artist="MB Artist")
    existing = RecordingMetadata(title="My Careful Title", artist="My Artist")
    assert merge_tags(recording, existing, path=_PATH).is_noop  # present fields untouched


def test_merge_treats_blank_string_as_missing() -> None:
    recording = RecordingMetadata(title="Filled")
    existing = RecordingMetadata(title="   ")  # whitespace-only tag is effectively missing
    assert merge_tags(recording, existing, path=_PATH).changes() == {"title": "Filled"}


def test_merge_never_writes_empty_over_present() -> None:
    recording = RecordingMetadata(title=None, artist=None)  # MB had nothing
    existing = RecordingMetadata(title="Keep", artist="Keep")
    assert merge_tags(recording, existing, path=_PATH).is_noop  # never erase good tags


def test_merge_skips_a_redundant_identical_write() -> None:
    recording = RecordingMetadata(album="Same")
    existing = RecordingMetadata(album="Same")
    assert merge_tags(recording, existing, path=_PATH).is_noop  # no churn for an equal value


# ---- merge_tags: force overwrites ---------------------------------------------------------
def test_force_overwrites_present_fields() -> None:
    recording = RecordingMetadata(title="Canonical", year=1991)
    existing = RecordingMetadata(title="Wrong", year=2000)
    plan = merge_tags(recording, existing, path=_PATH, force=True)
    assert plan.changes() == {"title": "Canonical", "year": 1991}


def test_force_still_never_erases_with_a_missing_candidate() -> None:
    # force overwrites, but a None candidate is "MB had nothing" -> still never erase (H-T2)
    recording = RecordingMetadata(title="New", artist=None)
    existing = RecordingMetadata(title="Old", artist="Keep")
    plan = merge_tags(recording, existing, path=_PATH, force=True)
    assert plan.changes() == {"title": "New"}  # artist preserved


def test_force_fills_missing_and_overwrites_present_together() -> None:
    # QA/DA: force must STILL fill gaps, not only overwrite present (partial-file matrix)
    recording = RecordingMetadata(title="Canon", artist="A", album="LP", year=1990)
    existing = RecordingMetadata(title="Wrong", album="OldLP")  # 2 present, artist/year gap
    plan = merge_tags(recording, existing, path=_PATH, force=True)
    assert plan.changes() == {"title": "Canon", "artist": "A", "album": "LP", "year": 1990}


def test_force_skips_a_redundant_equal_value() -> None:
    # even under force, an equal value is no churn (don't re-touch the file for nothing)
    plan = merge_tags(
        RecordingMetadata(title="Same"), RecordingMetadata(title="Same"), path=_PATH, force=True
    )
    assert plan.is_noop


def test_never_erases_album_or_year_with_a_missing_candidate_even_forced() -> None:
    # DA: the never-erase guard must hold for EVERY field (album/year), in force mode too
    recording = RecordingMetadata()  # MB returned nothing
    existing = RecordingMetadata(album="Keep", year=1999)
    assert merge_tags(recording, existing, path=_PATH, force=True).is_noop


def test_never_writes_a_blank_candidate_over_present_or_into_a_gap() -> None:
    # DA: a whitespace/empty CANDIDATE is "no value" — never written (fill or force)
    blank = RecordingMetadata(title="   ", artist="")
    assert merge_tags(blank, RecordingMetadata(), path=_PATH).is_noop  # not filled into a gap
    present = RecordingMetadata(title="Keep", artist="Keep")
    assert merge_tags(blank, present, path=_PATH, force=True).is_noop  # not written over present


# ---- choose_best: the authoritative corruption gate (floor enforced at the unit) ----
def test_choose_best_below_floor_is_noop_even_with_perfect_metadata() -> None:
    # THE H-T2 invariant: a below-confidence match writes NOTHING, even if the recording is perfect
    matches = [_m("mbid", _MIN_ACOUSTID_SCORE - 0.01)]
    perfect = RecordingMetadata(title="Perfect", artist="Band", album="LP", year=1984)
    plan = choose_best(matches, perfect, RecordingMetadata(), path=_PATH)
    assert plan.is_noop and plan.path == _PATH


def test_choose_best_empty_matches_is_noop() -> None:
    perfect = RecordingMetadata(title="Perfect", artist="Band")
    assert choose_best([], perfect, RecordingMetadata(), path=_PATH).is_noop


def test_choose_best_above_floor_merges() -> None:
    matches = [_m("mbid", 0.96)]
    recording = RecordingMetadata(title="Real", artist="Band")
    plan = choose_best(matches, recording, RecordingMetadata(), path=_PATH)
    assert plan.changes() == {"title": "Real", "artist": "Band"}


def test_choose_best_threads_force() -> None:
    matches = [_m("mbid", 0.96)]
    recording = RecordingMetadata(title="Canon")
    plan = choose_best(matches, recording, RecordingMetadata(title="Wrong"), path=_PATH, force=True)
    assert plan.changes() == {"title": "Canon"}


def test_merge_carries_the_path() -> None:
    plan = merge_tags(RecordingMetadata(title="T"), RecordingMetadata(), path=_PATH)
    assert plan.path == _PATH and isinstance(plan, TagPlan)
