"""RED tests for ``pirate_radio.errors`` — authored from Phase 0 plan §4.1 / §6.1.

Tests first (strict spec-driven TDD): this file defines the contract for the
Phase-0 exception hierarchy *before* the module exists. The implementation must be
written to satisfy these tests; the tests change only if review proves them wrong.

Hardening folded in from the panel's tests-first review (adopted 7-0):
  - leaves asserted distinct and not cross-subclassed (Senior Dev + Devil's Advocate).
"""

from __future__ import annotations

from itertools import permutations
from pathlib import Path

import pytest

from pirate_radio.errors import (
    CatalogError,
    ConfigError,
    GridResolutionError,
    GridValidationError,
    PirateRadioError,
    StateCorruptionError,
)

# Every Phase-0 leaf the plan §4.1 enumerates.
LEAF_ERRORS: list[type[PirateRadioError]] = [
    ConfigError,
    GridValidationError,
    GridResolutionError,
    CatalogError,
    StateCorruptionError,
]


def test_root_subclasses_builtin_exception() -> None:
    assert issubclass(PirateRadioError, Exception)


@pytest.mark.parametrize("leaf", LEAF_ERRORS)
def test_all_leaves_subclass_root(leaf: type[PirateRadioError]) -> None:
    # One `except PirateRadioError` must catch everything from the package.
    assert issubclass(leaf, PirateRadioError)


def test_leaves_are_distinct_and_not_cross_subclassed() -> None:
    # No leaf may be an alias of, or a subclass of, another leaf — otherwise the
    # "raise the most specific leaf / catch them separately" §4.1 contract breaks
    # (e.g. GridResolutionError must NOT be a subclass of GridValidationError).
    assert len(set(LEAF_ERRORS)) == len(LEAF_ERRORS)
    for a, b in permutations(LEAF_ERRORS, 2):
        assert not issubclass(a, b), f"{a.__name__} must not subclass {b.__name__}"


def test_leaf_is_catchable_via_root() -> None:
    with pytest.raises(PirateRadioError):
        raise ConfigError("station names must be unique")


def test_message_is_preserved() -> None:
    assert str(ConfigError("bad config")) == "bad config"


def test_state_corruption_carries_path_and_message() -> None:
    err = StateCorruptionError("live and .bak both invalid", path=Path("/x/state.json"))
    assert err.path == Path("/x/state.json")
    assert isinstance(err, PirateRadioError)
    assert str(err) == "live and .bak both invalid"


def test_state_corruption_path_is_keyword_only() -> None:
    # `path` is keyword-only (def __init__(self, message, *, path)); a positional
    # path must be a TypeError, so callers can't accidentally swap message/path.
    with pytest.raises(TypeError):
        StateCorruptionError("boom", Path("/x/state.json"))  # type: ignore[misc]
