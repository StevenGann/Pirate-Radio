# Phase-6 plan — Rev 1 vote + Rev 2 adoption (FastAPI control API)

## Rev 1 — full-seven vote: 3 AYE / 4 NAY → REVISE

- **AYE:** Senior Dev (architecture/service-split/envelope/loop-integration sound; make the skip churn
  explicit), RPi Expert (loop-sharing + memory fine; pin `regenerate` single-flight; drop `[standard]`),
  Fact Checker (every repo reuse claim + external fact CONFIRMED; skip-vs-frozen-run_once honestly
  labelled).
- **NAY (substantive, convergent):**
  - **Devil's Advocate** — `regenerate_now` mutates the LIVE day's schedule file the player reads, no
    lock, races the midnight roll (`to_thread` hides the loop-block, not the file race); no API-crash
    isolation (bare `gather` cancels the broadcast); the log `deque` isn't thread-safe + secrets
    unscrubbed into `/logs`; mid-segment skip can't work (the sink drains the whole buffer on its
    thread); R8′ silently re-defined.
  - **Old Man** — skip churns the frozen `run_once` mid-segment; over-built (7 modules,
    `uvicorn[standard]`, `Generic[T]` envelope, `meta`, `ActionResult`).
  - **QA** — the skip-seam gate ("set event, assert advanced") and the R23 gate ("assert to_thread")
    were unfalsifiable.
  - **Field Operator** — API bind host/port default + firewall guidance unspecified; systemd unit gave
    no network confinement (0.0.0.0 exposure risk).

## Rev 2 — every NAY folded; re-vote of the four NAYs: 3 AYE / 1 NAY

Combined with the Rev-1 Senior + RPi AYE + Fact-Checker CONFIRM → **ADOPTED (effectively 6 AYE / 1
NAY; ≤1 NAY charter)**. Folded:

- **Regenerate (DA CRITICAL):** `POST /regenerate` → 202; `Coordinator.regenerate_station(name)` holds
  a **per-station serialization shared with the midnight task** (no interleave with the 00:00 roll or a
  concurrent regen), offloads via the injected `offload` (R23), writes the **on-disk** schedule only
  (live broadcast unaffected; effect at next roll/restart, like `--regenerate`). Old Man latitude:
  since `atomic_write_json` is rename-atomic, a plain in-process serialization is acceptable as long as
  the P6-3 "serialized vs midnight + concurrent" test passes.
- **Skip (Old Man/DA/QA/Senior/Fact-Checker):** **skip-at-next-boundary** — a per-station
  `asyncio.Event` checked at the player loop top (between segments); `/skip` advances past the next
  item boundary, never cuts the airing segment (the sink can't be cut without surgery); virtual-time
  test asserts the dropped segment is absent from `FakeAudioSink.played`. True mid-segment skip
  deferred.
- **Crash isolation (DA):** the API runs as a crash-isolated task; an API failure never cancels
  `coordinator.run()` (tested).
- **Log ring (DA):** `RingLogHandler` locked emit/snapshot + `scrub_secrets` in emit (a logged secret
  never reaches `/logs`); bounded; `since` via injected clock.
- **R8′ deviation (all):** the ring buffer is an EXPLICIT documented deviation from R8′
  (journald/SQLite), residual stated (lossy across restarts / shallow → fall back to `journalctl`),
  flagged for the P6-6 deep-dive to ratify — not smuggled under the R8′ number.
- **Security/bind (Field-Op):** default bind `127.0.0.1`; LAN opt-in; firewall/ssh-tunnel + systemd
  note; token fail-fast/env-name/constant-time/never-logged; `/health` open + data-free;
  `control.enabled` flag (off-able on Pi 3). Rev-2.1: runbook documents **operator-side** token
  hygiene (`curl -K`/`--netrc`/`read -s`, never inline) + token rotation (folds the lone Rev-2 NAY).
- **Build/deps (Old Man/RPi):** plain `fastapi` + `uvicorn` (no `[standard]`); envelope
  `{success,data,error}` via `ok()/fail()` (no `Generic[T]`, no `meta`); 7→5 modules; `pytest-socket`
  dev-dep so "no socket bind" (R21) is harness-enforced.
- **R23 falsifiable (QA):** the blocking offload is an injected dependency; tests assert work ran
  through it, not on the loop.

## Build order

P6-1 models(envelope+DTOs)+logs → P6-2 service read paths (focused-panel test review) → P6-3 service
control paths + skip Event + regen lock seams → P6-4 api.py + auth (TestClient) → P6-5 server +
`__main__` integration + config + runbook → P6-6 deep-dive. Strict spec-driven TDD; decision per
increment.
