"""RED tests for the R15 provider-error taxonomy — Phase 1 plan §4.1.

Tests first: the base classes the pipeline catches (any ProviderError → R11 backstop)
and that Phase-3 failover will branch on (retryable vs fatal). Attaches under the
existing PirateRadioError root so `except PirateRadioError` still catches everything.
"""

from __future__ import annotations

from itertools import permutations

from pirate_radio.errors import (
    PirateRadioError,
    ProviderError,
    ProviderFatal,
    ProviderQuotaExceeded,
    ProviderUnavailable,
)

_LEAVES = [ProviderUnavailable, ProviderQuotaExceeded, ProviderFatal]


def test_provider_error_subclasses_root() -> None:
    assert issubclass(ProviderError, PirateRadioError)


def test_leaves_subclass_provider_error_and_root() -> None:
    for leaf in _LEAVES:
        assert issubclass(leaf, ProviderError)
        assert issubclass(leaf, PirateRadioError)


def test_leaves_are_distinct_and_not_cross_subclassed() -> None:
    # Failover (Phase 3) branches on these; one must not be a subclass of another.
    assert len(set(_LEAVES)) == len(_LEAVES)
    for a, b in permutations(_LEAVES, 2):
        assert not issubclass(a, b), f"{a.__name__} must not subclass {b.__name__}"


def test_any_leaf_catchable_as_provider_error() -> None:
    for leaf in _LEAVES:
        try:
            raise leaf("boom")
        except ProviderError as exc:
            assert isinstance(exc, PirateRadioError)
