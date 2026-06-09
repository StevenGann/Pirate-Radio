"""Crash-safe write primitives — one home for the temp→`os.replace`→dir-fsync durability core.

`persistence` (daily schedules / cache / resume) and `tagging.tag_writer` (the offline tagger's tag
write) both need "atomically replace a file, then make the rename itself survive a power loss". They
historically each carried a private `_fsync_dir`; this is the single shared core (final-review
carry-forward 0063).

The one *intentional* difference is the dir-fsync policy, made explicit here per call site:

- **`strict=True`** — a parent-dir fsync failure PROPAGATES. For the `state_dir`, which MUST be a
  filesystem with a working directory fsync (ext4/f2fs per A7); a failure means the R5 durability
  guarantee can't be met and the caller should know (pinned by a persistence test).
- **`strict=False`** — best-effort. For the operator's content library, which may be vfat/exotic
  where a directory fd is rejected; the `os.replace` has already swapped the file atomically, so a
  dir-fsync failure there is harmless.
"""

from __future__ import annotations

import os
from pathlib import Path


def fsync_dir(directory: Path, *, strict: bool) -> None:
    """fsync ``directory`` so an ``os.replace`` rename within it survives a power loss (R5). See the
    module docstring for the ``strict`` policy (state_dir strict; content library best-effort)."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        if strict:
            raise
        return
    try:
        os.fsync(fd)
    except OSError:
        if strict:
            raise
    finally:
        os.close(fd)


def atomic_replace(tmp: Path, dst: Path, *, strict: bool) -> None:
    """Atomically move ``tmp`` → ``dst`` (``os.replace`` — atomic on POSIX for a same-filesystem
    rename; ``tmp`` MUST be in ``dst``'s directory), then fsync the parent dir so the rename itself
    is durable. ``strict`` controls the dir-fsync policy (see the module docstring)."""
    os.replace(tmp, dst)
    fsync_dir(dst.parent, strict=strict)
