# P4-7 — `midnight.py` (sleep-to-midnight + per-station isolated day-roll, DST) + Coordinator wiring

Strict spec-driven TDD (tests authored from plan §E → RED → GREEN → gate); integration-glue increment
per the 0038 efficiency stance, P4-9 deep-dive is the backstop.

## Implementation

- `next_midnight(now, tz) -> datetime` — PURE: the next local midnight strictly after `now`
  (tz-aware). `seconds_until_next_midnight(now, tz) -> float` — the **real elapsed** seconds, computed
  by converting both ends to **UTC** first.
- `MidnightTask(*, stations, clock, sleeper)` + `run()`: loop — sleep
  `seconds_until_next_midnight` (the injected `Sleeper`), then **per station, isolated**:
  `prepare_next_day()` (write the new day's file) **then** `signal_day_roll()` (set the Event) — the
  **file-then-event** ordering (Q2). A regen failure in one station is logged CRITICAL and **never
  escapes** (H-DA-1): siblings still roll (the later sibling too — the loop continues), the failed
  station keeps today's schedule. `DayRollable` Protocol = `name` + the two methods (Station satisfies
  it structurally).
- **Station regen API (P4-5 addition):** `prepare_next_day()` (= `_load_or_generate(clock today)` —
  reuses the one load-or-generate path so cold-start/restart/day-roll share it) and `signal_day_roll()`
  (= `day_roll.set()`). The midnight task uses these; it never cancels a running `run_once`, so a
  straddle-midnight item finishes uncut and the Station observes the roll after `play_day` returns
  (§8.6 — handled by the existing Station loop: `play_day` → REGENERATING → `await day_roll.wait()`).
- **Coordinator wiring:** builds `MidnightTask(stations=self.stations, …)` sharing the Stations' own
  day-roll Events; `run()` now gathers supervisor + midnight + summary concurrently.

## Two bugs the TDD loop caught (both real, fixed)

1. **Same-zone aware-datetime subtraction is NAIVE.** `(midnight_tomorrow - now).total_seconds()`
   on two `ZoneInfo`-aware datetimes returns the wall-clock delta (86400) and does NOT apply the DST
   offset change — so a spring-forward day wrongly slept 24 h, not 23 h. Fixed by converting both
   ends to UTC in `seconds_until_next_midnight` (verified empirically: NY 2026-03-08→09 = 82800 s in
   UTC vs 86400 naive). This is exactly the H24 DST-drift hazard the test guards.
2. **`VirtualSleeper` spins the loop.** It yields instantly, so the `while True` ran many iterations
   before the test cancel, accumulating duplicate regen events. Fixed at the test layer with a
   `_GatedSleeper` that parks after the first sleep → exactly one regen pass per test (prod sleeps
   are real, so no production impact).

## Deferred (documented for P4-9 ratification)

**Audio-buffer day-roll prewarm** (the Rev-2 amendment: render the opening cluster *during* the
outgoing day's final item). Not implemented — it would require spanning the day boundary inside the
**FROZEN** `run_once` (Q1 forbids churning it). What IS delivered is the **schedule prewarm**: the
new day's file is written before the Event is set, so the splice finds the schedule on disk (no
generation stall). The remaining boundary residual is the same bounded one-cluster R11 backstop as a
cold start (audible-as-bumper, not silence). The midnight task's docstring states this.

## Tests

`tests/test_midnight.py` (9): `next_midnight` basic + just-after-midnight; **DST spring-forward 23 h /
fall-back 25 h** (via `seconds_until_next_midnight`); the loop sleeps the computed seconds;
regenerate-then-signal each station (file-before-event order); **regen-failure isolated + non-fatal**
(sibling + later-sibling still roll, failed one not signaled, CRITICAL logged, no raise).
`tests/test_station.py` (+2): `prepare_next_day` generates+persists; `signal_day_roll` sets the Event.
`tests/test_coordinator.py`: `run()` now also patches `_midnight.run`.

## Gate

ruff + ruff-format + mypy `--strict` clean (46 source files); **692 tests** (+9), 98.29% coverage;
`midnight.py` 100%.

## Next

P4-8: `systemd/pirate-radio.service` + `__main__.py` (`python -m pirate_radio`, `main(argv, *, deps)`
seam, `--regenerate` oneshot) + `logging_setup.py` (operator log vocabulary) + `docs/ops/first-boot.md`.
