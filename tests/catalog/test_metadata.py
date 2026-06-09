"""RED tests for ``pirate_radio.catalog.metadata`` — from Phase 0 plan §4.5 / §6.4.

Tests first (strict spec-driven TDD): best-effort metadata extraction. Real mutagen
on real tiny WAVs (no mocks). A5d: the tagged-file test asserts the actual extracted
title/artist/year.

Folded in from the panel review:
  - `_first` dialect coverage: Vorbis (lowercase, list values) + MP4 (\\xa9 keys),
    not only ID3 — an ID3-only impl must fail (Devil's Advocate, BLOCKING). No
    FLAC/M4A encoder is available in CI, so the dialect contract is pinned directly
    on `_first` rather than via a binary fixture.
  - `_parse_year` on messy/garbage dates, incl. an out-of-range guard (QA, A10).
  - read_metadata swallows mutagen exceptions on recognized-but-malformed files
    (Devil's Advocate) and returns None for an opens-but-zero-duration file (Old Man/QA).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

import pirate_radio.catalog.metadata as md
from pirate_radio.catalog.metadata import _first, read_metadata
from pirate_radio.yeartag import parse_year as _parse_year


def test_reads_duration_from_real_wav(content_tree: Path) -> None:
    meta = read_metadata(content_tree / "classical" / "track0.wav")
    assert meta is not None
    assert meta.duration > 0


def test_sparse_tags_are_none_not_skipped(content_tree: Path) -> None:
    # Untagged silence: returned best-effort with None tags, NOT skipped (§9.3).
    meta = read_metadata(content_tree / "classical" / "track0.wav")
    assert meta is not None
    assert meta.title is None and meta.artist is None and meta.album is None


def test_extracts_real_tags_from_tagged_file(tagged_wav: Path) -> None:
    # A5d: assert the real extracted values, not merely that a meta object exists.
    meta = read_metadata(tagged_wav)
    assert meta is not None
    assert meta.title == "Clair de Lune"
    assert meta.artist == "Debussy"
    assert meta.album == "Suite"
    assert meta.year == 1905


def test_corrupt_file_returns_none(tmp_path: Path) -> None:
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"not audio")
    assert read_metadata(bad) is None


def test_missing_file_returns_none(tmp_path: Path) -> None:
    assert read_metadata(tmp_path / "nope.flac") is None


def test_read_metadata_swallows_mutagen_exceptions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A recognized-but-malformed file makes mutagen *raise* (not return None). The
    # scanner relies on read_metadata never propagating; force the broad-except path.
    def boom(_path: object) -> object:
        raise RuntimeError("mutagen blew up on a malformed-but-recognized file")

    monkeypatch.setattr(md.mutagen, "File", boom)
    assert read_metadata(tmp_path / "whatever.flac") is None


def test_opens_but_zero_duration_returns_none(
    tmp_path: Path, make_wav: Callable[..., Path]
) -> None:
    # A 0-frame WAV opens fine but has info.length == 0 -> unusable -> None (skip).
    p = make_wav(tmp_path / "silent0.wav", seconds=0)
    assert read_metadata(p) is None


def test_first_handles_id3_vorbis_and_mp4_key_spellings() -> None:
    # The dialect contract (§4.5): one helper resolves ID3 (TIT2), Vorbis (lowercase
    # list values), and MP4 (\xa9-prefixed) spellings, and skips empty values.
    keys = ("title", "TIT2", "\xa9nam")
    assert _first({"title": ["Vorbis Title"]}, keys) == "Vorbis Title"  # Vorbis list
    assert _first({"\xa9nam": ["Mp4 Title"]}, keys) == "Mp4 Title"  # MP4
    assert _first({"TIT2": "ID3 Title"}, keys) == "ID3 Title"  # ID3 (frame/str)
    assert _first({"title": [""]}, keys) is None  # empty -> skipped
    assert _first({}, keys) is None  # absent -> None


def test_parse_year_extracts_from_messy_dates() -> None:
    assert _parse_year("1905") == 1905
    assert _parse_year("2021-03-04") == 2021  # ISO date -> year
    assert _parse_year("03/12/1968") == 1968  # slash date -> year
    assert _parse_year("0000") is None  # implausible year guarded (A10 agreement)
    assert _parse_year("unknown") is None
    assert _parse_year("") is None
    assert _parse_year(None) is None
