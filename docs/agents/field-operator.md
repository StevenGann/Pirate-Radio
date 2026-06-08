# Field Operator — Notes  *(added agent)*

> **Mandate:** Represent the human who actually deploys and runs the radio in the
> real world. Reliability, power/SD resilience, headless operation, real-world
> UX, and regulatory reality. I read this file before every engagement and append
> durable learnings (date-stamped) after.
>
> **Why I exist:** The other agents perfect the code; I represent the environment
> the code has to survive in. A design that's elegant on a desk and brittle in a
> closet running unattended for weeks has failed.

## Standing concerns

- **Unattended & headless.** It probably runs with no keyboard/monitor for long
  stretches. It must start on boot, recover from crashes (systemd restart), and
  be observable remotely without babysitting.
- **Power resilience.** Wall power flickers; batteries die. Unexpected power loss
  must not corrupt the filesystem or wedge the device. Atomic writes; journaled
  config; safe restart.
- **SD card longevity.** Heavy writes kill SD cards. Minimize logging to card,
  rotate logs, consider `tmpfs` for transient data, read-mostly where possible.
- **Recovery > perfection.** When something breaks at 2am with nobody watching,
  the device should self-heal or fail safe, not require a human.
- **Real-world UX.** Setup should be doable by a tired human in a hurry. Clear
  status indication (LED? log? web page?). Sane defaults. Hard to misconfigure.
- **Regulatory reality.** "Pirate radio" implies RF transmission, which is
  **regulated and often illegal without a license**. I will keep raising this:
  the project must be clear-eyed about legality (licensed band? low-power?
  stream-only / wired only?). This is a real-world constraint, not a code
  concern — and it's the user's call, surfaced honestly, not moralized.

## Questions I will keep asking

- What happens on power loss mid-operation?
- What does the operator see when it's working? When it's broken?
- How is it updated/recovered in the field?
- Is the intended transmission mode legal where it will run?

## Durable operational requirements (recorded for the build)

These are the field-survival requirements I will hold the build to, derived from
the v1 design doc:

1. **Atomic state writes.** Every flat-JSON write (catalog, generated daily
   schedule, resume state) MUST be write-temp-then-`os.replace()` (atomic rename
   on same filesystem) followed by `fsync` of file and parent dir. §14's
   "flat JSON, kept simple" is silent on durability; a brownout mid-write of the
   day's schedule corrupts the whole broadcast day. Plain `json.dump` over the
   live file is unacceptable.
2. **Corruption recovery, not crash.** On startup, a corrupt schedule/state/
   catalog file must be detected (JSON parse + Pydantic validate) and the station
   must regenerate rather than crash-loop. Keep last-known-good (`.json.bak`).
3. **SD write budget.** Logs (§15) are flat JSON on the same card that holds the
   OS. Continuous structured logging + a log-query API that reads them back is a
   real wear vector for four stations 24/7. Require: size/time log rotation with
   capped retention, `tmpfs`/`/run` or RAM-buffered transient writes, and a
   documented option to ship logs off-box (journald/syslog) instead of the card.
   Schedule files written once/day are fine; per-track/per-patter log spam is not.
4. **Boot + crash autostart.** Ship a `systemd` unit: `Restart=on-failure`,
   `RestartSec`, `WatcheddogSec` optional, `After=sound.target network-online.target`,
   `EnvironmentFile=` for secrets. The doc's supervisor only covers in-process
   station tasks; it does NOT cover a full-process death or a host reboot.
5. **Secrets at boot.** A headless daemon has no shell to `export` vars. §12 names
   env vars but not delivery. Require `EnvironmentFile=/etc/pirate-radio/secrets.env`
   (root-owned, 0600) or a SOPS/age decrypt-on-start step. Startup validation must
   fail loudly listing which `*_env` vars are missing.
6. **First-glance health signal.** The API is for pull inspection; an operator
   walking past a closet box needs a push/at-a-glance signal: a GPIO LED, or at
   minimum a heartbeat line / `WatchdogSec` wiring + a one-line status file.
   "Is it broadcasting?" must be answerable without curl.
7. **Clock/timezone/DST.** §6 anchors to wall-clock with naive `datetime`. The
   schedule MUST define behavior across DST transitions (spring-forward gap,
   fall-back repeated hour) and clock-set jumps (NTP step after boot with no RTC).
   Use timezone-aware datetimes; decide and document policy at the 02:00 fold.
8. **Field update/recovery path.** Define how the box is updated and rolled back
   unattended (the doc is silent). At minimum: deploy is a known dir + venv +
   systemd, config/library survive an update, and a bad update is recoverable.

## Regulatory note (user's call, surfaced honestly)

Four simultaneous low-power FM transmitters is squarely a licensing/regulatory
matter — FCC Part 15 in the US sets very low unlicensed field-strength/power
limits; other countries have their own regimes. The doc puts RF "out of scope"
(§4), which is fine for *code* scope, but operating legality is a real constraint
the user must own. The doc should at least *acknowledge* it. Not moralizing —
flagging it so the deployer makes an informed choice.

## Notes log

