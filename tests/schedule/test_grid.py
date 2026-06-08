"""RED tests for ``pirate_radio.schedule.grid`` — from Phase 0 plan §4.7 / §6.6.

Tests first (strict spec-driven TDD): grid models, YAML loader, day-of-week
resolution (§8.2), and fail-fast tiling validation (§8.3) — before grid.py exists.

Q3 fence (adopted): ``time(0,0)`` models end-of-day (24:00) but is legal ONLY on the
final slot. A single ``00:00->00:00`` slot is accepted as "all day"; a non-final
slot ending at midnight (incl. two all-day slots) and a zero-length slot are rejected.

Rev 2 folds in panel hardening: §8.3 time-format parse (QA, BLOCKING), Saturday
weekend boundary (RPi), missing-slots-key / empty-file / slot-not-mapping /
unreadable-path (QA, DA), empty-group + optional-None + order-preservation
(Senior Dev, DA), and richer gap-message assertions (Field Op).
"""

from __future__ import annotations

from datetime import time
from pathlib import Path

import pytest

from pirate_radio.errors import GridResolutionError, GridValidationError
from pirate_radio.schedule.grid import (
    load_grid,
    resolve_grid_path,
    validate_grid_against_catalog,
)


def _write(p: Path, body: str) -> Path:
    p.write_text(body, encoding="utf-8")
    return p


# --- day-of-week resolution (§8.2) ----------------------------------------------


def test_resolution_prefers_exact_day(tmp_path: Path) -> None:
    (tmp_path / "default.yaml").touch()
    (tmp_path / "wednesday.yaml").touch()
    assert resolve_grid_path(tmp_path, weekday=2).name == "wednesday.yaml"


def test_resolution_weekend_then_default(tmp_path: Path) -> None:
    (tmp_path / "default.yaml").touch()
    (tmp_path / "weekend.yaml").touch()
    assert resolve_grid_path(tmp_path, weekday=6).name == "weekend.yaml"  # Sunday
    (tmp_path / "weekend.yaml").unlink()
    assert resolve_grid_path(tmp_path, weekday=6).name == "default.yaml"


def test_resolution_saturday_routes_to_weekend(tmp_path: Path) -> None:
    # weekday=5 (Saturday) is the exact `>= 5` weekend boundary — the most likely
    # off-by-one in a Mon=0 scheme (RPi: matters for the pre-NTP boot lookup).
    (tmp_path / "weekday.yaml").touch()
    (tmp_path / "weekend.yaml").touch()
    assert resolve_grid_path(tmp_path, weekday=5).name == "weekend.yaml"


def test_resolution_weekday_for_a_weekday(tmp_path: Path) -> None:
    (tmp_path / "weekday.yaml").touch()
    (tmp_path / "default.yaml").touch()
    assert resolve_grid_path(tmp_path, weekday=0).name == "weekday.yaml"  # Monday


def test_resolution_none_raises(tmp_path: Path) -> None:
    with pytest.raises(GridResolutionError):
        resolve_grid_path(tmp_path, weekday=0)


# --- valid tiling (§8.3) --------------------------------------------------------


def test_valid_grid_tiles_full_day(tmp_path: Path) -> None:
    g = load_grid(
        _write(
            tmp_path / "default.yaml",
            "slots:\n"
            '  - {start: "00:00", end: "12:00", group: a, name: "AM"}\n'
            '  - {start: "12:00", end: "00:00", group: b, name: "PM"}\n',
        )
    )
    assert g.slots[0].start == time(0, 0)
    assert g.slots[-1].end == time(0, 0)
    assert g.name == "default"  # falls back to the file stem when no name given


def test_optional_fields_parsed(tmp_path: Path) -> None:
    g = load_grid(
        _write(
            tmp_path / "g.yaml",
            "name: Weekday\n"
            "slots:\n"
            '  - {start: "00:00", end: "00:00", group: a, name: "All",'
            ' tagline: "t", description: "d"}\n',
        )
    )
    assert g.name == "Weekday"
    assert g.slots[0].tagline == "t" and g.slots[0].description == "d"


