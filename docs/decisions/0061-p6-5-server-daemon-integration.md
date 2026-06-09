# P6-5 — control server + daemon integration (`ControlConfig`, crash-isolated API task)

Strict spec-driven TDD (tests from the adopted Phase-6 plan §P6-5 → RED → GREEN → gate). This is the
integration-glue increment that wires the P6-1..P6-4 control plane into the live daemon, so per the
documented efficiency stance (decision 0038) it folds prior-panel lessons directly and relies on the
P6-6 phase deep-dive as the backstop — no standalone panel review of these tests.

## Implementation

- **`control/server.py`** — `make_server(app, *, host, port)` builds a `uvicorn.Server` over
  `uvicorn.Config(..., log_level="info", access_log=False)` **without opening a socket** (unit-testable
  host/port wiring). `serve(app, *, host, port)` awaits the real bind — the only network-adjacent line
  (`pragma: no cover`); it shares the daemon's event loop (R23) and is launched crash-isolated.
- **`config.ControlConfig`** — `enabled=True`, `host="127.0.0.1"` (loopback default; never `0.0.0.0`
  without intent), `port=8080` (ge1/le65535), `token_env="PIRATE_API_TOKEN"`, `log_ring_size=2000`
  (ge1). `DaemonConfig.control: ControlConfig | None = None` — **absent ⇒ no control plane** (safe
  default for a Pi 3 / closed deployment).
- **`Coordinator`** — `build_control_service()` wires a `ControlService` over the live `registry`,
  `configs`, `clock`, a `state_dir` schedule loader, and the `skip`/`regenerate_station` actions.
  (`skip`/`regenerate_station` + the injected `offload` landed in P6-3.)
- **`__main__`** — `MainDeps.build_api: Callable[[DaemonConfig, Coordinator], Coroutine|None] | None`.
  `main` builds `api_coro = deps.build_api(config, coordinator)` (or `None`) and hands
  `_run_daemon(coordinator, api_coro=...)` to `deps.run`. `_run_daemon` gathers `coordinator.run()`
  with `_isolated(api_coro, name="control-api")`; `_isolated` re-raises `CancelledError` but
  **swallows+logs any other exception** so an API crash NEVER cancels the broadcast (H-A5). The prod
  `build_api` (pragma'd) attaches a `RingLogHandler` to the root logger, `create_app(...)`, and returns
  `serve(...)` — or `None` when `control` is absent/`enabled=False`.

## Tests

- `tests/control/test_server.py` (1) — `make_server` builds a server bound to the given host/port
  without opening a socket.
- `tests/test_coordinator.py` (+1) — `build_control_service` lists stations in config order and its
  `skip` routes to the station's skip `Event`.
- `tests/test_main.py` (+3) — `_isolated` swallows a task crash; `_run_daemon` runs the broadcast to
  completion despite an API-coro crash; `main` consults `build_api` when a factory is provided.

## Gate

ruff + ruff-format + mypy `--strict` clean (61 source files); **843 tests**, 97.33% coverage.

## Docs

`docs/ops/control-api.md` — the operator runbook: enable/disable, loopback-default + SSH-tunnel (do
not LAN-bind), token in the root-owned 0600 `EnvironmentFile` (by name, never value), token rotation
via rewrite+restart, leak-safe `curl` (`read -s` / `-K` config file), the endpoint table with the
skip-at-boundary and regenerate-at-next-roll semantics, and the **`/logs` ring lossy-across-restarts
caveat** (journald is the durable source of truth).

## Next

P6-6: Phase-6 housekeeping + full-seven deep-dive (must ratify the R8′ ring-buffer deviation and the
skip-at-next-boundary semantics), then remediate any CRITICAL/HIGH.
