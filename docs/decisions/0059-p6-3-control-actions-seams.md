# P6-3 — control-API control paths (skip / regenerate) + the skip Event + regen lock seams

Strict spec-driven TDD (tests from the adopted Phase-6 plan §Skip / §Regenerate / P6-3 → RED → GREEN
→ gate).

## Implementation

- **Skip-at-next-boundary seam.** `Player` gains an injected `skip: asyncio.Event | None`; at the loop
  top (between segments) a set Event → drop the next buffered segment, clear the Event (one-shot), and
  advance — it NEVER cuts the currently-airing segment (the sink writes the whole buffer on its
  thread, so a mid-segment cut is impossible without sink surgery — Rev-2 ruling). `skip` is threaded
  back-compat (`None` default) through `run_once` → `play_day` (via `**run_once_kwargs`) → `Station`.
  The `Station` owns its skip Event (`signal_skip()` sets it).
- **Regen lock seam.** `Station` gains a per-station `regen_lock` (`asyncio.Lock`, exposed read-only).
  The **MidnightTask** acquires `station.regen_lock` around `prepare_next_day` (DayRollable protocol
  gains the lock), and `Coordinator.regenerate_station(name)` acquires the SAME lock + offloads
  `prepare_next_day(force=True)` via the injected `offload` (default `asyncio.to_thread`, R23) — so an
  API regenerate can never race the midnight roll or a concurrent regen (DA CRITICAL). On-disk only;
  effect at the next day-roll/restart (documented, like `--regenerate`).
- **Coordinator** gains `skip(name)` (→ `station.signal_skip()`), async `regenerate_station(name)`, a
  `_by_name` map, and the injected `offload`.
- **ControlService** control paths: `skip(name)` (sync, injected callable) + async `regenerate(name)`
  (injected awaitable); both validate the station first (→ `StationNotFound` before invoking).

## Tests

`tests/pipeline/test_player.py` (+1): skip drops the next segment then clears (one-shot).
`tests/test_midnight.py`: fake station gains `regen_lock` (midnight acquires it).
`tests/test_coordinator.py` (+2): `skip` sets the station's Event; `regenerate_station` is BLOCKED
while the regen lock is held (serialized vs the midnight roll) and offloads. `tests/control/
test_service.py` (+4): skip/regenerate invoke the injected callables; unknown station raises BEFORE
invoking.

## Gate

ruff + ruff-format + mypy `--strict` clean (59 source files); **826 tests** (+7), 97.60% coverage.

## Next

P6-4: `control/api.py` + bearer auth — the FastAPI routes, envelope wiring, 404/401/422, R23 offload
seam, `TestClient` (+ `pytest-socket`).
