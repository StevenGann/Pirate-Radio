"""RED tests for ``pirate_radio.control.models`` — Phase-6 P6-1 (the response envelope).

The consistent envelope (D4): ``{success, data, error}`` — ``error`` present IFF ``not success``,
and an error response carries no ``data``. ``ok()``/``fail()`` are the only builders; a hand-built
malformed combo must raise (data-xor-error enforced in the model, not by convention).
"""

from __future__ import annotations

import pytest

from pirate_radio.control.models import ApiError, ApiResponse, fail, ok


def test_ok_wraps_data_with_no_error() -> None:
    r = ok({"name": "Pi0"})
    assert r.success is True and r.data == {"name": "Pi0"} and r.error is None


def test_fail_carries_a_typed_error_and_no_data() -> None:
    r = fail("not_found", "no station 'X'")
    assert r.success is False and r.data is None
    assert r.error == ApiError(code="not_found", message="no station 'X'")


def test_success_response_with_an_error_is_rejected() -> None:
    with pytest.raises(Exception):  # data-xor-error: success must not carry an error
        ApiResponse(success=True, error=ApiError(code="x", message="y"))


def test_error_response_without_an_error_is_rejected() -> None:
    with pytest.raises(Exception):
        ApiResponse(success=False, error=None)


def test_error_response_with_data_is_rejected() -> None:
    with pytest.raises(Exception):
        ApiResponse(success=False, data={"x": 1}, error=ApiError(code="x", message="y"))


def test_ok_allows_none_data() -> None:
    # skip/regenerate return success with no payload — still valid (success, data=None, error=None)
    assert ok(None).success is True and ok(None).error is None
