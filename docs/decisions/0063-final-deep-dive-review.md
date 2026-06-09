# 0063 — Final full-team deep-dive (whole-system code-quality + documentation) + remediation

The overnight-mandate closer: a full-seven review of the **assembled system** (phases 0→6 — 62 source
files / ~6.6k LOC, ~11k LOC tests, plus README, design doc, and the ops runbooks), each persona on a
whole-system lens (not re-litigating ratified per-phase decisions).

## Panel result: CONFIRM ×3, DISPUTE ×4 → remediated → re-poll → **all 7 CONFIRM**

- **CONFIRM (round 1):** Old Man (system lean; deps all justified; control API didn't sprawl — one
  HIGH dead-code finding flagged for cleanup), RPi Expert (Pi-deployment-grade — conditional on the
  `/tmp` fix), QA Engineer (green CI honest; LOW caveats only).
- **DISPUTE (round 1):** Senior Dev, Fact Checker, Devil's Advocate, Field Operator — real
  CRITICAL/HIGH in cross-cutting concerns, integration seams, and documentation. All remediated below.
- **Re-poll (after remediation):** Senior Dev, Fact Checker, Devil's Advocate, Field Operator all
  **flipped to CONFIRM** — each re-verified their findings closed (DA proved the SIGTERM drain
  end-to-end with a real signal through the 3-level nested gather: all sinks close, no task leak, no
  deadlock; Fact Checker re-derived the gate; Senior Dev confirmed the single-sink scrub filter;
  Field Operator re-walked blank-Pi→on-air from docs alone). **Unanimous CONFIRM (7/7).**

## Findings remediated

### Code
1. **[HIGH — Senior Dev] The journald/stdout stream was not secret-scrubbed** (only the `/logs` ring +
   some call sites). **Fix:** new leaf module `scrub.py` with `scrub_secrets` + a `SecretScrubFilter`
   attached to the journald `StreamHandler` in `logging_setup.py` — the operator stream is now scrubbed
   at the sink, so a secret in a bubbled third-party exception can never reach journald verbatim. Test
   added.
2. **[MEDIUM — Senior Dev] `scrub_secrets` lived in `supervisor.py`** (the tagger + control API
   imported the broadcast supervisor just for it). **Fix:** relocated to `scrub.py`; `supervisor.py`
   re-exports for back-compat; `control/logs.py` + `tagging/tagger.py` import from the leaf.
3. **[HIGH — DA] Midnight day-roll ran `prepare_next_day` (full-day generate + fsync-heavy write)
   SYNCHRONOUSLY on the event loop** — a multi-second all-station xrun every midnight on a Pi. **Fix:**
   `MidnightTask` takes an injected `offload` (default `asyncio.to_thread`, mirroring
   `Coordinator.regenerate_station`) and awaits the write off the loop, under the same regen lock.
4. **[HIGH — DA] No SIGTERM handling** — `systemctl stop`/`restart` (the documented routine op)
   hard-killed the daemon; the sink `__aexit__` never ran (abandoned PortAudio/ALSA handle). **Fix:**
   `_run_daemon` installs SIGTERM/SIGINT handlers that cancel the runner and drain, so every
   `async with self._sink` unwinds through `__aexit__`; clean exit 0. systemd unit gains
   `TimeoutStopSec=15`. Test added (`test_run_daemon_drains_the_broadcast_on_shutdown`).
5. **[HIGH — RPi] Piper/espeak temp WAVs landed on the boot SD** (`/tmp` is not tmpfs on Bookworm) —
   per-render SD wear, the unattended-Pi killer. **Fix:** `PrivateTmp=yes` in the systemd unit (private
   tmpfs-backed `/tmp`); documented in first-boot §0.
6. **[HIGH — Old Man] Dead poison-skip machinery in the Supervisor** (`PoisonItemError` is never
   raised; no production unit implements `skip_item`). **Fix:** deleted `PoisonItemError`, the
   supervisor poison branch + `poison_threshold`/`max_skips` params/constants, and the `skip_item`
   Protocol mention; the supervisor collapses to restart-to-known-good + sibling isolation + ceiling.
   Also deleted the dead `worst_case_track_render` + `_DECODE_TIMEOUT_DEFAULT` (only test callers).
