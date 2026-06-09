"""The look-ahead budget — the C1 fix math (Phase-4 plan §A), PURE and unit-tested.

The producer renders **serially**, so the only thing that keeps it ahead of a short-patter cluster
is a look-ahead buffer deep enough to pre-render the whole cluster *while the preceding multi-minute
track plays* (the track masks the ~90 s of serial renders). The coordinator computes four coupled
quantities once at boot from the resolved config + each station's schedule:

- **depth** — ``worst_consecutive_patter + 1`` (the cluster + the one masking-track slot); passed to
  ``run_once(maxsize=depth)``.
- **RAM ceiling** — a **FAIL-FAST** ``ConfigError`` (NOT a silent clamp; a clamp would re-introduce
  C1) against a **FIXED** byte budget (``LOOKAHEAD_RAM_BUDGET_BYTES`` — sized for the 4 GB /
  4-station target, NOT a ``psutil`` fraction that varies per boot and is unreproducible at 3am).
- **stagger** — a deterministic per-station initial render delay (no RNG) so N stations don't fire
  Piper/cloud renders on the same tick (the 4-core thundering herd, synchronized top-of-hour IDs).
- **worst-case render** — Σ chain timeouts, used to decide the cold-start startup WARNING.

Everything here is pure (no clock, no IO, no hardware) — the coordinator (P4-6b) wires it.
"""

from __future__ import annotations

from collections.abc import Sequence

from pirate_radio.audio.buffer import DEFAULT_SAMPLE_RATE
from pirate_radio.errors import ConfigError
from pirate_radio.schedule.models import ScheduleItem, TrackItem

# ---- Named constants (§A, Q5; Old-Man/RPi condition: FIXED + reproducible, no magic numbers) ----

_BYTES_PER_FLOAT32 = 4  # AudioBuffer is float32 (~11.5 MB/min mono @ 48 kHz)

# A FIXED look-ahead RAM budget ≈ 1.6 GB ≈ 40% of a 4 GB Pi's *total* RAM, sized for the
# 4 GB / 4-station deployment target. Deliberately a constant (NOT a psutil-derived fraction of
# free RAM): the boot result must be byte-identical across reboots so a config that fails fast at
# 3am fails the same way every time (Rev-2 amendment; DA + Senior + Old Man). No psutil dependency.
LOOKAHEAD_RAM_BUDGET_BYTES = 1_600_000_000

# Per-station render-stagger step (H-RPi-3): station i waits ``i * step`` before its first render.
_STAGGER_STEP_SECONDS = 2.0

# Whole-track buffers resident BEYOND the look-ahead queue's ``depth`` slots, per station: the one
# segment the player popped and is writing, plus the one the producer has finished and is blocked
# trying to ``put``. The RAM fail-fast budgets for ``depth + this`` so the boundary is honest, not
# optimistic by two tracks (deep-dive RPi HIGH).
_RESIDENT_SLACK_SLOTS = 2

# Worst-case render timeouts (H14 defaults; named with derivation). A hung backend burns its FULL
# timeout before failover, so the worst single patter render = Σ of every chain backend's timeout.
# These mirror the config defaults (LLMConfig.request_timeout_seconds=20, DaemonConfig
# .tts_timeout_seconds=30, .decode_timeout_seconds=120) and are the fallbacks when none is passed.
_LLM_TIMEOUT_DEFAULT = 20.0
_TTS_TIMEOUT_DEFAULT = 30.0


def worst_consecutive_patter(items: Sequence[ScheduleItem]) -> int:
    """PURE: the longest run of consecutive NON-``TrackItem`` items (a patter cluster).

    A ``TrackItem`` resets the run; everything else (station_id / block_transition / block_reminder
    / future intro/outro/factoid patter) extends it. The generator's realistic worst case is 2
    (``block_transition`` + ``station_id`` at a top-of-hour boundary); the day's opening cluster has
    no preceding track to mask it (the day-roll-prewarm motivation lives in the coordinator)."""
    worst = run = 0
    for item in items:
        run = 0 if isinstance(item, TrackItem) else run + 1
        if run > worst:
            worst = run
    return worst


