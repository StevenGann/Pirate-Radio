# Phase 6 Implementation Plan — FastAPI Control API — **Rev 2 (for re-vote)**

> **Status:** Rev 2 — folds the **Rev-1 full-seven vote (3 AYE / 4 NAY → REVISE)**. Rev-1 NAYs:
> Devil's Advocate (`regenerate` races the live-day schedule file the player reads; no crash
> isolation; log-deque not thread-safe + secrets unscrubbed; R8′ silently re-defined), Old Man (skip
> churns the frozen `run_once` mid-segment; 7 modules / `[standard]` / `Generic[T]` / `meta`
> over-built), QA (skip-seam + R23 gates not falsifiable), Field-Op (bind host/port + firewall
> unspecified). AYE: Senior (architecture sound; make the skip churn explicit), RPi (loop-sharing +
> memory fine; pin `regenerate` single-flight; drop `[standard]`), Fact-Checker (all repo/external
> claims accurate). **Every NAY point folded below** (marked "Rev-2"). Charter ≤1 NAY adopts. Design:
> §15 endpoints, §21 D4 / R23 / R8′.

## Goal & non-goals

**Goal.** A FastAPI REST control plane (D4, the last v1 feature) over the running daemon. Endpoints
(§15): `GET /health`, `GET /stations`, `GET /stations/{name}/now`, `GET /stations/{name}/schedule?date=`,
`POST /stations/{name}/regenerate`, `POST /stations/{name}/skip`, `GET /logs?station=&level=&since=&limit=`.
Consistent **envelope**; unknown `{name}` → **404**; mutating + inspection routes require **bearer
auth**; handlers **non-blocking** (R23).

**Non-goals.** No browser UI; no websockets/SSE; no multi-user auth; no durable metrics store; no
per-station stop/pause/restart lever in v1 (documented gap — use `systemctl restart` or `regenerate`/
`skip`). API binds **loopback by default** (operator tunnels over ssh or opts into a LAN bind).

## Rev-2 dependency decision (Old Man / RPi)

`pyproject` adds **plain `fastapi` + `uvicorn`** (NOT `uvicorn[standard]` — its `watchfiles`/dev-reload
+ `websockets` are dead weight on a daemon; `httptools`/`uvloop` not needed for a homelab control
plane). `httpx` (already a dep) backs the in-process `TestClient`. Dev-only: **`pytest-socket`** with
`--disable-socket --allow-unix-socket` so "no socket bind on CI" (R21) is a *harness-enforced* gate,
not reviewer vigilance. FastAPI/uvicorn import only inside `control/`.

## Architecture (`src/pirate_radio/control/` — Rev-2 collapsed 7 → 5)

```
control/
  models.py   NEW  the envelope (ok()/fail(); {success,data,error} — NO Generic[T], NO meta) + the
                   response DTOs (StationView, NowPlayingView, ScheduleView, LogEntry) + ApiError(code,msg)
  logs.py     NEW  RingLogHandler (bounded deque, LOCKED emit/snapshot, scrub_secrets in emit) +
                   query_logs(...) PURE filter (station/level/since/limit, newest-first)
  service.py  NEW  ControlService over the Coordinator: list_stations / now_playing / schedule /
                   regenerate / skip — typed, raises StationNotFound; the testable core (no FastAPI)
  api.py      NEW  bearer-auth dependency + create_app(service, log_ring, *, token_env, offload) ->
                   FastAPI; routes, envelope wiring, 404/401/422 handlers
  server.py   NEW  serve(app, *, host, port) — uvicorn programmatic (bind pragma'd); host default 127.0.0.1
```

Coordinator gains: a per-station **skip `asyncio.Event`** + a per-station **regen `asyncio.Lock`**, a
`now_playing(name)` read, and an **async** `regenerate_station(name)` that holds the lock. The daemon
entrypoint runs the API as a **crash-isolated** task alongside `coordinator.run()`. Config gains
`control.enabled` (default on for Pi 4/5, off-able for Pi 3) + `control.host`/`control.port`.
`docs/ops/control-api.md` runbook + the systemd-unit port/bind note.

## Skip — Rev-2: skip-at-next-boundary (NO mid-segment cancel)

