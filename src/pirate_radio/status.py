"""In-memory station status (Phase 4 §status / Q6) — the minimal struct supervision already needs.

NO DTO module, NO read-model, NO HTTP (Q6 — Old Man "zero speculative surface" + Field-Op
"answerable from journald"): just a frozen snapshot the Station + Supervisor update and the periodic
"N/N ON AIR" summary log reads. Phase 6's control API can read it later; Phase 4 ships only this
struct + the summary line.

Every state here is ACTUALLY emitted: ``STARTING``/``ON_AIR``/``REGENERATING`` by the Station,
``CRASHED``/``RESTARTING`` by the Supervisor (with ``restart_count`` + a scrubbed ``last_error``). A
``GAP``/``airing_backstop`` state is deliberately NOT modelled in v1 — distinguishing "live" from
"airing the R11 bumper" would require threading status out of the frozen ``run_once``/producer (Q1);
instead the producer's **station-tagged** backstop WARNING / render-poison CRITICAL logs make that
degradation greppable in journald (deep-dive resolution; a status enrichment is a Phase-6 nicety).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class StationState(StrEnum):
    STARTING = "starting"
    ON_AIR = "on_air"  # broadcasting (the R11 backstop bumper is surfaced via station-tagged logs)
    REGENERATING = "regenerating"
    CRASHED = "crashed"
    RESTARTING = "restarting"


@dataclass(frozen=True)
class StationStatus:
    name: str
    state: StationState
    restart_count: int = 0  # set by the Supervisor on the crash/restart path
    last_error: str | None = None  # the scrubbed crash cause (H22), set by the Supervisor
