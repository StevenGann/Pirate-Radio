"""RED tests for ``pirate_radio.catalog.models`` — from Phase 0 plan §4.4 / §13.

Tests first (strict spec-driven TDD): the ``Track`` value object contract before
the module exists. Per amendment A10, the ``year`` bound and its producer agree —
``year`` is constrained so a nonsense year (0) is rejected.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from pirate_radio.catalog.models import Track


def test_track_minimal_valid() -> None:
    t = Track(path=Path("/lib/classical/x.wav"), group="classical", duration=12.5)
    assert t.group == "classical"
    assert t.duration == 12.5
    assert t.title is None and t.artist is None and t.album is None and t.year is None


def test_track_is_frozen() -> None:
    t = Track(path=Path("/x"), group="g", duration=1.0)
    with pytest.raises(ValidationError):
        t.duration = 2.0  # type: ignore[misc]  # frozen value object


def test_duration_must_be_positive() -> None:
    for bad in (0.0, -1.0):
        with pytest.raises(ValidationError):
            Track(path=Path("/x"), group="g", duration=bad)


def test_group_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        Track(path=Path("/x"), group="", duration=1.0)


def test_year_rejects_nonsense_and_out_of_range() -> None:
    assert Track(path=Path("/x"), group="g", duration=1.0, year=1905).year == 1905
    for bad in (0, 10000):
        with pytest.raises(ValidationError):
            Track(path=Path("/x"), group="g", duration=1.0, year=bad)