Rev-1 proposed racing/cancelling the in-flight `sink.play`. **Rejected** (Old Man + DA + Fact-Checker):
`SoundDeviceSink.play` writes the whole segment buffer on its dedicated executor thread, so cancelling
the *await* abandons nothing — the device still drains the buffer (a "skip" that skips nothing) — and
it churns the deliberately-frozen `run_once`/`Player` hot loop (the day-roll seam was built to *never*
cut a segment). **Rev-2:** the player checks a per-station skip `asyncio.Event` **at the loop top
(between segments)**; when set, it drops the next buffered segment and clears the event (the gap is
R11-covered). Semantics, documented precisely: `/skip` **advances past the next item boundary** — it
does NOT cut the currently-airing item mid-play (the design never interrupts a segment). One injected
`asyncio.Event` threaded through `run_once`→`Player` (same shape + back-compat default `None` as the
existing seams), virtual-time-testable (`FakeAudioSink.played` shows the dropped segment absent). True
mid-segment skip (needs a chunked, cancellable sink) is a documented later increment.

## Regenerate — Rev-2: single-flight, lock-serialized, future-safe (DA CRITICAL)

`POST /regenerate` returns **202 Accepted** and runs `Coordinator.regenerate_station(name)`, which:
(1) holds a **per-station `asyncio.Lock`** shared with the **midnight task** (so an API regen can never
interleave with the 00:00 roll or a second concurrent API regen → no torn `.bak`/half-written file);
(2) offloads the synchronous generate+atomic-write via the injected `offload` (to_thread) so the loop
never blocks (R23); (3) regenerates the **on-disk** schedule for the day — the **live in-memory
broadcast is unaffected**; the station picks it up on its next day-roll or restart (identical to the
`--regenerate` oneshot semantics, documented). The midnight task is refactored to acquire the same
per-station lock around its `prepare_next_day`. This closes the live-day file race. (Implementation
latitude — Old Man: `atomic_write_json` is already rename-atomic, so the serialization only needs to
prevent API-regen / midnight-roll / a second concurrent regen from interleaving on the SAME path's
`.bak` rotation; a plain in-process serialization achieving that is acceptable as long as the P6-3
"serialized vs midnight + concurrent" test passes.)

## R8′ deviation — explicit (DA / Old Man / RPi / Field-Op)

Design R8′ says `GET /logs` "must be backed by a journald query or an indexed SQLite store — never a
linear scan." **Rev-2 deviates deliberately:** a **bounded in-memory ring buffer** (`deque(maxlen=N)`).
Rationale: it never reads the SD card (H26), is R23-safe (no disk I/O in the handler), and is far
simpler. **Residual (documented in the runbook):** the ring is **lossy across restarts and shallow**
(only the last N records) — for deep/historical forensics the operator falls back to `journalctl`.
This deviation is flagged for the panel + the P6-6 deep-dive to ratify (it does NOT silently re-use
the R8′ number).

## Security / bind — Rev-2 (Field-Op / DA)

- **Bearer token** by env-name (`PIRATE_API_TOKEN`, H22), `secrets.compare_digest` (constant-time;
  the test asserts *usage*, not timing), never logged. **Fail-fast if unset** when `control.enabled`
  — no open-by-default. `/health` is the only unauthenticated route and returns NO station data.
- **Bind default `127.0.0.1`** (loopback). A LAN bind is an explicit opt-in (`control.host`); the
  runbook + systemd note document ssh-tunnel-by-default and a `ufw`/`IPAddressAllow` example. Never
  `0.0.0.0`.
- **Operator-side token hygiene (Field-Op):** the runbook MUST show invoking `curl` without leaking
  the token into the operator's own shell history — `curl -K <file>` / `--netrc-file` / a `0600`
  config, or `read -s` — never an inline `-H "Authorization: Bearer <literal>"`. It MUST also document
  **token rotation** (edit the `EnvironmentFile`, `systemctl restart` picks up the new token).
- **Crash isolation (H-A5):** the API runs as a task whose failure is caught/logged and **never
  cancels `coordinator.run()`** (a shielded wrapper, not a bare `gather` sibling) — the broadcast
  outlives the control plane. Tested: kill the API task, assert the stations keep airing.
- **Log scrubbing:** `RingLogHandler.emit` runs `scrub_secrets` on each record before storing, so a
  token/key in a log line can never surface via `/logs`. Tested.

## Increment breakdown (strict spec-driven TDD)

- **P6-1 — `models.py` + `logs.py`** (PURE). Gate: envelope `ok()`/`fail()` enforce **data-xor-error**
  (a malformed combo raises); `RingLogHandler` bounded eviction + **locked emit/snapshot** + `scrub_
  secrets` in emit (a logged secret never reaches the ring); `query_logs` filters station/level/`since`
  (records clock-stamped at capture, injected clock — no wall-time) + caps `limit`, newest-first.
