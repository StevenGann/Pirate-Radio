# P6-6 — Phase-6 full-seven deep-dive + remediation (phase gate)

The mandated phase-gate review of the assembled control plane (P6-1…P6-5). Seven persona agents
(opus) reviewed the `control/` package + the integration seams (skip Event, regen lock, crash-isolated
API task, `ControlConfig`) against the adopted Rev-2 plan, with two mandatory ratification asks: the
**R8′ ring-buffer deviation** (`/logs` from an in-memory ring, not journald/SQLite) and the
**skip-at-next-boundary** semantics.

## Panel result: CONFIRM ×4, DISPUTE ×3 → remediated → re-poll CONFIRM

- **CONFIRM (round 1):** Senior Dev, Old Man, RPi Expert, Fact Checker. Both ratification asks
  RATIFIED by all (the ring is RAM-only — never the SD card (H26), R23-safe, secret-scrubbed, journald
  the documented source of truth; skip never cuts the airing segment — the sink writes a whole buffer
  on its own thread). Fact Checker re-derived every gate number (843/97.33%/61 files/mypy-strict).
- **DISPUTE (round 1):** Devil's Advocate, QA Engineer, Field Operator — each found real CRITICAL/HIGH
  in the seams the unit tests didn't cross. All remediated below; on re-poll DA + Field-Op flipped to
  CONFIRM, and QA's two coverage-theatre findings were fixed with mutation-verified tests.

## Findings remediated

1. **[CRITICAL — Field-Op] A clean API-task exit was invisible.** `_isolated` logged only on
   `Exception`; a clean `serve()` return left the control plane dead with no trace while the broadcast
   ran on. **Fix:** `_isolated` now logs a WARNING on ANY exit (`"control-api task exited (broadcast
   continues; control plane is now down)"`); runbook adds a "Detecting a dead control plane" section
   (greppable `control-api task (crashed|exited)` + a `/health` probe one-liner). Test:
   `test_isolated_logs_loudly_on_a_clean_exit`.
2. **[CRITICAL — QA] Ring thread-safety was claimed + locked but untested.** The lock is the stated
   R8′ safety mechanism (logging threads append, the async route reads). **Fix:** a mutation-sensitive
   `test_emit_and_snapshot_acquire_the_lock` (a `_TrackingLock` proves both paths genuinely take the
   lock — CPython's GIL makes a no-lock deque test pass regardless, so this pins the mechanism, not the
   GIL), plus a concurrent-emit/snapshot smoke test for the bound-under-contention.
3. **[HIGH — DA] Stale skip leaked across the day-roll** and silently dropped the new day's opening
   station-ID. **Fix:** `Station.run` clears `self._skip` at each slice start, so a skip applies only
   within the slice it was issued in. Test: `test_run_clears_a_stale_skip_at_each_slice_start`.
4. **[HIGH — QA] "skip never cuts the airing segment" was asserted nowhere** (the deferral-justifying
   half of the contract). **Fix:** `test_skip_during_airing_does_not_cut_the_current_segment` — a sink
   sets the skip Event mid-s0; asserts s0 airs in full, s1 (the next) is dropped, s2 airs.
5. **[HIGH — DA, Fact-Checker] Un-enveloped 500s.** `GET /logs?since=<naive>` raised naive-vs-aware
   TypeError; a non-ASCII `Authorization` byte raised TypeError in `compare_digest`. **Fix:** the
   route coerces a naive `since` to UTC; `_require_token` guards `compare_digest` (non-ASCII → 401,
   fail-closed); a catch-all `@app.exception_handler(Exception)` makes the `{success,data,error}`
   envelope TOTAL (500 envelope, internals never leak). Tests: naive-since (non-empty ring, comparison
   exercised), non-ASCII auth, malformed-scheme (parametrized), catch-all 500.
6. **[HIGH — RPi] `RingLogHandler.emit` ran scrub + pydantic per record on the caller's thread**
   (incl. the sink executor). **Fix:** `ring.setLevel(logging.INFO)` in prod wiring — DEBUG (the
   high-frequency tier) no longer pays the cost on the timing-sensitive path.
7. **[HIGH — QA] regen-lock-vs-midnight serialization untested end-to-end.** **Fix:**
   `test_midnight_roll_waits_for_an_in_flight_regen_on_the_shared_lock` runs the real `MidnightTask`;
   an in-flight regen holds `regen_lock`, the roll blocks then proceeds — genuine lock contention.
8. **[HIGH — QA] auth had no malformed-scheme coverage.** **Fix:** parametrized 401 tests
   (no-prefix, wrong-case, trailing-space, empty, wrong-word).
9. **[MEDIUM] `ControlConfig` had zero direct tests; `log_ring_size`/`limit` unbounded; `/logs`
   `?station=` is a substring match.** **Fix:** `tests/control/test_control_config.py` (loopback +
   off-by-default + port/ring-size range + frozen/forbid-extra); `log_ring_size` capped `le=100_000`,
   `limit` `Query(ge=1, le=10000)`; the substring semantics documented honestly in the `query_logs`
   docstring + runbook.
10. **[MEDIUM — Field-Op] Runbook operability gaps.** **Fix:** `docs/ops/control-api.md` adds a
    Troubleshooting section (401-after-rotation-needs-restart; missing-token startup error;
    connection-refused; empty `/logs`), a concrete `ufw` LAN-bind 3-step sequence, and the
    double-skip / degraded-stretch / stale-skip-cleared-at-midnight nuances; `first-boot.md` adds the
    `state_dir` MUST equal `StateDirectory` note.

## Ratifications (both ASKS, unanimous)

- **R8′ deviation RATIFIED.** The in-memory ring is the correct v1 call: RAM-only (never the SD card,
  H26), R23-safe (no disk I/O in the handler), secret-scrubbed, bounded + thread-safe, with journald
  as the documented durable source of truth. The residual (lossy across restarts, shallow) is stated
  in the module docstring, this decision lineage, and the runbook.
- **skip-at-next-boundary RATIFIED.** A one-shot `asyncio.Event` checked at the player loop top drops
  the next buffered segment and never cuts the airing one (a mid-segment cut is structurally
  impossible — the sink writes a whole buffer on its own thread). Now also cleared at each slice
  boundary so it cannot leak across midnight.

## Final gate

ruff + ruff-format + mypy `--strict` clean (61 source files); **869 tests** (+26 from 843), 97.34%
coverage. Both remediation tests for the QA-disputed items verified mutation-sensitive (removing the
lock / the naive coercion makes them fail).

## Phase 6 status

**COMPLETE.** The FastAPI control plane is built, reviewed by the full seven, remediated, and green:
`{success,data,error}` envelope, constant-time bearer auth (fail-fast + fail-closed), read paths
(stations/now/schedule) + write actions (skip-at-boundary, lock-serialized regenerate), the bounded
secret-scrubbing `/logs` ring (R8′), loopback-default + off-by-default config, a crash-isolated daemon
task with a visible-death log line, and an operator runbook.
