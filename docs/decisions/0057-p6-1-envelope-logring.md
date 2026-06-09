# P6-1 — `control/models.py` (envelope) + `control/logs.py` (bounded log ring)

Strict spec-driven TDD (tests from the adopted Phase-6 plan §P6-1 → RED → GREEN → gate). The first
increment: the consistent response envelope (D4) + the `/logs` backing store.

## Implementation

- `control/models.py`: `ApiError{code,message}` + `ApiResponse{success,data,error}` with a
  `model_validator` enforcing **data-XOR-error** (error present iff `not success`; an error response
  carries no data) — so a route can never ship a malformed envelope. `ok(data=None)` / `fail(code,
  message)` are the only builders. NO `Generic[T]`, NO `meta` (Old Man Rev-2 trims).
- `control/logs.py`: `RingLogHandler(maxsize, *, clock, scrub)` — a `logging.Handler` with a
  `deque(maxlen=N)`; `emit`/`snapshot` are **lock-guarded** (records appended by logging threads, read
  by the async `/logs` route) and `scrub_secrets` runs in `emit` BEFORE storage (H22 — a token can
  never reach `/logs`). Records are clock-stamped via an INJECTED clock (R18/R21). `query_logs(...)` is
  a PURE filter (station substring / minimum level / `since` / `limit`, newest-first). `LogEntry`
  frozen DTO. **Documented R8′ deviation** (ring vs journald/SQLite — never reads the SD; residual:
  lossy-across-restarts/shallow → fall back to journalctl; P6-6 to ratify).

## Tests (`tests/control/test_models.py` 6, `test_logs.py` 7)

envelope: ok/fail shapes; success+error / error-without-error / error+data all rejected; ok(None)
valid. logs: bounded eviction (oldest dropped); emit scrubs `sk-…`; emit stamps via the injected
clock; query filters by station substring / minimum level / since; newest-first + limited.

## Gate

ruff + ruff-format + mypy `--strict` clean (58 source files); **807 tests** (+13), 97.53% coverage.
Deps added: `fastapi`, `uvicorn` (plain, no `[standard]`); dev `pytest-socket`.

## Next

P6-2: `control/service.py` read paths (list_stations / now_playing / schedule) over a fake
coordinator — focused-panel test review.