- **P6-2 — `service.py` read paths** (`list_stations`/`now_playing`/`schedule`) over a FAKE coordinator
  + injected schedule-reader. Gate: views from the registry; now-playing via `find_now`; schedule via
  the injected reader (no real FS); unknown name → `StationNotFound`. **Focused-panel test review.**
- **P6-3 — `service.py` control paths + the seams**: the skip `asyncio.Event` (player loop-top check,
  back-compat threaded through `run_once`/`play_day`/`Station`) + the regen `asyncio.Lock`
  (`Coordinator.regenerate_station`, shared with the midnight task). Gate: `skip` sets the event and a
  virtual-time `run_once` test shows the next segment dropped; `regenerate_station` holds the lock
  (a second concurrent call + a simulated midnight regen are serialized — asserted) and offloads via
  the injected `offload`; unknown name → `StationNotFound`.
- **P6-4 — `api.py` + auth** (`TestClient`). Gate: every route returns the envelope; unknown `{name}`
  → 404 + envelope; missing/wrong token → 401, right token → 200, `/health` open; bad query → 422;
  skip/regenerate → 202 **and** the side effect asserted (event set / `regenerate_station` called on
  the fake); **R23 offload is an injected dependency** and the test asserts the schedule read ran
  through it (not on the loop); token by env-name + fail-fast if unset. `pytest-socket` proves no bind.
- **P6-5 — `server.py` + `__main__` integration + config**. Gate: `serve` builds a uvicorn `Config`
  with `host`/`port` (bind line pragma'd, default 127.0.0.1); the entrypoint launches the API as a
  **crash-isolated** task (test: API task raises → `coordinator.run()` keeps running); `control.enabled`
  gates it; `docs/ops/control-api.md` + the systemd unit port/bind note shipped.
- **P6-6 — Phase-6 deep-dive** (full-seven; must ratify the R8′ ring-buffer deviation + the
  skip-at-boundary semantics) + housekeeping.

## §21 coverage

**Implemented:** D4 (envelope + 404 + bearer auth), R23 (injected-offload handlers), §15 endpoints,
R8′-as-ring (deviation, ratified). **Reused:** `Coordinator.registry`/`regenerate_now` (refactored to
`regenerate_station` + lock), `StationStatus`, `find_now`, `load_with_recovery`, `main(argv,*,deps)`,
`scrub_secrets`. **Deferred (honest):** browser UI, websockets push, multi-user auth, durable log
store, per-station stop/restart, true mid-segment skip, API rate-limiting (loopback-bound, single
token).

## Risks & hardening

- **H-A1 loop starvation (R23)** → injected `offload` for every sync IO + `regenerate`; asserted.
- **H-A2 regenerate live-day race (DA CRITICAL)** → per-station `asyncio.Lock` shared with midnight;
  on-disk only; effect at next roll/restart; single-flight; tested vs concurrent + midnight.
- **H-A3 auth bypass / token leak** → constant-time, env-name, fail-fast, `/health` data-free,
  scrub in the log handler.
- **H-A4 skip dead air / churn** → boundary-skip Event (no mid-segment cut, no sink surgery); gap
  R11-covered; documented semantics.
- **H-A5 API crash kills broadcast** → crash-isolated task; tested.
- **H-A6 log ring thread-safety / secrets** → locked emit+snapshot; `scrub_secrets` in emit; bounded.
- **H-A7 exposed bind** → default 127.0.0.1; LAN opt-in; firewall/ssh-tunnel runbook + unit note.

## Acceptance checklist

- [ ] All §15 endpoints; envelope `{success,data,error}`; documented 404/401/422/200/202.
- [ ] Bearer auth (constant-time, env-name, fail-fast, `/health` open + data-free); never logged.
- [ ] R23 via an injected offload seam, asserted; no blocking handler.
- [ ] `regenerate` lock-serialized vs midnight + concurrent calls; on-disk only; 202.
- [ ] skip = boundary Event (next-item drop), virtual-time-tested; no run_once hot-loop cut.
- [ ] `/logs` from the bounded, locked, scrubbed ring (R8′ deviation ratified); `since` via injected clock.
- [ ] API crash never cancels `coordinator.run()`; bind default 127.0.0.1; `control.enabled` flag.
- [ ] TestClient routes (no socket; `pytest-socket` enforced); service pure-tested; only uvicorn bind pragma'd.
- [ ] plain `uvicorn` (no `[standard]`); `docs/ops/control-api.md` + systemd port/bind note.
