# P4-5 — `station.py` (per-station supervised day loop) + in-band render-poison

Strict spec-driven TDD: tests authored from the adopted Phase-4 plan §station-loop / P4-5 →
confirmed RED → implemented GREEN → gate. Per the autonomous-to-completion directive, the remaining
Phase-4 increments fold prior-panel lessons directly into the tests; the full-seven **Phase-4
deep-dive (P4-9)** is the quality backstop — and it must ratify the in-band render-poison deviation
recorded below.

## Implementation

- `station.py`: `Station` — the per-station `Supervisable` (name + async `run`; `skip_item(index)`).
  `run()` is the day loop: status `STARTING` → **load-or-generate** today's `DailySchedule`
  (`load_with_recovery`; on `StateCorruptionError` — absent OR corrupt — regenerate from
  `grid_loader(day)` + catalog via `generate_schedule` with `derive_seed(day, name)`, `mkdir -p`
  the station dir, `atomic_write_json` — **R6**, never a crash-loop), **anchor** (R12), status
  `ON_AIR`, drive `play_day(anchored, now, …)`, status `REGENERATING`, then **await the day-roll
  `asyncio.Event`** (set by the midnight task *after* it writes the new day's file — write-then-signal
  ordering, §E), `clear()`, loop. Cold start and post-crash restart use the identical path (§6):
  reload from disk + slice vs `clock.now()`.
- **`sleeper` is a Station constructor dependency** (was a `None`-placeholder bug in the first
  draft): `run_once` (reached via `play_day`) needs a real `Sleeper` for its cooperative R23 wait,
  so the Station accepts `sleeper: Sleeper` and forwards it. Prod injects `RealSleeper`; tests inject
  `VirtualSleeper`.
- `Catalog` is imported from `catalog.scanner` (not `catalog.models`).
- `_status(state, **kw)` builds a frozen `StationStatus` and pushes it to the injected `on_status`
  callback (the coordinator's registry, P4-6) — `None` = no-op for the bare path.

### In-band render-poison (documented deviation from plan §C — for P4-9 ratification)

The plan's §C had the producer **propagate** a non-`ProviderError` render crash so the supervisor
could advance past it by item index. That required intricate index-mapping across the slice/seek
boundary. Instead (P4-5, building on the P4-4 producer change) the **producer backstops ANY render
exception in-band** with a distinct `CRITICAL` "render-poison … -> backstop; investigate" log. This
is strictly safer — it can't crash-loop, never dead-airs (R11), and is loud in journald — and it
eliminates the index plumbing. The Station/Supervisor `skip_item` advance-past-poison path is
**retained as the net** for a crash that escapes the producer entirely. To be ratified by P4-9.

## Tests (7 — `tests/test_station.py`)

`Station` is `Supervisable` + `name`; `skip_item` records the index; load-or-generate uses the
persisted schedule when present (generate NOT called) and regenerates-AND-persists on corruption
(R6); `run` plays the day then awaits the day-roll (station/persona threaded into `play_day`);
re-slices and plays again on the day-roll signal; reports the `ON_AIR` status transition to
`on_status`. Orchestration tested with `load_with_recovery`/`generate_schedule`/`atomic_write_json`/
`play_day` monkeypatched (each covered by its own suite) — this pins the Station's CONTROL FLOW.

Producer render-poison (P4-4/P4-5, `tests/pipeline/test_producer_dj.py`):
`test_non_providererror_render_poison_is_backstopped` — a non-`ProviderError` render raise yields the
backstop segment (never crashes / drops the item), logged `CRITICAL`.

## Gate

ruff + ruff-format + mypy `--strict` clean; **640 tests** (+8), 98.64% coverage; `station.py` 100%.

## Next

P4-5b: `item_kind` Protocol-param removal (drop the redundant `item_kind` from
`TextGenerator.patter(item_kind, context)` since `context.kind` carries it). Then P4-6 (coordinator).
