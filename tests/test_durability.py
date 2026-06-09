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

from pirate_radio.durability import atomic_replace, fsync_dir, write_bytes_durably


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


# ---- write_bytes_durably: the shared temp→fsync→atomic-replace byte writer (CF cycle-3) -----
def test_write_bytes_durably_writes_atomically_and_fsyncs(tmp_path: Path, monkeypatch) -> None:
    real_fsync = os.fsync
    file_fsyncs = dir_fsyncs = 0

    def spy(fd: int) -> None:
        nonlocal file_fsyncs, dir_fsyncs
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            dir_fsyncs += 1
        else:
            file_fsyncs += 1
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy)
    dst = tmp_path / "state.json"
    write_bytes_durably(dst, b"durable-payload", strict=True)
    assert dst.read_bytes() == b"durable-payload"
    assert file_fsyncs >= 1  # the file bytes were fsynced before the rename
    assert dir_fsyncs >= 1  # the parent dir was fsynced so the rename survives power loss
    # no stray temp left behind in the directory
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_write_bytes_durably_overwrites_existing(tmp_path: Path) -> None:
    dst = tmp_path / "f"
    dst.write_bytes(b"old")
    write_bytes_durably(dst, b"new", strict=True)
    assert dst.read_bytes() == b"new"


def test_write_bytes_durably_leaves_no_temp_on_failure(tmp_path: Path, monkeypatch) -> None:
    dst = tmp_path / "f"

    def boom(*_a: object, **_k: object) -> None:
        raise OSError("write failed")

    # fail during the in-fdopen write; the temp must be unlinked and the error re-raised
    monkeypatch.setattr(os, "fsync", boom)
    with pytest.raises(OSError):
        write_bytes_durably(dst, b"data", strict=True)
    assert list(tmp_path.iterdir()) == []  # no stray .tmp