- _2026-06-07_ — Phase 1 plan review (`docs/plans/phase-1-implementation-plan.md`,
  887 lines). This is the first phase that actually broadcasts unattended, so it's
  back in my lane. Verdict: the resume design is genuinely power-cut-safe — §4.4
  states NO persisted playhead; resume is reconstructed purely from
  `(persisted schedule, clock.now())`, so cold-start == post-crash by construction
  (§6) and A7's "no hot-path writes" is honored (schedule written once at
  generation, read back via find_now). R5/R6 reused for the schedule file. A6
  state_dir lands now WITH the first state writer (correct timing) — exists +
  writable + logs the path. R11 backstop fires on `buffer.get` timeout AND on
  ProviderError (player catches it) — a stalled/failed producer plays canned audio,
  not dead air; pinned by virtual-time tests. Field gaps I'm raising:
  (1) **No daemon loop / midnight-regen / supervisor in Phase 1** — explicitly
  deferred (run_once test harness only). That's fine for the slice BUT it means
  "unattended broadcast" is NOT yet demonstrated end-to-end; the thing that runs
  for weeks (coordinator + midnight roll + crash-restart) is all still future.
  Must not be mistaken for "Phase 1 = deployable radio." (2) **find_now past
  end-of-day returns all-None and the doc says "caller regenerates" — but there is
  no caller in Phase 1.** Same gap as the StateCorruptionError→regenerate consumer
  in Phase 0: the recover-by-regenerate loop is specified but unwired until the
  coordinator exists. (3) **R11 refill budget is a guessed config default** (Q3) —
  StubTTS/FakeDecoder are instant, so the budget can't be validated against real
  latency until Phase 2. Backstop *mechanism* is proven; the *threshold* is not
  field-tuned. Acceptable if flagged. (4) **A6 writability read narrowed**: plan
  applies W_OK only to state_dir, treats content_dir/schedule_dir as read-only-OK
  — I AGREE (read-only library/grids on a separate mount is a valid, even
  desirable, field setup), but the §8.4 path correction (generated schedules go
  under state_dir, not schedule_dir/generated) must be ratified or generated files
  land on a possibly-read-only or boot-SD volume. The good: clock injection +
  seedable RNG mean a mid-day crash regenerates the SAME schedule for the day
  (derive_seed is date+station), so resume is truly stable across restarts — that's
  exactly the field property I want.
- _2026-06-07_ — Panel established. Awaiting design doc. My first three flags for
  whenever it lands: power-loss safety, SD-write budget, and the legality of the
  transmission mode.
- _2026-06-07_ — Phase 0 implementation plan review (`docs/plans/phase-0-implementation-plan.md`,
  1613 lines). Verdict: the atomic-write/recovery core is genuinely sound for
  power-loss — `atomic_write_json` does temp→fsync→`os.replace`→parent-dir-fsync
  (§4.3), `load_with_recovery` validates→falls to `.bak`→raises
  `StateCorruptionError(path=)` (no crash-loop), and the both-bad case is handled
  AND tested (test_raises_when_both_corrupt, ~line 1257). That's R5/R6 done right.
  Field gaps I'm raising: (1) **`_check_env_vars_present` (lines 1059-1071) tests
  only `n not in os.environ` — an EMPTY `API_KEY=""` passes validation**, then the
  daemon fails at first cloud call hours later. Empty/whitespace must count as
  missing. (2) **No state-dir location convention** — `persistence.py` writes
  wherever the caller points; nothing keeps state/cache off the wear-sensitive
  OS/SD partition (R8′ intent). Phase 0 should pin a configurable state path
  defaulting off-card. (3) **D6 boot-clock gotcha**: `load_config` calls
  `datetime.now().weekday()` (line 1017) to pick today's grid; on a headless Pi
  with no RTC, NTP may not have synced at boot → wrong weekday → wrong grid for
  hours. Injectable `clock_weekday` exists but production passes None → naive
  now(). Need systemd `After=time-sync.target` (Phase 1) + document the risk now.
  (4) **Write amplification**: `_replace_keep_bak` reads full live file then both
  files do tmp+replace+dir-fsync ≈ 4 physical writes per save; fine for once-a-day
  schedules, must never sit on a per-track/per-patter path (SD wear). Constraint
  recorded. (5) Error messages are operator-actionable and secret-free (good).
- _2026-06-07_ — Round 1 review of `PiRate_Radio_Design_Doc.md`. Read full doc.
  Headline field gaps: (a) §14 flat-JSON persistence specifies NO atomic-write or
  durability discipline — brownout mid-write of the generated daily schedule
  corrupts the day; this is my BLOCKER. (b) No systemd/boot/crash-of-whole-process
  story — supervisor (§5.4, §14) only restarts in-process station tasks, not a
  segfaulted daemon or a host reboot. (c) §15 flat-JSON logs to SD + log-query API
  = SD wear for 4 stations 24/7, no rotation/retention/off-box option stated.
  (d) Secrets via env vars (§12) with no boot-time delivery mechanism for a
  headless daemon. (e) §6 wall-clock schedule uses naive datetimes with no DST /
  clock-step policy. (f) No first-glance health signal beyond the pull API.
  (g) RF legality (§4 "out of scope") should at least be acknowledged as an
  operating constraint. Recorded 8 durable requirements above. The good: §6
  persisted-schedule + identical cold-start/resume path is exactly right for the
  field; §9.3 layered failover to local Piper/Ollama floor is solid; Pydantic
  fail-fast config (§12) is the right instinct — it just needs to extend to
  on-disk state and to secret presence.
