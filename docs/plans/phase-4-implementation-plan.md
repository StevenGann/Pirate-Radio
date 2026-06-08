# Phase 4 Implementation Plan — Multi-Station (Coordinator · Supervisor · systemd · Real Audio Sink · Midnight Regeneration) — **Rev 2 (re-vote)**

> **Status:** Rev 2 — revised after the Rev-1 vote (5 AYE / 2 NAY → REVISE; NAY: Devil's Advocate, Field Operator). Fact Checker verified every referenced symbol against the tree (no corrections). This revision folds **every** adopt-blocking CRITICAL, HIGH, and ratified open-question ruling from `docs/decisions/0033-phase4-plan-rev1-vote.md`. Strict spec-driven TDD applies (tests authored from spec → panel-reviewed BEFORE implementation → GREEN → ruff/mypy `--strict`/pytest gate → one decision record per increment). Charter: ≤1 NAY adopts; ≥2 NAY → revise + re-vote.
>
> **Rev-2 changelog (every item is a `0033` must-fix or ratified ruling):**
> 1. **(CRITICAL C1, DA) The serial-render / short-patter audible backstop-loop is now FIXED, not documented.** The fix is architectural: the coordinator **computes the look-ahead depth from the grid's worst consecutive-patter run** so the producer pre-renders a patter cluster *during the preceding multi-minute track* (which masks the serial renders); patter generation is **staggered/jittered across stations** (no 4-core thundering herd); and the depth is **bounded by a RAM ceiling** (C1 + H-RPi-2 + H-RPi-3 converged). The irreducible residual (cold start, or a block that *opens* with back-to-back patter and no masking track) is honestly bounded to **one render → R11 backstop**, and a startup WARNING fires for it — but the sustained-loop case is eliminated by buffer depth. See §A.
> 2. **(CRITICAL C2, DA + Field-Op) Render-poison crash-loop closed.** `load_with_recovery` only catches *parse* corruption; a structurally-valid schedule with a render-poisoning item replayed identically = infinite loop, globalized by escalation. Fix: the supervisor **advances past a poison item** after K identical-offset crashes (skip + backstop that slot, log loudly) rather than replaying; the systemd unit sets `StartLimitIntervalSec`/`StartLimitBurst` → terminal `failed` + a loud final line. See §C, §H.
> 3. **(CRITICAL, RPi) `sounddevice` needs system `libportaudio2` (apt) — no Linux wheel bundles PortAudio.** Documented as a hard runtime prereq; the `sounddevice` import is lazy (R20/R21). See §G, P4-1.
> 4. **(CRITICAL, RPi + Field-Op) `WatchdogSec` footgun resolved:** v1 ships `Type=simple` + `Restart=on-failure` (NO `WatchdogSec` without a heartbeat); a real `sd_notify` heartbeat is a documented optional upgrade. See §H.
> 5. **(CRITICAL, RPi) systemd `After=` fixed:** `network-online.target` (+ `Wants=`) + `time-sync.target`, NOT `sound.target`; the daemon **tolerates a not-yet-present device / not-yet-up LAN at boot** (retry/degrade-to-backstop, don't crash). See §F, §H.
> 6. **(HIGH, DA) Midnight regen-failure is per-station isolated + non-fatal** (never escapes the coordinator TaskGroup); the **in-flight-item-straddles-midnight** flow is specified + tested. See §E.
> 7. **(HIGH, DA) Seek-into-first-item guards `offset_frames > decoded.frames`** (VBR/truncated/metadata-lying files) — clamp + skip-to-next, trim by the buffer's OWN rate post actual-rate check. See §B.
> 8. **(HIGH, RPi) udev rules key on the PHYSICAL USB PORT PATH, not serial** (CM10x dongles share/empty serials → wrong station on wrong transmitter); the resolver bridges PortAudio device-string ↔ ALSA `hw:CARD=` and tests both namespaces. See §F.
> 9. **(HIGH, Field-Op) Operability layer:** a minimal in-memory `StationStatus` + a periodic all-stations summary log line (Q6); a named, `station_name`-tagged operator **log vocabulary** with restart/regen visibility as asserted gates; a `docs/ops/first-boot.md` runbook; defined `--regenerate` semantics. See §D, §H.
> 10. **(HIGH, Senior) Honest churn:** threading `recent_tracks` requires adding the param to `build_dj_context`/`Producer`/`run_once` (back-compat default `()`) — the "frozen/zero-churn" framing is corrected; `item_kind` removal is its **own** named increment (8 call sites). See §B, P4-5b.
> 11. **Ratified rulings:** Q1 decode+slice in `daily.play_day` (not churn `run_once`); Q2 `asyncio.Event`, **write-file-then-set** ordering; Q3 record in `play_day` (look-ahead-ordered, pinned in a test); Q4 leave `build_dj_context` in the producer (coordinator owns inputs); Q5 worst-case as a single PURE tested fn with **named constants**; Q6 minimal `StationStatus`, **no DTO module, no HTTP**; Q7 construction-from-one-format **+** first-buffer assert; Q8 fixed-window ceiling → process exit, **no per-cause branching**; Q9 persistent `sd.OutputStream` + explicit `blocksize`/`latency` + xrun=logged-glitch + **dedicated sink executor** + stream lifecycle close; Q10 `python -m pirate_radio`.
> 12. **Wording:** "per-station audio format" → "the single fixed global station format (`DEFAULT_SAMPLE_RATE`, mono)" — there is no `sample_rate`/`channels` config field.

> **Governing authority:** `PiRate_Radio_Design_Doc.md` §5.1, §5.4, §8.6, §20, §21 (R6/R7/R8′/R9/R10/R11/R12/R13/R18/R19/R20/R21/R23, D4/D6, A6/A7) + `docs/decisions/0001`–`0033`. Where this plan and §21 disagree, §21 governs.

## Overview

Phase 4 turns the Phase 0–3 library into a **deployable radio**. It is thin orchestration over proven seams: a daily-slice driver, a per-station loop, a coordinator owning shared services + DJ inputs + the midnight task, a two-tier supervisor (in-process + systemd), a real `SoundDeviceSink`, a real `UdevAudioDeviceResolver`, and a logging entrypoint. Two constraints stay central: **never dead air (R11)** and **virtual-time testability (R18/R21)**.

## Architecture (modules; MANY SMALL FILES <400 lines; strictly downward deps)

```
__main__.py            NEW  entrypoint: logging -> load_config -> Coordinator.run() (python -m pirate_radio)
logging_setup.py       NEW  structured logging (R8' stdout/journald) + the operator log vocabulary
coordinator.py         NEW  shared services; DjContext inputs; look-ahead-depth + RAM + stagger budget;
                            midnight task; supervises N stations; owns the StationStatus registry
supervisor.py          NEW  R7 tier-2: restart-to-known-good, sibling isolation, backoff (Sleeper),
                            crash-loop ceiling -> escalate; advance-past-poison-item
station.py             NEW  per-station loop: load-or-generate, find_now, drive the daily slice;
                            updates its StationStatus; the supervised unit
pipeline/daily.py      NEW  AnchoredSchedule + find_now -> remaining items + seek + leading gap;
                            play_day (gap silence -> seek-trim first segment -> run_once)
midnight.py            NEW  next_midnight (injected Clock, DST) + per-station isolated regenerate
audio/sink.py          NEW  SoundDeviceSink (AudioSink); persistent sd.OutputStream; only the write hardware
audio_devices.py       EDIT real UdevAudioDeviceResolver (port-path keyed; PortAudio<->ALSA bridge)
status.py              NEW  StationStatus (frozen, in-memory; NO DTO/HTTP — Q6)
systemd/pirate-radio.service   NEW  R7 tier-1 (Type=simple, Restart=on-failure, StartLimit*, After=)
docs/ops/first-boot.md NEW  the ordered install runbook (config + secrets + udev + systemd + verify)
docs/ops/udev-audio.md NEW  port-path udev recipe + udevadm discovery/verify walk
```

Reused **unchanged**: `pipeline/run_once`+`Producer`/`Player`/`LookAheadBuffer`/`timing.py`, `schedule/resume.py`, `schedule/generator.py`, `config.py`, `catalog/`, `persistence.py`, `clock.py`. **Additively changed** (back-compat defaults, honest churn): `pipeline/producer.py`+`run_once` gain a `recent_tracks` param (default `()`); `dj/protocols.py`+backends+fakes drop the redundant `item_kind` param (its own increment).

## §A — The look-ahead budget (C1 fix: depth + RAM + stagger) — `coordinator.py`

The Rev-1 "refill budget" only WARNed; this is the real fix. Three coupled quantities the coordinator computes once from the resolved config + grid:

- **Look-ahead depth (the C1 fix).** The producer renders **serially**, so the only thing that lets it stay ahead of a short-patter cluster is a buffer deep enough to pre-render the cluster *while the preceding multi-minute track plays*. Compute `depth = max_consecutive_non_track_items(grid) + 1` (a block boundary may emit e.g. `block_transition`+`station_id` back-to-back). Pass it as `run_once(..., maxsize=depth)`. During the long track before a cluster, the serial producer renders the whole cluster ahead — the track masks the ~90s renders. **`_worst_consecutive_patter(grid) -> int`** is a PURE, unit-tested function.
- **RAM ceiling (H-RPi-2).** Whole-track float32 buffers ≈ `DEFAULT_SAMPLE_RATE × 4 bytes × seconds` (≈11.5 MB/min mono). The total look-ahead footprint is `Σ_stations(depth × worst_track_bytes)`. The coordinator clamps `depth` so this stays ≤ a configured fraction of `psutil`-free / a fixed budget (e.g. ≤ 40% RAM), and emits a **startup WARNING** naming the clamp. `_ram_bounded_depth(depth, worst_track_seconds, n_stations, ram_budget_bytes) -> int` — PURE, tested.
- **Stagger (H-RPi-3).** To avoid N stations firing Piper/cloud renders on the same tick (4-core thundering herd, synchronized top-of-hour IDs), the coordinator assigns each station a **fixed render-stagger offset** (e.g. `i * stagger_step`), applied as an initial delay via the injected `Sleeper` before the station's first render. Deterministic per index (R19-style, no `Math.random`), virtual-time-testable.
- **Worst-case render (Q5, named constants).** `worst_case_patter_render(llm, tts_chain) = sum(llm timeouts) + sum(tts timeouts)`; `worst_case_track_render = decode_timeout`. A single PURE tested function; the default timeout numbers (`20.0` LLM, `30.0` TTS, `120.0` decode) are **named constants** with a derivation comment. The coordinator logs a **startup WARNING** when `worst_case_patter_render > shortest_schedulable_patter_item` AND that item can open a block with no masking track (the irreducible residual → R11 backstop for one render).

**Honest residual (stated, not hidden):** cold start (no prior audio) and a block that *opens* with a patter cluster degrade to the R11 backstop for the duration of one render. This is bounded (one render, not a sustained loop) and audible-as-bumper, not silence. The sustained-cluster-loop Rev-1 hole is eliminated by depth.

## §B — `pipeline/daily.py` (slice + seek + gap) + `recent_tracks`

- `slice_from_now(anchored, now) -> tuple[list[ScheduleItem], float, float]` — PURE; from `AnchoredSchedule.find_now(now)`: remaining items, `NowPlaying.offset_seconds`, `NowPlaying.gap_seconds`.
- `play_day(...)` — if in a gap, play `gap_seconds` of silence (a buffer at the **station format** — asserted, H-QA-2) via the sink first (R11); then **decode+slice the first item** by `offset_seconds` and play the trimmed segment directly, then `run_once(items=remaining[1:], ...)` (Q1 — keeps `run_once` frozen).
  - **Seek guard (H-DA-2):** trim by the *decoded buffer's own rate*; if `offset_frames >= decoded.frames` (VBR/truncated/metadata-lying), **skip to the next item** (do not emit an empty buffer → backstop); `offset` taken straight from `NowPlaying` (never re-derived, so non-negative by construction).
- **`recent_tracks` (Q3, honest churn):** `play_day` appends each aired `TrackItem`'s `TrackMeta` to the coordinator-owned per-station `deque(maxlen=N)`; this is **look-ahead-ordered, NOT air-accurate under a backstop substitution** — pinned in a test (H-QA-MEDIUM-3). Threading it to the DJ requires adding `recent_tracks` to `build_dj_context`/`Producer`/`run_once` (back-compat default `()`).
- 100% pure/virtual-time (FixedClock, FakeAudioSink, VirtualSleeper, StubTTS/FakeDecoder, synthetic DailySchedule).

## §C — `supervisor.py` (R7 tier-2; advance-past-poison)

- `Supervisor(sleeper, *, on_escalate)`; `run(units)`. `Supervisable` = `async run()` + `name`.
- Per unit in its own child task; on a non-`CancelledError` exception: **scrub** the message (no secrets), log a `station_name`-tagged WARNING with the cause + restart count, backoff via the injected `Sleeper` (fixed or simple-multiplier — **no per-cause branching**, Q8), restart-to-known-good (re-enter `Station.run()` → reload/re-anchor from disk, R6/R12). **Sibling isolation** (§5.4): one crash never cancels another.
- **Advance-past-poison (C2):** the Station tracks the offset/item of its last crash; on **K identical-offset crashes** it skips that item (logs CRITICAL, airs the backstop for that slot) and continues — a render-poison item can never infinite-loop.
- **Crash-loop ceiling → escalate (Q8):** fixed-window restart count; on breach, log CRITICAL + call the injected `on_escalate` (default → process exit so the systemd tier restarts) — **tested via the injected seam, not a real `sys.exit`** (H-QA-MEDIUM-2).
- Cannot catch a native SIGSEGV (R7) — explicitly the systemd tier's job (documented).
- 100% pure with a crash-on-Nth-call fake + `VirtualSleeper`; **R6 corruption→regenerate exercised THROUGH the supervisor restart path** (Old-Man condition), plus the poison-skip path.

## §D — `coordinator.py` (shared services, DJ inputs, budget, status, midnight)

- `Coordinator(config, clock, resolver, sleeper, sink_factory)`; `sink_factory(port_id) -> AudioSink` is the injection seam (tests → `FakeAudioSink`; prod → `SoundDeviceSink`; the coordinator never imports `sounddevice`).
- **Build-once (§5.1):** per station resolve LLM (`resolve_station_llm`), `build_text_generator(llm)` (cache per identical resolved LLM — shared chains), `resolve_persona`, `build_tts_engine(...)`, `CatalogCache`, one pre-normalized backstop. Computes the §A budget (depth/RAM/stagger/worst-case) once.
- **DJ inputs (Q4):** `build_dj_context` stays in the producer; the coordinator supplies real persona/station/tagline/`recent_tracks` so the producer sentinels never fire in production.
- **Actual-rate (Q7, CF5):** decoder + TTS + backstop wired from the **one global format** (`DEFAULT_SAMPLE_RATE`, mono) so they agree by construction; the daily driver asserts the first rendered buffer's `(sample_rate, channels)` (`run_once._assert_station_format` already guards the backstop side).
- **StationStatus registry (Q6):** owns a per-station `StationStatus` (see §status); a coordinator task logs a periodic **all-stations summary** ("N/N ON AIR …") so "is it broadcasting?" is answerable from journald alone — no HTTP.
- `run()`: `asyncio.gather(supervisor.run(stations), midnight.run(stations))` under one `TaskGroup`.
- Imports no hardware; tested with `StaticAudioDeviceResolver` + a fake `sink_factory`.

## §E — `midnight.py` (sleep-to-midnight + per-station isolated regen, DST)

- `next_midnight(now, tz) -> datetime` — PURE, DST-correct via `zoneinfo` (the clock's `tz()`).
- `run(stations)`: loop — sleep the computed seconds (`Sleeper`), then **per station, isolated:** re-read the grid (`resolve_grid_path`+`load_grid`+`validate_grid_against_catalog`), `generate_schedule`, `atomic_write_json`, then **set the station's day-roll `asyncio.Event`** (Q2 — **file written THEN event set**, an ordering contract that is tested). **Per-station try/except (H-DA-1):** a regen failure (bad tomorrow-grid, missing content) is logged CRITICAL and **the station keeps today's loaded schedule** — the exception **never escapes into the coordinator TaskGroup** (a bad tomorrow-grid must not take down today's broadcast at 00:00).
- **In-flight not cut (§8.6):** regen writes only the next-day file + flips the signal; never cancels the running `run_once`. **Straddle-midnight flow (H-DA-1):** an item that starts 23:30 and ends 00:30 is the last of yesterday's slice → `run_once` returns when it finishes → the station then observes the day-roll Event and re-slices onto the new day (the gap until the new day's first item is one render, R11-covered). Specified + tested.
- `next_midnight` unit-tested across DST spring-forward + fall-back (explicit `ZoneInfo`); the loop with `FixedClock`+`VirtualSleeper`; regen-failure isolation + straddle both tested. Zero wall-clock.

## §F — `audio_devices.py` (real `UdevAudioDeviceResolver`) + udev recipe

- `UdevAudioDeviceResolver` implements `AudioDeviceResolver`: configured `audio_device` name → stable `PortId` **keyed on the physical USB port path** (R10/A2), NOT serial (CM10x dongles share/empty serials → wrong transmitter). It **bridges** the PortAudio device string ↔ ALSA `hw:CARD=<id>` ↔ the PortAudio device index. The udev/ALSA enumeration is the only hardware line (`pragma`/`@pytest.mark.hardware`); the name→PortId + namespace-bridge logic is PURE, tested with a fake enumeration **modelling BOTH namespaces** (H-RPi-1).
- `docs/ops/udev-audio.md`: the port-path udev rule + the `udevadm info -a` discovery walk + a "reboot and re-verify" step + the note that moving a dongle to another port reassigns the station.

## §G — `audio/sink.py` (`SoundDeviceSink`, R20) + libportaudio2

- `SoundDeviceSink` implements `AudioSink` (gapless, §10). **Persistent `sd.OutputStream`** opened once per station, `stream.write(buf.samples)` per call (Q9); explicit `blocksize` + `latency` (~80–150 ms headroom) pinned to avoid xruns on cheap dongles under a contended Pi. The blocking write hops via a **dedicated to_thread executor** (one thread per station) so playback writes never starve CPU normalize/decode in the shared default pool (RPi/DA-M1).
- **xrun policy:** a `PaOutputUnderflowed` is **logged as a glitch and the stream continues** — NOT a crash, NOT a supervisor event (R11 does not cover xruns; an xrun is a degraded glitch, not dead air).
- **Stream lifecycle:** the sink is an async context manager; the stream is closed in `finally` on station exit/restart so a crash-loop can't leak streams/threads (DA-M1).
- **R20:** only the literal `stream.write`/stream-open line is `pragma`/hardware; format coercion, the to_thread hop, the lifecycle, and xrun handling are pure, tested with an injected `FakeOutputStream` (the stream factory is a constructor dep, default = real `sd.OutputStream`). `sounddevice` import is **lazy** (inside the factory/to_thread body) — a `no-module-scope-import` test guards R21 (H-QA-MEDIUM-1). A `@pytest.mark.hardware` smoke plays short silence.
- **`libportaudio2` (CRITICAL, RPi):** `pyproject` adds `sounddevice`; `docs/ops/first-boot.md` + the P4-1 record document `sudo apt install libportaudio2` as a hard runtime prereq (the pure-Python wheel does NOT bundle PortAudio; pip-installs clean but imports fail without the system `.so`).

## §status — `status.py` (`StationStatus`, Q6 — minimal, no HTTP)

A frozen in-memory `StationStatus` per station: `name`, `state` (`starting|on_air|gap|regenerating|crashed|restarting`), `current_item`, `last_transition_at`, `restart_count`, `last_error`. Updated at the same points the operator log events fire. The coordinator holds the registry; a periodic task logs the all-stations summary. **No new DTO module beyond this frozen struct, no read-model, no HTTP** (Old-Man "zero speculative surface" + Field-Op "answerable from journald" reconciled). Phase 6 reads it; Phase 4 ships only the struct + the summary log.

## §H — entrypoint, logging vocabulary, systemd, ops docs (Field-Op)

- `logging_setup.configure_logging(level)` (R8′ stdout/journald). **Operator log vocabulary** — a named, `station_name`-tagged event set, each an asserted gate (caplog): station `starting` / `on_air @ <track>` / `crashed (<cause>)` / `restart N/<ceiling>` / `backoff <Xs>` / `escalating` / `midnight regen <station> started|done items=N|FAILED <cause>` / `backstop fired`.
- `__main__.py` (`python -m pirate_radio`, Q10): argparse (config path, `--regenerate`, `--log-level`), `configure_logging` **first**, then `load_config(..., resolver=UdevAudioDeviceResolver(), clock=SystemClock(), preflight=True)`, construct `Coordinator` with the real `sink_factory`+`SystemClock`+`RealSleeper`, `asyncio.run(coordinator.run())`. Tested via a `main(argv, *, deps)` seam with fakes (logging before config load); only the real-resolver/`asyncio.run` line is hardware-adjacent. **`--regenerate` semantics (H-FieldOp-4):** regenerate today's schedule for all stations (or `--regenerate=<station>`), write, and **exit** (oneshot tool, not live) — the running daemon is unaffected; a live daemon picks up a manual regen only on its next day-roll or a restart (documented).
- `systemd/pirate-radio.service`: `Type=simple`, `Restart=on-failure`, `RestartSec=2`, **`StartLimitIntervalSec`/`StartLimitBurst`** (terminal `failed` instead of thrash, C2), `After=network-online.target time-sync.target` + `Wants=network-online.target`, `EnvironmentFile=` (root-owned 0600 secrets). **NO `WatchdogSec`** in v1 (a real `sd_notify` heartbeat is a documented optional upgrade). The daemon **tolerates a not-yet-present device / LAN at boot** (resolution retry + degrade-to-backstop, don't crash).
- `docs/ops/first-boot.md`: the ordered runbook — deploy venv, `apt install libportaudio2`, write `/etc/pirate-radio/secrets.env` (0600), install+verify udev rules per dongle, lay down `config.json` (from `config.example.json`), `systemctl enable --now`, confirm "N/N ON AIR" in journald. Plus the 24/7 appliance requirements (active cooling, SSD boot, official PSU, powered USB hub).

## Increment Breakdown (dependency-ordered; strict spec-driven TDD)

- **P4-1 — `audio/sink.py` `SoundDeviceSink`** (+ `sounddevice` dep, `libportaudio2` doc). Gate: format coercion + to_thread offload (dedicated executor) + persistent-stream lifecycle (close in `finally`) + xrun-is-a-glitch, all with injected `FakeOutputStream`; **only `stream.write` hardware**; **no module-scope `sounddevice` import** test (R21); CI green `-m "not hardware"`.
- **P4-2 — `UdevAudioDeviceResolver`** + `docs/ops/udev-audio.md`. Gate: name→PortId **port-path** keying + PortAudio↔ALSA bridge unit-tested with a fake modelling both namespaces; only enumeration hardware; `StaticAudioDeviceResolver` still the CI resolver.
- **P4-3 — `supervisor.py`** (R7 tier-2) + secret-scrub + `status.py`. Gate: crash-on-Nth restart count, backoff via `VirtualSleeper`, sibling isolation, **advance-past-poison after K identical-offset crashes**, crash-loop ceiling → **injected `on_escalate`** (not real exit); R6 corruption→regenerate **through** the restart path; scrubbed logs; `StationStatus` transitions asserted.
- **P4-4 — `pipeline/daily.py`** (slice + seek-guard + gap) + `recent_tracks` param threading. Gate: `slice_from_now` across now-inside-item (R12 seek), now-in-gap (R11 silence + next), now-before-first, now-past-end; **seek `offset_frames >= decoded.frames` → skip-to-next** (not empty→backstop); **gap silence asserted at the station format** (H-QA-2); `recent_tracks` look-ahead-ordered semantics pinned; virtual time only.
- **P4-5 — `station.py`** (load-or-generate + resume + day loop + StationStatus updates). Gate: first-start generates+persists; load; corruption→regenerate not crash-loop (R6); mid-day resume re-anchors (R12); day-roll re-slices on the Event; status transitions; full fakes.
- **P4-5b — `item_kind` Protocol removal** (its own increment, 8 sites). Gate: `patter(context)` green across `protocols.py` + the `failover.py` lambda + 3 backends + 2 fakes + the producer caller; mypy `--strict` clean.
- **P4-6 — `coordinator.py`** (shared services, DJ inputs, §A budget, status registry, actual-rate). Gate: shared-LLM reuse asserted (§5.1); real persona/station/recent_tracks supplied; **look-ahead depth = worst consecutive patter +1**, RAM-clamped, **stagger offsets** assigned; worst-case render a PURE fn with **named constants**; startup WARNING (caplog) for the irreducible residual + the RAM clamp; first-segment actual-rate assert; injected `sink_factory`, no hardware.
- **P4-7 — `midnight.py`** (sleep + per-station isolated regen, DST, straddle). Gate: `next_midnight` DST spring/fall; `run` sleeps computed seconds (`VirtualSleeper`), regenerates+persists+signals **file-then-event**; **regen failure isolated + non-fatal** (other stations + today's schedule survive); **straddle-midnight** item aired uncut then re-sliced (FakeAudioSink recorded the FULL in-flight buffer — positive assertion, H-QA-1); zero wall-clock.
- **P4-8 — `systemd/pirate-radio.service` + `__main__.py` + `logging_setup.py` + `docs/ops/first-boot.md`** (R7 tier-1, CF6). Gate: unit has `Type=simple`/`Restart=on-failure`/`RestartSec`/`StartLimit*`/`After=network-online+time-sync`/`EnvironmentFile=` and **no `WatchdogSec`**; the operator log vocabulary asserted (caplog); `main(argv, *, deps)` tested with fakes (logging before config); `--regenerate` oneshot path; first-boot runbook present.
- **P4-9 — housekeeping (fall-through WARNING de-dup) + Phase-4 deep-dive.** Gate: WARNING de-dup asserted (caplog); full-seven deep-dive CONFIRM, no CRITICAL/HIGH; phase-gate numbers + uncovered-lines audit (pragma+thin-seam, not just %).

Parallelizable: P4-1, P4-2, P4-3 independent. P4-4 feeds P4-5/P4-5b. P4-5→P4-6→P4-7 chain. P4-8 depends on P4-6. P4-9 last.

## §21 Resolutions: Implemented vs Deferred
**Implemented:** R7 (P4-3+P4-8), R10/A2 (P4-2), R11 (§A depth + shipped backstop/gap), R18 (P4-5/P4-7), R20 (P4-1/P4-2), R21 (every gate + lazy-import guards), R6 (P4-3/P4-5), R9/D6 (P4-7), A6/A7 (state_dir, low-freq writes), R8′ (P4-8 logging). **Reused:** R5, R12, R15/R16/R17, R19, H4/H5/H14. **Deferred (rationale):** R13 player-subprocess → systemd tier; R8′ `GET /logs` + R23 non-blocking handlers + D4 control API → Phase 6 (only the in-memory `StationStatus` is pre-built, no HTTP); §7-Q5 rate limiting → reserved; SIGHUP reload → restart in v1.

## Open Questions — RESOLVED (Rev 2)
All Rev-1 Q1–Q10 are ruled and folded (see changelog item 11). Remaining genuinely-open item for the panel: **§A's RAM-budget fraction + the stagger step** are tunable constants — confirm the defaults (≤40% RAM for look-ahead; `stagger_step ≈ 2s × station_index`) or set them.

## Risks & Hardening (continued)
- **H21** native SIGSEGV → systemd tier-1 `Restart` (no `WatchdogSec` footgun); supervisor documents it can't catch it.
- **H22** worst-case render stall → §A depth masks clusters during tracks; irreducible residual (cold start / patter-opening block) → R11 backstop for one render + startup WARNING. No sustained loop.
- **H23** device reorder → R10 **port-path** udev (P4-2) + config-load distinct-PortId (shipped) + `docs/ops` verify.
- **H24** DST fold → `next_midnight` via `zoneinfo`, explicit spring/fall tests.
- **H25** midnight race → regen writes next file + flips signal (file-then-event), never cancels run_once; straddle splices at end-of-item; **regen failure per-station isolated**.
- **H26** state_dir on slow SD → A6/A7 (off boot SD, low-freq).
- **H27** shared client contention / RAM → §A RAM ceiling + dedicated sink executor + stagger; reactive failover.
- **H28** poison item → supervisor advance-past after K crashes + systemd `StartLimit*` (no global thrash).
- **H29** xrun on a contended Pi → explicit `blocksize`/`latency` + xrun-is-a-glitch (logged, in-stream recovery).

## Success Criteria (Phase Gate — full-seven)
- [ ] N stations run from one daemon, each on its own distinct physical device (R10), gapless (§10), R11 intact.
- [ ] Each station: first-start generates+persists; restart resumes mid-day (R6/R12); end-of-day re-slices; **a render-poison item is skipped after K crashes, never an infinite loop**.
- [ ] In-process supervisor restarts to known-good without affecting siblings (R7 t2); systemd owns the process + `StartLimit*` terminal-fails instead of thrashing (R7 t1); **no `WatchdogSec` reboot loop**.
- [ ] Midnight regen DST-correct (R18/R9), per-station isolated (a bad tomorrow-grid doesn't kill today), in-flight segment uncut (§8.6, positive "aired in full" assertion); straddle-midnight specified.
- [ ] `SoundDeviceSink` behind the unchanged `AudioSink`; only the `sounddevice` write is hardware (R20); lazy import (R21); `libportaudio2` documented.
- [ ] **C1 fixed:** look-ahead depth (worst consecutive patter), RAM-clamped, staggered — no sustained backstop-loop on patter clusters; irreducible residual bounded to one render + WARNING.
- [ ] Operability: minimal `StationStatus` + periodic "N/N ON AIR" summary; operator log vocabulary asserted; first-boot runbook + port-path udev recipe shipped.
- [ ] `recent_tracks` threaded (honest churn, default `()`); `item_kind` Protocol param removed.
- [ ] Gate: ruff + ruff-format + mypy `--strict` clean; pytest green `-m "not hardware and not network"`; `--cov-fail-under=80` (R20); per-increment records + BUILD-LOG; full-seven deep-dive CONFIRM, no CRITICAL/HIGH.