def test_minimal_slot_has_no_optional_fields(tmp_path: Path) -> None:
    g = load_grid(
        _write(
            tmp_path / "g.yaml",
            'slots:\n  - {start: "00:00", end: "00:00", group: a, name: "All Day"}\n',
        )
    )
    assert g.slots[0].tagline is None and g.slots[0].description is None


def test_slot_order_is_preserved(tmp_path: Path) -> None:
    # Phase-1's cursor walk depends on authored order — the loader must not re-sort.
    g = load_grid(
        _write(
            tmp_path / "g.yaml",
            "slots:\n"
            '  - {start: "00:00", end: "08:00", group: a, name: "first"}\n'
            '  - {start: "08:00", end: "16:00", group: b, name: "second"}\n'
            '  - {start: "16:00", end: "00:00", group: c, name: "third"}\n',
        )
    )
    assert [s.name for s in g.slots] == ["first", "second", "third"]


# --- structural rejections (§8.3) -----------------------------------------------


def test_gap_rejected_with_actionable_message(tmp_path: Path) -> None:
    with pytest.raises(GridValidationError) as ei:
        load_grid(
            _write(
                tmp_path / "g.yaml",
                "slots:\n"
                '  - {start: "00:00", end: "06:00", group: a, name: "x"}\n'
                '  - {start: "07:00", end: "00:00", group: b, name: "y"}\n',
            )
        )
    # Operator-actionable: names the offending slots and the gap times (Field Op).
    msg = str(ei.value)
    assert "gap/overlap" in msg
    assert "06:00" in msg and "07:00" in msg


def test_overlap_rejected(tmp_path: Path) -> None:
    with pytest.raises(GridValidationError):
        load_grid(
            _write(
                tmp_path / "g.yaml",
                "slots:\n"
                '  - {start: "00:00", end: "06:00", group: a, name: "x"}\n'
                '  - {start: "05:00", end: "00:00", group: b, name: "y"}\n',
            )
        )


def test_must_start_at_midnight(tmp_path: Path) -> None:
    with pytest.raises(GridValidationError, match="00:00"):
        load_grid(
            _write(
                tmp_path / "g.yaml",
                'slots:\n  - {start: "01:00", end: "00:00", group: a, name: "x"}\n',
            )
        )


def test_must_end_at_midnight(tmp_path: Path) -> None:
    with pytest.raises(GridValidationError):
        load_grid(
            _write(
                tmp_path / "g.yaml",
                'slots:\n  - {start: "00:00", end: "23:00", group: a, name: "x"}\n',
            )
        )


def test_start_not_before_end_rejected(tmp_path: Path) -> None:
    with pytest.raises(GridValidationError):
        load_grid(
            _write(
                tmp_path / "g.yaml",
                'slots:\n  - {start: "06:00", end: "03:00", group: a, name: "x"}\n',
            )
        )


def test_missing_name_rejected(tmp_path: Path) -> None:
    with pytest.raises(GridValidationError):
        load_grid(
            _write(
                tmp_path / "g.yaml",
                'slots:\n  - {start: "00:00", end: "00:00", group: a}\n',
            )
        )


def test_empty_group_rejected(tmp_path: Path) -> None:
    with pytest.raises(GridValidationError):
        load_grid(
            _write(
                tmp_path / "g.yaml",
                'slots:\n  - {start: "00:00", end: "00:00", group: "", name: "x"}\n',
            )
        )


def test_invalid_time_format_rejected(tmp_path: Path) -> None:
    # §8.3 "time formats parse": an unparseable time must surface as the typed
    # GridValidationError (not a raw Pydantic ValidationError leaking out). (QA)
    with pytest.raises(GridValidationError):
        load_grid(
            _write(
                tmp_path / "g.yaml",
                'slots:\n  - {start: "25:99", end: "00:00", group: a, name: "x"}\n',
            )
        )


def test_no_slots_rejected(tmp_path: Path) -> None:
    with pytest.raises(GridValidationError):
        load_grid(_write(tmp_path / "g.yaml", "slots: []\n"))


def test_missing_slots_key_rejected(tmp_path: Path) -> None:
    with pytest.raises(GridValidationError):
        load_grid(_write(tmp_path / "g.yaml", "name: nope\n"))


def test_empty_file_rejected(tmp_path: Path) -> None:
    # `touch monday.yaml` -> safe_load returns None -> not a mapping (DA).
    with pytest.raises(GridValidationError):
        load_grid(_write(tmp_path / "g.yaml", ""))


