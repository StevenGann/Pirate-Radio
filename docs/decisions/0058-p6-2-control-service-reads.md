# P6-2 — `control/service.py` read paths (the typed read contract)

Strict spec-driven TDD with a **focused-panel test review** (QA · Senior · DA) before implementation
(the typed read contract the control API + future UI depend on).

## TDD loop

Tests authored → RED → **focused panel: QA NAY, Senior AYE, DA NAY → 2 NAY → revised** → re-RED →
GREEN. The decisive finding (QA+DA): the `now_playing` **GAP** shape of `find_now` (`item=None` +
`next_item` set + `gap_seconds`) was untested and conflated with the no-schedule case.

### Folded
- **GAP now-playing** test at T+601s — with the config's 2 s `transition_silence` item1 starts at
  T+602, so now is in the gap → `playing=False`, `next_item_kind="station_id"`, `gap_seconds≈1.0`.
  (Doubles as the **transition_silence wiring** pin: silence=0 would place T+601 INSIDE item1.)
- **past-end-of-day** (`playing=False`, `next_item_kind=None`).
- **list config-order** proven with a registry in REVERSE order; a config station **missing from the
  registry** → listed as `starting` (no KeyError).
- TrackItem **title/artist** surfaced in now-playing + schedule; a patter item's `title is None`;
  `item_count == len(items)`; an **unknown station does NOT attempt a load** (spy).

## Implementation

`ControlService(*, registry, configs, clock, load_schedule)` — FastAPI-free; injected
`load_schedule: (name, date) -> DailySchedule | None`. `list_stations` (config order; missing →
`starting`); `now_playing` (anchor today's schedule with the station's `transition_silence` + find_now
— A7 no-persisted-playhead re-derivation); `schedule(name, on=None)`. `StationNotFound` /
`ScheduleNotFound` (both → 404). DTOs `StationView` / `NowPlayingView` (incl. gap + track tags) /
`ScheduleView` / `ScheduleItemView`, all frozen.

## Gate

ruff + ruff-format + mypy `--strict` clean (59 source files); **819 tests** (+12), 97.60% coverage.

## Next

P6-3: service control paths (`regenerate`, `skip`) + the skip `asyncio.Event` + the regen lock seams.