def lookahead_depth(items: Sequence[ScheduleItem]) -> int:
    """The buffer depth that masks the worst cluster: ``worst_consecutive_patter + 1`` (the cluster
    plus the one masking-track slot being consumed). An all-track schedule still needs depth 1."""
    return worst_consecutive_patter(items) + 1


def track_buffer_bytes(
    seconds: float, *, sample_rate: int = DEFAULT_SAMPLE_RATE, channels: int = 1
) -> int:
    """Bytes for ONE whole-track float32 ``AudioBuffer`` of ``seconds`` PLAYED duration.

    NB: ``seconds`` is the longest track's *played duration* (what sits decoded in the buffer),
    which is distinct from the decode *timeout* (a decode timeout sizes a render stall, not a
    buffer) — do not conflate the two."""
    return int(seconds * sample_rate * channels * _BYTES_PER_FLOAT32)


def ram_affordable_depth(
    *,
    worst_track_seconds: float,
    n_stations: int,
    ram_budget_bytes: int = LOOKAHEAD_RAM_BUDGET_BYTES,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    channels: int = 1,
) -> int:
    """The deepest look-ahead the budget affords across ALL stations: ``floor(budget /
    (n_stations × worst_track_bytes))`` — each buffered slot is ~one whole decoded track."""
    if worst_track_seconds <= 0 or n_stations <= 0 or ram_budget_bytes <= 0:
        raise ConfigError(
            "ram_affordable_depth: worst_track_seconds, n_stations and ram_budget_bytes "
            "must all be positive"
        )
    per = track_buffer_bytes(worst_track_seconds, sample_rate=sample_rate, channels=channels)
    return ram_budget_bytes // (n_stations * per)


def resolve_lookahead_depth(
    *,
    needed_depth: int,
    worst_track_seconds: float,
    n_stations: int,
    ram_budget_bytes: int = LOOKAHEAD_RAM_BUDGET_BYTES,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    channels: int = 1,
    resident_slack: int = _RESIDENT_SLACK_SLOTS,
) -> int:
    """Return ``needed_depth`` if the FIXED RAM budget affords the REAL resident peak across all
    stations, else FAIL-FAST with a ``ConfigError`` naming the fix. A silent clamp-to-affordable is
    REJECTED: a buffer shallower than the worst cluster cannot pre-render that cluster during the
    masking track, so C1 would silently regress to a sustained backstop-loop. The budget must cover
    ``needed_depth + resident_slack`` whole-track buffers per station — the queue PLUS the in-flight
    player + producer-blocked segments — not just the queue depth (deep-dive RPi)."""
    required = needed_depth + resident_slack
    affordable = ram_affordable_depth(
        worst_track_seconds=worst_track_seconds,
        n_stations=n_stations,
        ram_budget_bytes=ram_budget_bytes,
        sample_rate=sample_rate,
        channels=channels,
    )
    if affordable < required:
        raise ConfigError(
            f"look-ahead depth {needed_depth} (worst patter cluster + 1) needs {n_stations} × "
            f"{required} = {n_stations * required} whole-track buffers (queue + {resident_slack} "
            f"resident), but the {ram_budget_bytes / 1e9:.1f} GB RAM budget affords only "
            f"{affordable} per station; reduce the station count, shorten the longest track, or "
            f"raise the RAM budget"
        )
    return needed_depth


def stagger_offset(index: int, *, step: float = _STAGGER_STEP_SECONDS) -> float:
    """The deterministic initial render-stagger delay (seconds) for station ``index`` (R19-style —
    a pure function of the index, no RNG, so it is byte-reproducible)."""
    if index < 0:
        raise ConfigError(f"stagger_offset: station index must be non-negative, got {index}")
    return float(index * step)


def worst_case_patter_render(llm_timeouts: Sequence[float], tts_timeouts: Sequence[float]) -> float:
    """PURE worst-case seconds to render one patter item: Σ LLM-chain timeouts + Σ TTS-chain
    timeouts (each backend can hang its full timeout before the ranked chain fails over, Q5/H14)."""
    return sum(llm_timeouts) + sum(tts_timeouts)
