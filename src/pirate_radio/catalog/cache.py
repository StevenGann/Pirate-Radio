"""CatalogCache (A9): memoize ``scan_catalog`` and rescan only when the tree changes.

Re-walking the library and re-reading every file's metadata on each access is wasteful;
the cache returns the stored ``Catalog`` until the content tree's structure changes. It is
keyed by ``content_dir`` (so two stations' libraries are cached independently), and the
change signal is the ``st_mtime_ns`` of every directory in the tree — a cheap
one-``stat``-per-directory walk that opens no files.

H9 invalidation granularity (documented limits):
  - A file/dir **add, remove, or rename** bumps the containing directory's mtime and is
    detected.
  - An **in-place edit** of an existing file's bytes (same name) changes the FILE mtime
    but no DIRECTORY mtime, so it is NOT detected — restart or ``touch`` the dir to force
    a rescan.
  - On **FAT32 / exFAT** (common on Pi USB sticks) directory mtime has ~2 s resolution and
    may not update reliably on some kernel/mount configurations; the cache can stay hot
    across a structural change. Use ext4 for the content directory if dependable
    invalidation matters.

Not thread-safe: designed for single-threaded / single asyncio-loop use (the pipeline's
producer calls ``load``).
"""

from __future__ import annotations

import logging
from pathlib import Path

from pirate_radio.catalog.scanner import Catalog, scan_catalog

logger = logging.getLogger(__name__)

_Signature = tuple[tuple[str, int], ...]  # sorted (dir path, st_mtime_ns) for every dir


def _tree_signature(content_dir: Path) -> _Signature:
    """A cheap change-signal: the mtime of ``content_dir`` and every directory beneath it."""
    dirs = [content_dir, *(p for p in content_dir.rglob("*") if p.is_dir())]
    return tuple(sorted((str(p), p.stat().st_mtime_ns) for p in dirs))


class CatalogCache:
    def __init__(self) -> None:
        self._entries: dict[Path, tuple[_Signature, Catalog]] = {}

    def load(self, content_dir: Path) -> Catalog:
        """Return the cached ``Catalog`` for ``content_dir``, rescanning only if it changed."""
        content_dir = Path(content_dir)
        if not content_dir.is_dir():
            return scan_catalog(content_dir)  # raises CatalogError; never cache a failure

        signature = _tree_signature(content_dir)
        cached = self._entries.get(content_dir)
        if cached is not None and cached[0] == signature:
            logger.debug("catalog cache hit: %s", content_dir)
            return cached[1]

        catalog = scan_catalog(content_dir)
        self._entries[content_dir] = (signature, catalog)
        return catalog
