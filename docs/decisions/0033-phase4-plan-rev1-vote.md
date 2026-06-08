# 0033 — Phase 4 plan (multi-station) — Rev-1 panel vote: REVISE (5 AYE / 2 NAY)

The seven-agent panel reviewed `docs/plans/phase-4-implementation-plan.md` Rev 1. **Tally: 5 AYE
(Senior Dev, Old Man, RPi Expert, Fact Checker, QA) / 2 NAY (Devil's Advocate, Field Operator)
→ REVISE + re-vote** per the ≥2-NAY charter. Fact Checker verified **every** referenced symbol /
field / signature / design-doc section against the tree — no corrections; the plan's seam claims
are accurate and the team may build on them. This record is the **consolidated Rev-2 revision
brief** (the convergent must-fixes the planner must fold in, then re-vote).

## Adopt-blocking CRITICALs (the two NAYs + the RPi CRITICALs)

- **C1 (DA) — the refill budget DOCUMENTS the dead-air hole, it doesn't FIX it.** The producer
  renders **serially** (one `await _render` at a time); `maxsize` bounds *memory*, not the refill
  *rate* (1 item / worst-case ≈90s). On a **patter cluster** (station_id→transition→reminder, each
  a few seconds of audio but each a ≤90s render) or **cold start / every midnight**, the depth-2
  buffer drains and the player loops the backstop bumper for ~80s between short IDs — "loud-but-
  wrong," technically not dead air so R11's letter holds, but an audibly broken station. A startup
  WARNING is a confession, not a fix. **Resolution (pick one, converges with RPi "stagger patter"):**
  (a) a **hard config-load invariant** `Σ(patter chain timeouts) < shortest schedulable patter item`
  (fail-fast like R10), and/or (b) **pre-render the whole patter run at block entry** so a real
  multi-minute track masks the serial renders (the design's "depth hides latency" only ever worked
  because a long track masked the next render — back-to-back patter has nothing to hide behind).
  The P4-6 success checkbox tests memory-boundedness, the WRONG property — it must test audible
  liveness.
- **C2 (DA) + M1 (Field Op) — render-poison infinite crash-loop, globalized by escalation.**
  `load_with_recovery` only catches *parse* corruption (`StateCorruptionError`); a structurally-valid
  schedule with a *render-poisoning* item (a file that crashes normalize/decode/sink) passes recovery,
  so restart-to-known-good replays the SAME item at the SAME offset → deterministic loop. The Q8
  ceiling "escalates to process exit" → systemd restarts the process → reloads the same schedule →
  same crash, now taking down **all N stations** per cycle, and the P4-8 unit OMITS
  `StartLimitIntervalSec`/`StartLimitBurst` so systemd loops forever too. **Resolution:** the
  supervisor must **advance past the poisoning item** after K identical-offset crashes (skip + backstop
  that slot, log loudly), NOT replay it; the systemd unit must set `StartLimitIntervalSec`/
  `StartLimitBurst` → terminal `failed` state + a loud final log line.
- **C-RPi-1 — `sounddevice` needs system `libportaudio2` (apt); NO Linux wheel bundles PortAudio.**
  `pip install sounddevice` succeeds but `import` fails at runtime without the system `.so` — passes
  CI, fails on the Pi at first sink use. **Resolution:** P4-1 / `docs/ops/` document `apt install
  libportaudio2` as a hard runtime prereq (venv pip pkg + system .so); the `sounddevice` import must
  be lazy (inside the stream-factory / to_thread body), not module-scope.
- **C-RPi-2 / C-FieldOp-1 — `WatchdogSec` without an `sd_notify(WATCHDOG=1)` heartbeat bricks the box
  in a restart loop** (systemd kills a healthy daemon every interval). **Resolution:** EITHER drop
  `WatchdogSec` (v1: `Type=simple` + `Restart=on-failure`) OR wire a real coordinator heartbeat task
  (`Type=notify` + `sd_notify`). Do not ship the directive without the ping.
- **C-RPi-3 — `After=sound.target` is unreliable for USB-dongle readiness** (async udev enumeration).
  **Resolution:** `After=network-online.target` (+ `Wants=` — the LAN LLM/TTS need the network) +
  **app-level device-resolution retry/tolerance at boot** (degrade to backstop if a device isn't up
  yet, don't crash); add `After=time-sync.target` (Field Op — the boot-clock weekday gotcha).

## HIGH (fold into Rev 2)

- **H-DA-1 — midnight regen failure is uncaught and globally fatal at 00:00.** A bad tomorrow-grid
  raises in the midnight task → cancels the coordinator TaskGroup → kills all N stations. **Per-station
  regen must be isolated + non-fatal** (log, keep today's loaded schedule, never escape into the
  TaskGroup). Also specify + test the **in-flight-item-straddles-midnight** control flow (a 23:30→00:30
  item) — it's a per-midnight cold-start dead-air trigger (C1 again).
- **H-DA-2 — seek-into-first-item: no guard for `offset_frames > decoded.frames`** (VBR/metadata-lying/
  truncated files → empty buffer → first-item-on-resume backstop). Clamp/validate against the *decoded*
  buffer's actual frame count, define skip-to-next behavior, trim by the buffer's OWN rate (post the
  Q7 actual-rate check). (Trim-in-`play_day` over churning `run_once` is still the right call — Senior/
  Old Man/QA/DA all agree — but the mechanic is "decode+slice the first segment in `play_day`, then
  `run_once` on the remainder," not literal "trim," per Senior.)
- **H-RPi-1 — udev rules must key on PHYSICAL USB PORT PATH, not serial** (CM10x dongles share/empty
  serials → wrong station on wrong transmitter, FCC-relevant). `docs/ops/udev-audio.md` must mandate
  port-path keying + show the `udevadm info -a` discovery walk; the resolver must bridge PortAudio
  device-string ↔ ALSA `hw:CARD=` and TEST both namespaces.
- **H-RPi-2 — the refill/`maxsize` budget is also a RAM budget.** Whole-track float32 buffers ≈92MB ×
  depth × N stations ≈ ~740MB on a 4GB Pi. The coordinator's budget computation must cross-check a
  **bytes ceiling** (Σ maxsize × worst-track-bytes ≤ fraction of RAM) + startup WARNING, not just time.
- **H-RPi-3 — stagger/jitter patter generation** (synchronized top-of-hour station-IDs = 4-core
  thundering herd). An explicit requirement, not just "budget the worst case." (Converges with C1.)
- **H-FieldOp-1 — operator log vocabulary.** Specify a named, `station_name`-tagged event set
  (started, ON AIR @ track, crashed+cause, restart N/ceiling, backoff Xs, escalating, midnight regen
  per-station start/done, backstop fired) and make restart-visibility + per-station-regen-visibility
  **asserted gates** (caplog), not just "logging configured."
- **H-FieldOp-2/3 — first-boot runbook + udev verify.** Ship `docs/ops/first-boot.md` tying
  config.example + root-owned `secrets.env` (0600) + udev install + per-dongle PortId verify +
  `systemctl enable --now` + "is it broadcasting?" into ONE ordered checklist; include the udev
  discovery/verify commands.
- **H-FieldOp-4 — define `--regenerate` semantics** (scope per-station/all; oneshot vs live; interaction
  with a running daemon).
- **H-Senior-1 — `recent_tracks` wiring is real churn, not zero-churn.** `build_dj_context`/`Producer`/
  `run_once` have NO `recent_tracks` param; threading the deque requires adding it (back-compat default
  `()`). Correct the Q4/CF1 "frozen/zero-churn" framing.
- **H-Senior-2 — `item_kind` removal is shotgun surgery across 8 sites** (protocols, failover lambda,
  3 backends, 2 fakes, producer caller) — resequence as its OWN named increment, not bundled under
  "WARNING de-dup."

## MEDIUM / rulings to ratify

- **Q5 budget** = a single PURE tested function; **name the default timeout numbers as constants**
  (Old Man). **Q6 status** = minimal in-memory `StationStatus` (the attributes supervision already
  needs: name/state/current_item/restart_count/last_error) + a periodic all-stations summary log line;
  **NO new DTO module, NO HTTP** (Field Op wants the struct, Old Man wants zero speculative surface —
  reconciled: tiny struct, no API). **Q8** = fixed-window restart count + ceiling → process exit;
  **reject per-cause backoff branching** (Old Man) + supervisor advances past poison (C2). **Q2** =
  `asyncio.Event` owned by the coordinator, **write-next-day-file THEN set event** (ordering contract,
  tested). **Q9** = persistent `sd.OutputStream` + explicit `blocksize`/`latency`; **xrun = logged
  glitch, recovered in-stream, NOT a crash/supervisor event** (RPi). Dedicate a **separate to_thread
  executor for the sink writers** so blocking playback writes don't starve CPU normalize/decode (RPi/
  DA M1); the Station must own stream lifecycle (close on exit/restart, async-CM `finally`) to avoid a
  per-crash stream/thread leak. **Q1/Q3/Q4/Q7/Q10** adopted as recommended.
- QA gate tightenings: P4-4/P4-7 assert the in-flight segment **aired in full** (FakeAudioSink recorded
  complete buffer/duration) + next-day file written + re-slice only at boundary — not "not cancelled";
  P4-4 assert the **gap-silence format/sample-count** matches the station format; P4-1/P4-2 add a
  **no-module-scope-import** R21 guard test; supervisor escalation uses an **injected exit seam**;
  pin `recent_tracks` semantics (look-ahead-ordered, not air-accurate under backstop) in a test.
  P4-9 deep-dive audits the uncovered-lines report (pragma+thin-seam), not just the %.
- Wording: "per-station audio format" → "the single fixed global station format (`DEFAULT_SAMPLE_RATE`,
  mono)" — there is no `sample_rate`/`channels` config field (Senior).
- `docs/ops/`: active cooling + SSD boot + official PSU + powered USB hub are mandatory for 24/7
  4-station load (RPi).

## Next

Revise the plan to Rev 2 folding all of the above (the planner is one-shot — the manager authors Rev 2
or spawns a fresh planner with this brief), then re-dispatch the full-seven panel for the re-vote.
Phase 3 remains COMPLETE + deep-dive-validated; Phase 4 is at the plan-revision stage.
