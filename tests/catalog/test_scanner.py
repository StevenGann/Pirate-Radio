"""RED tests for ``pirate_radio.catalog.scanner`` — from Phase 0 plan §4.6 / §6.5.

Tests first (strict spec-driven TDD): the folder scanner and ``Catalog`` value
object. Amendments folded in:
  - A5c: determinism asserted against the actual sorted order AND an
    insertion-order-independent case (not the tautological scan()==scan()).
  - A5b: the unreadable-file skip path asserts a WARNING was logged (caplog).
  - A9: nested subfolders collapse into the top-level group (pinned, not silent).
  - unknown-suffix skip + case-insensitive suffix (RPi: pins the _AUDIO_SUFFIXES
    filter an impl could silently drop).
  - Catalog frozen-ness + tuple/frozenset return types (Senior Dev: the Q1
    value-object contract).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

from pirate_radio.catalog.scanner import scan_catalog
from pirate_radio.errors import CatalogError


def test_one_group_per_top_level_folder(content_tree: Path) -> None:
    cat = scan_catalog(content_tree)
    assert cat.group_names() == frozenset({"classical", "oldies"})  # empty_group dropped
    assert isinstance(cat.group_names(), frozenset)


def test_group_track_counts(content_tree: Path) -> None:
    groups = scan_catalog(content_tree).groups()
    assert len(groups["classical"]) == 2
    assert len(groups["oldies"]) == 2
    assert isinstance(groups["classical"], tuple)  # immutable value (value-object rule)


def test_tracks_are_sorted_by_group_then_path(content_tree: Path) -> None:
    # A5c: assert the real ordering contract (Phase-1 seeded generation depends on
    # it), not the tautological scan()==scan().
    tracks = scan_catalog(content_tree).tracks
    keys = [(t.group, str(t.path)) for t in tracks]
    assert keys == sorted(keys)


def test_ordering_is_independent_of_creation_order(
    tmp_path: Path, make_wav: Callable[..., Path]
) -> None:
    # A5c companion: files created out of order still come out sorted.
    root = tmp_path / "lib"
    for name in ("c.wav", "a.wav", "b.wav"):
        make_wav(root / "g" / name)
    names = [t.path.name for t in scan_catalog(root).tracks]
    assert names == ["a.wav", "b.wav", "c.wav"]


def test_nested_subfolders_collapse_into_top_level_group(
    tmp_path: Path, make_wav: Callable[..., Path]
) -> None:
    # A9: oldies/1960s/song.wav is indexed under the top-level "oldies" group.
    root = tmp_path / "lib"
    make_wav(root / "oldies" / "1960s" / "song.wav")
    cat = scan_catalog(root)
    assert cat.group_names() == frozenset({"oldies"})
    assert cat.tracks[0].group == "oldies"


def test_unknown_suffixes_are_skipped(tmp_path: Path, make_wav: Callable[..., Path]) -> None:
    # Pins the _AUDIO_SUFFIXES filter: non-audio sidecars are skipped without even
    # opening them (a real Pi library is full of cover.jpg / .cue / .nfo files).
    root = tmp_path / "lib"
    make_wav(root / "g" / "song.wav")
    for junk in ("cover.jpg", "notes.txt", "playlist.cue", "readme.nfo"):
        (root / "g" / junk).write_bytes(b"x")
    names = sorted(t.path.name for t in scan_catalog(root).tracks)
    assert names == ["song.wav"]


def test_uppercase_suffix_is_accepted(tmp_path: Path, make_wav: Callable[..., Path]) -> None:
    # Real libraries have .WAV/.MP3/.FLAC; suffix matching must be case-insensitive.
    root = tmp_path / "lib"
    make_wav(root / "g" / "SONG.WAV")
    assert [t.path.name for t in scan_catalog(root).tracks] == ["SONG.WAV"]


def test_missing_content_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(CatalogError):
        scan_catalog(tmp_path / "nope")


def test_empty_content_dir_raises(tmp_path: Path) -> None:
    (tmp_path / "library").mkdir()
    with pytest.raises(CatalogError):
        scan_catalog(tmp_path / "library")


def test_unreadable_file_is_skipped_and_logged(
    content_tree: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # A5b: prove the file is skipped AND that a WARNING naming it was emitted —
    # a silent swallow must not be coverage-invisible.
    (content_tree / "classical" / "broken.mp3").write_bytes(b"junk")
    with caplog.at_level(logging.WARNING):
        cat = scan_catalog(content_tree)  # must not raise
    assert all(t.path.name != "broken.mp3" for t in cat.tracks)
    assert any("broken.mp3" in r.getMessage() for r in caplog.records)


def test_catalog_is_frozen(content_tree: Path) -> None:
    # Q1: Catalog is a frozen value object; rescanning yields a new one, never a mutation.
    cat = scan_catalog(content_tree)
    with pytest.raises(ValidationError):
        cat.tracks = ()  # type: ignore[misc]


def test_is_group_non_empty(content_tree: Path) -> None:
    cat = scan_catalog(content_tree)
    assert cat.is_group_non_empty("classical")
    assert not cat.is_group_non_empty("nonexistent")
