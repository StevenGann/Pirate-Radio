"""Tests for ``pirate_radio.durability`` — the shared crash-safe write core (CF 0063).

`fsync_dir`/`atomic_replace` are the single home for temp→`os.replace`→dir-fsync, with the dir-fsync
policy made explicit per call site: ``strict=True`` (state_dir, A7) propagates a dir-fsync failure;
``strict=False`` (content library, possibly vfat) swallows it. Both behaviors are pinned here.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from pirate_radio.durability import atomic_replace, fsync_dir


def _write(p: Path, text: str) -> None:
    p.write_text(text, encoding="utf-8")


def test_atomic_replace_moves_tmp_over_dst(tmp_path: Path) -> None:
    dst = tmp_path / "f.txt"
    _write(dst, "old")
    tmp = tmp_path / "f.txt.tmp"
    _write(tmp, "new")
    atomic_replace(tmp, dst, strict=True)
    assert dst.read_text() == "new"
    assert not tmp.exists()  # the temp was renamed, not left behind


def test_atomic_replace_fsyncs_the_parent_dir(tmp_path: Path, monkeypatch) -> None:
    # R5: the parent directory is fsynced after the rename so the rename itself survives power loss.
    real_fsync = os.fsync
    dir_fsyncs = 0

    def spy(fd: int) -> None:
        nonlocal dir_fsyncs
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            dir_fsyncs += 1
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy)
    tmp = tmp_path / "f.tmp"
    _write(tmp, "x")
    atomic_replace(tmp, tmp_path / "f", strict=True)
    assert dir_fsyncs >= 1


def test_strict_dir_fsync_failure_propagates(tmp_path: Path, monkeypatch) -> None:
    real_fsync = os.fsync

    def fail_dir(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("simulated dir-fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_dir)
    with pytest.raises(OSError):
        fsync_dir(tmp_path, strict=True)


def test_best_effort_dir_fsync_failure_is_swallowed(tmp_path: Path, monkeypatch) -> None:
    real_fsync = os.fsync

    def fail_dir(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("vfat rejects a directory fd")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_dir)
    fsync_dir(tmp_path, strict=False)  # MUST NOT raise — the replace already happened


def test_best_effort_unopenable_dir_is_swallowed(tmp_path: Path, monkeypatch) -> None:
    def fail_open(*_a: object, **_k: object) -> int:
        raise OSError("cannot open directory fd")

    monkeypatch.setattr(os, "open", fail_open)
    fsync_dir(tmp_path, strict=False)  # MUST NOT raise
    with pytest.raises(OSError):
        fsync_dir(tmp_path, strict=True)  # strict surfaces it
