"""RED tests for ``pirate_radio.dj.context`` — Phase 3 plan §3.2 / §4.2 (P3-1).

Tests first (strict spec-driven TDD): the typed, frozen, grounded ``DjContext`` tree
(R16 — no bare dicts) that the producer builds and ``dj/prompts.py`` turns into an
"invent nothing" instruction. ``TrackMeta`` carries a track's grounding facts (all
optional, §9.3 best-effort); ``BlockContext`` a programming block's; ``DjContext`` the
whole thing handed to ``TextGenerator.patter``.

The spine of P3-1: every model is FROZEN + ``extra="forbid"`` (R16); ``is_sparse`` is
True ONLY when title AND artist are both absent (a partially-tagged track is NOT sparse
— it still grounds best-effort, never a skip); the §9.2 example round-trips field-for-field.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from pirate_radio.dj.context import BlockContext, DjContext, TrackMeta


def _dt(hour: int) -> datetime:
    return datetime(2026, 6, 7, hour, 0, tzinfo=UTC)


def _ctx(**over: object) -> DjContext:
    base: dict[str, object] = {
        "kind": "intro",
        "persona": "A warm late-night host",
        "station_name": "PiRate One",
        "current_block": BlockContext(name="Late Night"),
    }
    base.update(over)
    return DjContext(**base)  # type: ignore[arg-type]


# ---- TrackMeta.is_sparse — the §9.3 best-effort discriminator ------------------------------
def test_is_sparse_true_only_when_title_and_artist_both_absent() -> None:
    assert TrackMeta().is_sparse is True


def test_is_sparse_false_when_title_only_present() -> None:
    assert TrackMeta(title="Clair de Lune").is_sparse is False  # partial is NOT sparse


def test_is_sparse_false_when_artist_only_present() -> None:
    assert TrackMeta(artist="Debussy").is_sparse is False


def test_is_sparse_false_when_both_present() -> None:
    assert TrackMeta(title="Clair de Lune", artist="Debussy").is_sparse is False


def test_is_sparse_ignores_album_and_year() -> None:
    # album/year without title/artist is still sparse — they don't anchor a spoken intro
    assert TrackMeta(album="Suite bergamasque", year=1905).is_sparse is True


def test_is_sparse_treats_empty_string_as_absent() -> None:
    # DA: the contract is a truthy test ("" == no tag), NOT `is None`; pin it so an `is None`
    # impl (which would call "" present) is killed, matching prompts.py's `if t.title:` guard.
    assert TrackMeta(title="").is_sparse is True
    assert TrackMeta(title="", artist="").is_sparse is True
    assert TrackMeta(title="X", artist="").is_sparse is False  # one real tag -> not sparse


# ---- frozen + extra-forbid (R16) on all three models --------------------------------------
def test_trackmeta_is_frozen() -> None:
    t = TrackMeta(title="X")
    with pytest.raises(ValidationError):
        t.title = "Y"  # type: ignore[misc]


def test_blockcontext_is_frozen() -> None:
    b = BlockContext(name="Late Night")
    with pytest.raises(ValidationError):
        b.name = "Morning"  # type: ignore[misc]


def test_djcontext_is_frozen() -> None:
    ctx = _ctx()
    with pytest.raises(ValidationError):
        ctx.kind = "outro"  # type: ignore[misc]


def test_trackmeta_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        TrackMeta(title="X", genre="jazz")  # type: ignore[call-arg]


def test_blockcontext_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        BlockContext(name="N", colour="blue")  # type: ignore[call-arg]


def test_djcontext_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        _ctx(mood="spooky")


# ---- required / bounded fields ------------------------------------------------------------
def test_blockcontext_name_required_non_empty() -> None:
    with pytest.raises(ValidationError):
        BlockContext(name="")


def test_djcontext_requires_kind_persona_station_non_empty() -> None:
    for empty in ("kind", "persona", "station_name"):
        with pytest.raises(ValidationError):
            _ctx(**{empty: ""})


def test_djcontext_current_block_is_required() -> None:
    with pytest.raises(ValidationError):
        DjContext(kind="intro", persona="P", station_name="S")  # type: ignore[call-arg]


def test_trackmeta_year_bounds_reject_nonsense() -> None:
    # consistency with Track.year / _parse_year (A10): a nonsense year can't ground a spoken
    # intro (e.g. "Year: 0"). Bounded ge=1, le=9999.
    with pytest.raises(ValidationError):
        TrackMeta(year=0)
    with pytest.raises(ValidationError):
        TrackMeta(year=10000)


def test_trackmeta_year_accepts_valid_range() -> None:
    assert TrackMeta(year=1).year == 1
    assert TrackMeta(year=9999).year == 9999


def test_trackmeta_optionals_default_none() -> None:
    t = TrackMeta()
    assert t.title is None and t.artist is None and t.album is None and t.year is None


# ---- defaults / optionals -----------------------------------------------------------------
def test_djcontext_optional_fields_default_to_none_and_empty_tuple() -> None:
    ctx = _ctx()
    assert ctx.station_tagline is None
    assert ctx.next_block is None
    assert ctx.track is None
    assert ctx.recent_tracks == ()
    assert isinstance(ctx.recent_tracks, tuple)


def test_blockcontext_optionals_default_none() -> None:
    b = BlockContext(name="Late Night")
    assert b.tagline is None and b.description is None and b.boundary_at is None


# ---- §9.2 example round-trips field-for-field ----------------------------------------------
def test_full_djcontext_round_trips_every_field() -> None:
    track = TrackMeta(title="Clair de Lune", artist="Debussy", album="Suite", year=1905)
    recent = (TrackMeta(title="Gymnopédie No.1", artist="Satie"),)
    current = BlockContext(
        name="Late Night", tagline="after dark", description="speak softly", boundary_at=_dt(2)
    )
    nxt = BlockContext(name="Sunrise", boundary_at=_dt(6))
    ctx = DjContext(
        kind="block_transition",
        persona="A warm late-night host",
        station_name="PiRate One",
        station_tagline="all killer no filler",
        current_block=current,
        next_block=nxt,
        track=track,
        recent_tracks=recent,
    )
    assert ctx.kind == "block_transition"
    assert ctx.persona == "A warm late-night host"
    assert ctx.station_name == "PiRate One"
    assert ctx.station_tagline == "all killer no filler"
    assert ctx.current_block.name == "Late Night"  # DA: every §9.2 field read back, none droppable
    assert ctx.current_block.tagline == "after dark"
    assert ctx.current_block.description == "speak softly"
    assert ctx.current_block.boundary_at == _dt(2)
    assert ctx.next_block is not None
    assert ctx.next_block.name == "Sunrise"
    assert ctx.next_block.boundary_at == _dt(6)
    assert ctx.track is not None
    assert ctx.track.title == "Clair de Lune"
    assert ctx.track.artist == "Debussy"
    assert ctx.track.album == "Suite"
    assert ctx.track.year == 1905
    assert ctx.recent_tracks[0].title == "Gymnopédie No.1"
    assert ctx.recent_tracks[0].artist == "Satie"


def test_recent_tracks_accepts_a_tuple_of_trackmeta() -> None:
    ctx = _ctx(recent_tracks=(TrackMeta(title="A"), TrackMeta(title="B")))
    assert len(ctx.recent_tracks) == 2


def test_recent_tracks_coerces_list_to_tuple() -> None:
    # immutability rule: a list arg must land as a tuple on the frozen model, never a mutable list
    ctx = _ctx(recent_tracks=[TrackMeta(title="A")])
    assert isinstance(ctx.recent_tracks, tuple)


def test_recent_tracks_rejects_non_trackmeta_elements() -> None:
    with pytest.raises(ValidationError):
        _ctx(recent_tracks=("notatrack",))