def test_not_a_mapping_rejected(tmp_path: Path) -> None:
    with pytest.raises(GridValidationError):
        load_grid(_write(tmp_path / "g.yaml", "- just\n- a\n- list\n"))


def test_slot_not_a_mapping_rejected(tmp_path: Path) -> None:
    # A slots entry that isn't a mapping must surface as GridValidationError, not a
    # raw Pydantic error (DA — locks the error-type contract).
    with pytest.raises(GridValidationError):
        load_grid(_write(tmp_path / "g.yaml", "slots:\n  - just a string\n"))


def test_unreadable_path_rejected(tmp_path: Path) -> None:
    # load_grid is public; a path that can't be read (here, a directory) -> typed error.
    d = tmp_path / "iam_a_dir.yaml"
    d.mkdir()
    with pytest.raises(GridValidationError):
        load_grid(d)


def test_yaml_safe_load_only(tmp_path: Path) -> None:
    # A python/object tag must be rejected by safe_load (no code execution).
    with pytest.raises(GridValidationError):
        load_grid(
            _write(
                tmp_path / "g.yaml",
                "slots: !!python/object/apply:os.system ['echo hi']\n",
            )
        )


# --- Q3: the 24:00 / time(0,0) fence --------------------------------------------


def test_single_all_day_slot_accepted(tmp_path: Path) -> None:
    g = load_grid(
        _write(
            tmp_path / "g.yaml",
            'slots:\n  - {start: "00:00", end: "00:00", group: a, name: "All Day"}\n',
        )
    )
    assert len(g.slots) == 1  # the 24:00-as-00:00 all-day edge is accepted


def test_two_all_day_midnight_slots_rejected(tmp_path: Path) -> None:
    # Q3: a non-final slot ending at midnight (here, two 00:00->00:00 slots) is the
    # degenerate collision; end==00:00 is legal ONLY on the final slot.
    with pytest.raises(GridValidationError, match="final"):
        load_grid(
            _write(
                tmp_path / "g.yaml",
                "slots:\n"
                '  - {start: "00:00", end: "00:00", group: a, name: "x"}\n'
                '  - {start: "00:00", end: "00:00", group: b, name: "y"}\n',
            )
        )


def test_non_final_slot_ending_at_midnight_rejected(tmp_path: Path) -> None:
    # Q3: an all-day slot followed by more slots tiles via the pairwise check but is
    # semantically broken — the midnight end-marker must appear only last.
    with pytest.raises(GridValidationError, match="final"):
        load_grid(
            _write(
                tmp_path / "g.yaml",
                "slots:\n"
                '  - {start: "00:00", end: "00:00", group: a, name: "x"}\n'
                '  - {start: "00:00", end: "06:00", group: b, name: "y"}\n'
                '  - {start: "06:00", end: "00:00", group: c, name: "z"}\n',
            )
        )


def test_zero_length_slot_rejected(tmp_path: Path) -> None:
    # Q3: start == end (non-midnight) is a zero-length slot — rejected.
    with pytest.raises(GridValidationError):
        load_grid(
            _write(
                tmp_path / "g.yaml",
                'slots:\n  - {start: "06:00", end: "06:00", group: a, name: "x"}\n',
            )
        )


# --- folder cross-check (§8.3 / §12, two-phase) ---------------------------------


def test_group_not_in_catalog_rejected(tmp_path: Path) -> None:
    g = load_grid(
        _write(
            tmp_path / "g.yaml",
            'slots:\n  - {start: "00:00", end: "00:00", group: jazz, name: "x"}\n',
        )
    )
    with pytest.raises(GridValidationError, match="jazz"):
        validate_grid_against_catalog(g, frozenset({"classical"}), tmp_path / "g.yaml")


def test_group_in_catalog_passes(tmp_path: Path) -> None:
    g = load_grid(
        _write(
            tmp_path / "g.yaml",
            'slots:\n  - {start: "00:00", end: "00:00", group: classical, name: "x"}\n',
        )
    )
    # No raise when every slot group has a non-empty content folder.
    validate_grid_against_catalog(g, frozenset({"classical", "oldies"}), tmp_path / "g.yaml")
