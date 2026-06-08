"""RED tests for ``pirate_radio.status`` — Phase 4 plan §status / Q6 (P4-3).

Tests first: the minimal in-memory ``StationStatus`` (frozen) the supervisor/coordinator already
need for restart decisions + the "N/N ON AIR" journald summary. NO DTO module, NO HTTP (Q6) — just
the struct. ``state`` distinguishes ``on_air`` from ``airing_backstop`` (Field-Op: tell "live" from
"stuck on the bumper" in the journal).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from pirate_radio.status import StationState, StationStatus


def test_station_status_has_the_operator_fields() -> None:
    st = StationStatus(name="PiRate One", state=StationState.ON_AIR)
    assert st.name == "PiRate One"
    assert st.state is StationState.ON_AIR
    assert st.current_item is None and st.last_error is None and st.restart_count == 0


def test_station_status_is_frozen() -> None:
    st = StationStatus(name="S", state=StationState.STARTING)
    with pytest.raises(dataclasses.FrozenInstanceError):
        st.state = StationState.ON_AIR  # type: ignore[misc]


def test_station_state_distinguishes_on_air_from_airing_backstop() -> None:
    # Field-Op: an operator reading journald must tell a live station from one stuck on the bumper
    assert StationState.ON_AIR is not StationState.AIRING_BACKSTOP
    assert {s.value for s in StationState} >= {
        "starting",
        "on_air",
        "gap",
        "airing_backstop",
        "regenerating",
        "crashed",
        "restarting",
    }


def test_station_status_carries_error_and_restart_count() -> None:
    st = StationStatus(
        name="S",
        state=StationState.CRASHED,
        current_item="station_id",
        last_transition_at=datetime(2026, 6, 10, tzinfo=UTC),
        restart_count=3,
        last_error="decode failed",
    )
    assert st.restart_count == 3 and st.last_error == "decode failed"
