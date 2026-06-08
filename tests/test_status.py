"""Tests for ``pirate_radio.status`` — Phase 4 plan §status / Q6 (P4-3, revised by the deep-dive).

The minimal in-memory ``StationStatus`` (frozen) the Station + Supervisor update for the "N/N ON
AIR" journald summary. NO DTO module, NO HTTP (Q6) — just the struct. Every state is ACTUALLY
emitted (deep-dive: no speculative surface): the unemittable ``gap``/``airing_backstop`` states and
the unpopulated ``current_item``/``last_transition_at`` fields were removed; "live vs bumper"
degradation is surfaced via the producer's station-tagged backstop logs instead.
"""

from __future__ import annotations

import dataclasses

import pytest

from pirate_radio.status import StationState, StationStatus


def test_station_status_has_the_operator_fields() -> None:
    st = StationStatus(name="PiRate One", state=StationState.ON_AIR)
    assert st.name == "PiRate One"
    assert st.state is StationState.ON_AIR
    assert st.last_error is None and st.restart_count == 0


def test_station_status_is_frozen() -> None:
    st = StationStatus(name="S", state=StationState.STARTING)
    with pytest.raises(dataclasses.FrozenInstanceError):
        st.state = StationState.ON_AIR  # type: ignore[misc]


def test_station_state_is_exactly_the_emitted_set() -> None:
    # deep-dive (Old Man / Field-Op): ship ONLY states actually emitted — no dead vocabulary
    assert {s.value for s in StationState} == {
        "starting",  # Station
        "on_air",  # Station
        "regenerating",  # Station
        "crashed",  # Supervisor
        "restarting",  # Supervisor
    }


def test_station_status_carries_error_and_restart_count() -> None:
    st = StationStatus(
        name="S", state=StationState.CRASHED, restart_count=3, last_error="decode failed"
    )
    assert st.restart_count == 3 and st.last_error == "decode failed"
