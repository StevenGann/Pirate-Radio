"""In-memory station status (Phase 4 §status / Q6) — the minimal struct supervision already needs.

NO DTO module, NO read-model, NO HTTP (Q6 — Old Man "zero speculative surface" + Field-Op
"answerable from journald"): just a frozen snapshot the coordinator's supervisor updates and the
periodic "N/N ON AIR" summary log reads. Phase 6's control API can read it later; Phase 4 ships
only this struct + the summary line. ``state`` distinguishes ``on_air`` from ``airing_backstop`` so
an operator can tell a live station from one stuck on the R11 bumper.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class StationState(StrEnum):
    STARTING = "starting"
    ON_AIR = "on_air"
    GAP = "gap"
    AIRING_BACKSTOP = "airing_backstop"  # live but on the R11 bumper (not dead air, not "on_air")
    REGENERATING = "regenerating"
    CRASHED = "crashed"
    RESTARTING = "restarting"


@dataclass(frozen=True)
class StationStatus:
    name: str
    state: StationState
    current_item: str | None = None
    last_transition_at: datetime | None = None
    restart_count: int = 0
    last_error: str | None = None
