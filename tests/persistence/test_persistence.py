"""RED tests for ``pirate_radio.persistence`` — from Phase 0 plan §4.3 / §6.3.

Tests first (strict spec-driven TDD): the atomic-durable-recoverable JSON layer
(R5 atomic write, R6 recovery, R17 schema_version envelope) is specified here
before persistence.py exists. Real filesystem via ``tmp_path``; crash paths via
``monkeypatch``.

Rev 2 — folded in from the panel's tests-first review:
  - **Parent-dir fsync is proven to run** on the success path, and a crash AFTER
    os.replace but BEFORE the dir-fsync is pinned (QA + Devil's Advocate, BLOCKING:
    otherwise an impl that omits the dir-fsync — the load-bearing R5 line — passes
    green). (test_parent_directory_is_fsynced_on_success,
    test_crash_after_replace_before_dir_fsync_keeps_committed_value)
  - keyword-only ``schema_version`` (Senior Dev).
  - ``Path``/``datetime`` round-trip (Senior Dev — the layer advertises any model).
  - live-missing-but-valid-.bak recovery (Field Operator).
  - .bak is a standalone valid prior generation after a clean overwrite (Old Man,
    Devil's Advocate).
Temp-leak checks use ``iterdir`` (not ``glob("*.tmp")``) so hidden temp files count.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel

from pirate_radio.errors import StateCorruptionError
from pirate_radio.persistence import atomic_write_json, load_with_recovery


class _Doc(BaseModel):
    n: int
    label: str


class _RichDoc(BaseModel):
    where: Path
    when: datetime


def _tmp_leftovers(directory: Path) -> list[Path]:
    # iterdir, not glob("*.tmp"): the temp files are hidden (".state.json.X.tmp"),
    # which a shell-style "*" would miss — that miss would hide a real leak.
    return [x for x in directory.iterdir() if x.name.endswith(".tmp")]


# --- happy path & envelope (R17) ------------------------------------------------


def test_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    atomic_write_json(p, _Doc(n=1, label="a"), schema_version=1)
    assert load_with_recovery(p, _Doc, schema_version=1) == _Doc(n=1, label="a")


def test_envelope_wraps_payload_with_version(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    atomic_write_json(p, _Doc(n=1, label="a"), schema_version=1)
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    assert raw["payload"] == {"n": 1, "label": "a"}


def test_round_trips_path_and_datetime_fields(tmp_path: Path) -> None:
    # The layer advertises "any Pydantic model"; pin that model_dump(mode="json")
    # round-trips JSON-native-but-non-trivial field types (Path/datetime) that the
    # Phase-1 consumers (Catalog, DailySchedule) rely on.
    p = tmp_path / "rich.json"
    doc = _RichDoc(
        where=Path("/library/x.mp3"),
        when=datetime(2026, 6, 10, 9, 30, tzinfo=UTC),
    )
    atomic_write_json(p, doc, schema_version=1)
    assert load_with_recovery(p, _RichDoc, schema_version=1) == doc


def test_no_temp_files_left_behind_on_success(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    atomic_write_json(p, _Doc(n=1, label="a"), schema_version=1)
    assert _tmp_leftovers(tmp_path) == []


def test_schema_version_is_keyword_only(tmp_path: Path) -> None:
    # Signature is (path, model, *, schema_version); a positional version must be a
    # TypeError so a future signature loosening can't pass silently.
    p = tmp_path / "state.json"
    with pytest.raises(TypeError):
        atomic_write_json(p, _Doc(n=1, label="a"), 1)  # type: ignore[misc]
    atomic_write_json(p, _Doc(n=1, label="a"), schema_version=1)
    with pytest.raises(TypeError):
        load_with_recovery(p, _Doc, 1)  # type: ignore[misc]


# --- durability: parent-directory fsync (R5, BLOCKING fix) ----------------------


def test_parent_directory_is_fsynced_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # R5 mandates fsync of the PARENT DIRECTORY after os.replace so the rename
    # itself survives power loss. Without this test, an impl that fsyncs only the
    # temp file (omitting the dir fsync) passes green — the classic durability bug.
    real_fsync = os.fsync
    dir_fsync_count = 0

    def spy_fsync(fd: int) -> None:
        nonlocal dir_fsync_count
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            dir_fsync_count += 1
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy_fsync)
    atomic_write_json(tmp_path / "state.json", _Doc(n=1, label="a"), schema_version=1)
    assert dir_fsync_count >= 1, "R5: the parent directory must be fsynced on a successful write"


def test_crash_after_replace_before_dir_fsync_keeps_committed_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # First write (no .bak rotation), so the only dir-fsync is the main one AFTER
    # os.replace has already committed the file. The dir-fsync failure must surface
    # (OSError) but the committed value is already live, and no temp litters.
    p = tmp_path / "state.json"
    real_fsync = os.fsync

    def fail_dir_fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("simulated crash during parent-dir fsync")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_dir_fsync)
    with pytest.raises(OSError):
        atomic_write_json(p, _Doc(n=1, label="committed"), schema_version=1)
    monkeypatch.undo()

    assert load_with_recovery(p, _Doc, schema_version=1).label == "committed"
    assert _tmp_leftovers(tmp_path) == []


# --- recovery (R6) --------------------------------------------------------------


def test_recovers_from_bak_when_live_corrupt(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    atomic_write_json(p, _Doc(n=1, label="good"), schema_version=1)  # live=good
    atomic_write_json(p, _Doc(n=2, label="newer"), schema_version=1)  # good -> .bak; live=newer
    p.write_text("{ truncated", encoding="utf-8")  # corrupt live
    # Falls back to the last-known-good .bak, not a crash.
    assert load_with_recovery(p, _Doc, schema_version=1).label == "good"


def test_recovers_from_bak_when_live_missing(tmp_path: Path) -> None:
    # Interrupted write / cleanup left only the rotated .bak — recovery must still
    # succeed from it (Field Operator).
    p = tmp_path / "state.json"
    atomic_write_json(p, _Doc(n=1, label="good"), schema_version=1)  # live=good
    atomic_write_json(p, _Doc(n=2, label="newer"), schema_version=1)  # good -> .bak
    p.unlink()  # live gone entirely
    assert load_with_recovery(p, _Doc, schema_version=1).label == "good"


def test_overwrite_leaves_bak_as_valid_prior_generation(tmp_path: Path) -> None:
    # After a clean overwrite, the standalone .bak is a valid envelope holding the
    # prior generation (pins the rotation contract directly, not just transitively).
    p = tmp_path / "state.json"
    bak = p.with_suffix(".json.bak")
    atomic_write_json(p, _Doc(n=1, label="first"), schema_version=1)
    atomic_write_json(p, _Doc(n=2, label="second"), schema_version=1)
    assert load_with_recovery(bak, _Doc, schema_version=1) == _Doc(n=1, label="first")


def test_raises_state_corruption_when_both_invalid(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    atomic_write_json(p, _Doc(n=1, label="a"), schema_version=1)
    p.write_text("bad", encoding="utf-8")
    p.with_suffix(".json.bak").write_text("also bad", encoding="utf-8")
    with pytest.raises(StateCorruptionError) as ei:
        load_with_recovery(p, _Doc, schema_version=1)
    assert ei.value.path == p  # carries the path so the caller can regenerate (R6)


def test_missing_file_is_corruption(tmp_path: Path) -> None:
    with pytest.raises(StateCorruptionError):
        load_with_recovery(tmp_path / "nope.json", _Doc, schema_version=1)


def test_version_mismatch_is_corruption(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    atomic_write_json(p, _Doc(n=1, label="a"), schema_version=1)
    with pytest.raises(StateCorruptionError):
        load_with_recovery(p, _Doc, schema_version=2)  # Phase 0 refuses unknown versions


def test_non_envelope_json_is_corruption(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"schema_version": 1, "not_payload": {}}), encoding="utf-8")
    with pytest.raises(StateCorruptionError):
        load_with_recovery(p, _Doc, schema_version=1)


# --- crash injection / durability (R5, amendment A5a) ---------------------------


def test_crash_during_replace_preserves_prior_good_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = tmp_path / "state.json"
    atomic_write_json(p, _Doc(n=1, label="good"), schema_version=1)  # live=good

    real_replace = os.replace

    def failing_replace(src: object, dst: object, *a: object, **k: object) -> None:
        # Fail only when committing the LIVE file; let the .bak rotation succeed,
        # so we test a crash at the live-commit step specifically.
        if os.fspath(dst).endswith("state.json"):  # type: ignore[arg-type]
            raise OSError("simulated crash during os.replace")
        return real_replace(src, dst, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(OSError):
        atomic_write_json(p, _Doc(n=2, label="newer"), schema_version=1)
    monkeypatch.undo()

    # A recoverable state is never lost and never raises StateCorruptionError.
    assert load_with_recovery(p, _Doc, schema_version=1).label == "good"
    assert _tmp_leftovers(tmp_path) == []


def test_crash_during_fsync_on_first_write_leaves_no_litter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = tmp_path / "state.json"

    def failing_fsync(fd: int) -> None:
        raise OSError("simulated crash during os.fsync")

    monkeypatch.setattr(os, "fsync", failing_fsync)
    with pytest.raises(OSError):
        atomic_write_json(p, _Doc(n=1, label="a"), schema_version=1)
    monkeypatch.undo()

    assert not p.exists()  # the first write never committed
    assert _tmp_leftovers(tmp_path) == []  # the temp file was cleaned up


def test_replace_keep_bak_failure_preserves_live_and_no_litter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Exercise the _replace_keep_bak failure path independently (A5a): make the
    # .bak rotation fail; the live file must survive and no temp file may leak.
    p = tmp_path / "state.json"
    atomic_write_json(p, _Doc(n=1, label="good"), schema_version=1)  # live=good

    real_replace = os.replace

    def fail_bak_replace(src: object, dst: object, *a: object, **k: object) -> None:
        if os.fspath(dst).endswith(".bak"):  # type: ignore[arg-type]
            raise OSError("simulated crash rotating .bak")
        return real_replace(src, dst, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "replace", fail_bak_replace)
    with pytest.raises(OSError):
        atomic_write_json(p, _Doc(n=2, label="newer"), schema_version=1)
    monkeypatch.undo()

    assert load_with_recovery(p, _Doc, schema_version=1).label == "good"
    assert _tmp_leftovers(tmp_path) == []