7. **[LOW — Senior Dev] `errors.py` header docstring** described a Phase-0 state ("provider taxonomy
   not here yet"). **Fix:** updated to the assembled phases-0–6 taxonomy.

### Documentation
8. **[CRITICAL — Field-Op] Grid authoring + [CRITICAL] content-folder→group layout were undocumented**
   — the documented first-boot path was non-completable by a code-blind operator. **Fix:** new
   `docs/ops/grids.md` (content layout, accepted extensions, grid YAML schema, filename resolution,
   the 00:00→24:00 tiling rule, a worked `default.yaml`, validation-error glossary); first-boot step 6
   now requires it before the dry-run.
9. **[HIGH — Field-Op] RF legality not surfaced.** **Fix:** a ⚠️ legality note at the top of `README.md`
   and `first-boot.md` §0 (Part 15 / licence / confirm-before-transmit / wired-only sidesteps it).
10. **[HIGH — Fact-Checker, Field-Op] README stale** — claimed "Phases 0–3 / not yet deployable" and a
    wrong gate (566 tests / ~99%). **Fix:** §Status rewritten to 0–6 complete; gate line corrected to
    865 tests / ~97%; governance decision range `0001`–`0063`.
11. **[MEDIUM — Fact-Checker] Design-doc §8.4** persisted to the wrong path
    (`<schedule_dir>/generated/…`). **Fix:** corrected to `<state_dir>/<station>/<date>.json` with an
    A6 correction note.
12. **[MEDIUM — Field-Op] Operability gaps.** **Fix:** `config.example.json` `audio_device` → `pirate1`
    (matches the udev recipe); new `docs/ops/config-reference.md` (every field + default + range,
    incl. `dj_personality` XOR `dj_personality_file`); first-boot "Recovery & troubleshooting"
    (journald vocabulary, terminal-`failed` recovery via `reset-failed`, disk-full mitigation, clean
    SIGTERM stop); `.env.example` lists `PIRATE_API_TOKEN`.
13. **[MEDIUM — RPi] RAM-budget framing.** **Fix:** first-boot §0 documents that the fail-fast budgets
    the audio buffers specifically (baseline RSS adds on top) and that one outlier-length track gates
    the fleet.

## Carry-forward (non-blocking, recorded — no reviewer blocks v1 on these)

- **Stale day-roll Event** (`station.py`): if the midnight task fires `signal_day_roll()` while a
  station is not parked on `day_roll.wait()` (crashed/in-backoff, or airing a tail past 00:00), the
  Event stays set and causes a *single* spurious same-day re-slice. Recoverable, low blast radius,
  unmodeled — a date-compare guard (roll keyed on an actual date change, not just the Event edge) is
  the clean fix (DA MEDIUM, both rounds).
- Station's own daily reload (`station.py` `_load_or_generate`) doesn't take `regen_lock`; safe today
  purely via `os.replace` atomicity — would become a torn read if a non-atomic write path is ever
  added (DA LOW).
- Converge the two atomic-write durability helpers (`persistence` vs `tag_writer`) — a deliberate
  refactor; both are individually correct, differing only in dir-fsync error policy (Senior Dev
  MEDIUM, accepted as carry-forward).
- Delete the dead `UdevAudioDeviceResolver.device_index` by-name method (has a resolve-invariant test;
  Old Man LOW).
- `LLMConfig.max_requests_per_minute` is a reserved/unenforced field (named in the docstring; Old Man).

## Final gate

ruff + ruff-format + mypy `--strict` clean (62 source files); **865 tests**, 97.37% coverage.

## Status

**Overnight build mandate COMPLETE.** PiRate Radio is built through design-doc §20 phases 0→6,
each phase committed and full-seven deep-dived, with this final whole-system code-quality +
documentation review and its remediation. The system is a deployable multi-station FM broadcaster with
an AI DJ, two-tier supervision, DST-correct day-roll, graceful shutdown, an offline tagger, an optional
control API, and a complete operator runbook set.
