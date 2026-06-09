# P6-4 — `control/api.py` (FastAPI routes + bearer auth)

Strict spec-driven TDD (tests from the adopted Phase-6 plan §P6-4 → RED → GREEN → gate); the HTTP edge
over `ControlService`, in-process `TestClient` only.

## Implementation

- **`create_app(*, service, log_ring, token_env="PIRATE_API_TOKEN", offload=asyncio.to_thread)`** —
  reads the bearer token by env-NAME at creation; **fail-fast `ConfigError` if unset** (never
  open-by-default, H22). Routes (§15): `GET /health` (open, data-free), `GET /stations`, `GET
  /stations/{name}/now`, `GET /stations/{name}/schedule?date=`, `POST .../regenerate` (202), `POST
  .../skip` (202), `GET /logs?station=&level=&since=&limit=`.
- **Auth** — a manual `Authorization` header check with `secrets.compare_digest` (constant-time);
  missing/wrong → `_Unauthorized` → 401 ENVELOPE (a custom exception so the 401 is enveloped, not
  FastAPI's bare default).
- **Envelope everywhere** — routes return `ApiResponse` (`ok(...)`); exception handlers map
  `StationNotFound`/`ScheduleNotFound` → 404 and `_Unauthorized` → 401, each as the `{success, data,
  error}` envelope; a bad `?date=`/`?since=` → FastAPI 422.
- **R23** — the blocking reads (`now_playing`, `schedule` — they touch the schedule file) run through
  the injected `offload`; a test asserts the schedule read went through it (not on the loop).

## Tests (`tests/control/test_api.py`, 12)

`pytestmark = disable_socket` (+ `--allow-unix-socket` so asyncio's AF_UNIX self-pipe works) proves
the in-process `TestClient` binds **no real TCP socket** (R21). Covers: fail-fast on missing token;
`/health` open + data-free; 401 (missing/wrong) vs 200 (right token); 404 + envelope on unknown name;
now-playing ok; **schedule read offloaded** (R23 seam asserted); bad date → 422; skip/regenerate →
202 + the side effect; unknown skip → 404 (not invoked); `/logs` filtered from the ring.

## Gate

ruff + ruff-format + mypy `--strict` clean (60 source files); **838 tests** (+12), 97.62% coverage.
(One harmless third-party `StarletteDeprecationWarning` about httpx in TestClient.)

## Next

P6-5: `control/server.py` (uvicorn, bind default 127.0.0.1) + `__main__` integration (crash-isolated
API task, `control.enabled`) + `docs/ops/control-api.md`.
