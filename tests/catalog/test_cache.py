"""RED tests for ``pirate_radio.catalog.cache`` — A9 mtime-cached rescan.

Tests first. ``CatalogCache`` wraps ``scan_catalog`` and avoids re-walking the library
on every access: it returns the cached ``Catalog`` until the content tree's structure
changes, then rescans. H9 granularity (documented + pinned here): the cache key is the
``st_mtime_ns`` of every directory in the tree, so file/dir **add/remove/rename** (which
bump the containing directory's mtime) invalidate it — but an **in-place edit** of an
existing file's bytes (which does not touch any directory mtime) does NOT, and needs a
restart / ``touch`` of the dir. On **FAT32/exFAT** (common on Pi USB sticks) directory
mtime has ~2s resolution and may not update reliably on some kernel/mount configs — use
ext4 for the content dir if dependable invalidation matters.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from pirate_radio.catalog.cache import CatalogCache
from pirate_radio.catalog.scanner import scan_catalog
from pirate_radio.errors import CatalogError

# Patch target: the cache module's own reference to scan_catalog, wrapped so it still runs.
_SCAN = "pirate_radio.catalog.cache.scan_catalog"


def _bump_mtime(d: Path) -> None:
    # Advance a directory's mtime by a full second AFTER an add/remove/rename. The OS
    # already bumps it on tmpfs/ext4, but coarse-resolution filesystems (FAT) may not —
    # this makes the invalidation deterministic regardless of FS timestamp resolution.
    # Must run AFTER the structural change (the change itself would otherwise overwrite it).
    st = d.stat()
    os.utime(d, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))


def test_first_load_matches_scan_catalog(content_tree: Path) -> None:
    cache = CatalogCache()
    assert cache.load(content_tree).tracks == scan_catalog(content_tree).tracks


def test_unchanged_tree_is_a_cache_hit_with_no_rescan(content_tree: Path) -> None:
    # THE contract (not just identity): a second load on an unchanged tree must NOT call
    # scan_catalog again. Identity alone would pass an always-rescan-but-return-stored impl.
    cache = CatalogCache()
    first = cache.load(content_tree)
    with patch(_SCAN, wraps=scan_catalog) as spy:
        second = cache.load(content_tree)
        spy.assert_not_called()
    assert second is first


def test_multiple_dirs_are_cached_independently(
    content_tree: Path, tmp_path: Path, make_wav
) -> None:
    # Keyed by content_dir: loading a second library does not evict the first. A->B->A
    # must serve A from cache (no rescan), proving it is a dict, not a single slot.
    other = tmp_path / "lib2"
    make_wav(other / "jazz" / "a.wav")
    cache = CatalogCache()
    a1 = cache.load(content_tree)
    cache.load(other)
    with patch(_SCAN, wraps=scan_catalog) as spy:
        a2 = cache.load(content_tree)
        spy.assert_not_called()
    assert a2 is a1


def test_added_file_invalidates_the_cache(content_tree: Path, make_wav) -> None:
    cache = CatalogCache()
    first = cache.load(content_tree)
    make_wav(content_tree / "classical" / "new.wav")
    _bump_mtime(content_tree / "classical")  # add bumps the dir mtime
    second = cache.load(content_tree)
    assert second is not first
    assert len(second.tracks) == len(first.tracks) + 1


def test_removed_file_invalidates_the_cache(content_tree: Path) -> None:
    cache = CatalogCache()
    first = cache.load(content_tree)
    victim = next(p for p in (content_tree / "oldies").iterdir() if p.suffix == ".wav")
    victim.unlink()
    _bump_mtime(content_tree / "oldies")
    second = cache.load(content_tree)
    assert second is not first
    assert len(second.tracks) == len(first.tracks) - 1


def test_nested_subdir_change_invalidates_the_cache(content_tree: Path, make_wav) -> None:
    # The signature walks EVERY directory (rglob), so a file added in a NEW nested subdir
    # invalidates too (creating classical/sub/ adds a dir to the signature).
    cache = CatalogCache()
    first = cache.load(content_tree)
    make_wav(content_tree / "classical" / "sub" / "deep.wav")
    second = cache.load(content_tree)
    assert second is not first
    assert len(second.tracks) == len(first.tracks) + 1  # nested file collapses into "classical"


def test_inplace_file_edit_is_not_detected_documents_granularity(content_tree: Path) -> None:
    # H9 limitation: overwriting an existing file's bytes changes the FILE mtime but not
    # any DIRECTORY mtime, so the dir-mtime signature is unchanged and the cache stays hot.
    cache = CatalogCache()
    first = cache.load(content_tree)
    track = next(p for p in (content_tree / "classical").iterdir() if p.suffix == ".wav")
    track.write_bytes(track.read_bytes() + b"\x00\x00")  # edit content, same tree
    assert cache.load(content_tree) is first  # still the cached (now stale) catalog


def test_different_content_dir_rescans(content_tree: Path, tmp_path: Path, make_wav) -> None:
    other = tmp_path / "lib2"
    make_wav(other / "jazz" / "a.wav")
    cache = CatalogCache()
    first = cache.load(content_tree)
    second = cache.load(other)
    assert second is not first
    assert second.group_names() == frozenset({"jazz"})


def test_invalid_content_dir_propagates_catalog_error(tmp_path: Path) -> None:
    cache = CatalogCache()
    with pytest.raises(CatalogError):
        cache.load(tmp_path / "does_not_exist")
