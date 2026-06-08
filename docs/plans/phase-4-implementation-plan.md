# Phase 4 Implementation Plan — Multi-Station (Coordinator · Supervisor · systemd · Real Audio Sink · Midnight Regeneration) — **Rev 1 (for panel review)**

> **Status:** Rev 1 — authored from spec for seven-agent panel review. Strict spec-driven TDD applies (PiRate standing directive + MEMORY): every RED test is authored from this spec and **panel-reviewed BEFORE any implementation**, then driven GREEN. No code touches the tree until the panel signs off. Charter: ≤1 NAY adopts; ≥2 NAY → revise + re-vote.
> **Builds on:** Phases 0–3 (all the per-item mechanics — config, catalog, generator, resume, the look-ahead pipeline, the AI DJ + ranked failover, the `dj/build.py` boot seam). Phase 4 **wires proven seams**, it does not rebuild them.
> **Governing authority:** `PiRate_Radio_Design_Doc.md` §5.1, §5.4, §8.6, §20, and §21 Review Resolutions (R6/R7/R8′/R9/R10/R11/R12/R13/R18/R19/R20/R21/R23, D4/D6, A6) + `docs/decisions/0001`–`0032`. Where this plan and §21 disagree, **§21 governs.**

## Overview

Phase 4 turns the Phase 0–3 library into a **deployable radio**. Phases 0–3 shipped every per-item mechanic but nothing yet drives a *whole station for a whole day*, supervises N stations, plays to a real device, or rolls the schedule at midnight (the BUILD-LOG states this explicitly).

Phase 4 is thin orchestration: a station loop that slices `DailySchedule → find_now → run_once`, a coordinator that owns shared services + DjContext inputs + the midnight task, an in-process supervisor (R7 tier 2) plus a systemd unit (R7 tier 1), a real `SoundDeviceSink` behind the existing `AudioSink` Protocol, a real `UdevAudioDeviceResolver` (the slot `audio_devices.py` already reserves), and a logging entrypoint (`__main__.py`).

Two load-bearing constraints stay central: **never dead air (R11)** and **virtual-time testability (R18/R21)** — the station loop and midnight task take an injected `Clock` + `Sleeper`, exactly like `run_once` already does.

## Requirements

- Run N stations (`config.json` `stations`) from a single `asyncio` daemon, each on its **own distinct physical audio device** (R10/A2 already enforced at config load via `_check_audio_devices`).
- Each station: load-or-generate today's `DailySchedule`, resume mid-day via `find_now` (R11 gap path + R12 re-anchor already implemented), render+play its day gaplessly through the existing pipeline with the R11 backstop.
- Two-tier supervision (R7): in-process supervisor restarts a crashed station task to known-good state without touching siblings; a systemd unit owns the process and recovers a native SIGSEGV.
- Midnight regeneration (§8.6, R18): a coordinator task sleeps to next midnight (DST-correct via the injected `Clock`'s `zoneinfo` tz), regenerates each station's schedule, re-reads grids; the in-flight segment is **not** interrupted (finish, splice at next boundary). First-start generates if absent.
- Real `SoundDeviceSink` behind `dj/protocols.py:AudioSink`, gapless (§10), hardware-marked (R20: only the literal `sounddevice` write is `@pytest.mark.hardware`).
- The coordinator **owns DjContext inputs** and threads `text_generator`/persona/station into each station loop (migrating `run_once`'s defaulted DJ args upward, §7-Q4) and maintains a real **rolling `recent_tracks` history** per station.
- A **stated, bounded worst-case refill budget** so play-time ≥ refill-time at cold start / on short-item runs (the DA liveness concern).
- A logging entrypoint (`__main__.py`) that configures structured logging before the coordinator starts.

## Scope & Non-Goals

**In Phase 4:** `coordinator.py`, `supervisor.py`, `station.py`, `pipeline/daily.py`, `midnight.py`, `audio/sink.py` (`SoundDeviceSink`), the real `UdevAudioDeviceResolver` in `audio_devices.py`, `__main__.py` + `logging_setup.py`, `systemd/pirate-radio.service` + `docs/ops/` notes, and the carry-forwards (1–6) each in a named increment.

**Deferred — Phase 5 (offline tagging):** the AcoustID/MusicBrainz batch tool. **Deferred — Phase 6 (Control API, D4):** FastAPI, `GET /logs` (R8′/R23), bearer auth — Phase 4 ships **no** HTTP server but must not block the loop in a way that would later starve those handlers, and should expose station status as a plain in-memory structure the API can later read (Q6).

**Explicitly NOT in Phase 4 (with rationale):**
- **Subprocess isolation of the player (R13):** design-doc downgraded "promote to subprocess" to "expect a real refactor." Keep the station boundary clean (the `AudioSink` Protocol is the seam) but do **not** build subprocess isolation; SIGSEGV recovery is delegated to the systemd tier (R7).
- **Proactive rate limiting** (`max_requests_per_minute`, §7-Q5): RESERVED/NOT ENFORCED (per 0032). Quotas stay reactive (failover).
- **`SIGHUP` config reload** (§8.7): `config.json` changes require a daemon restart in v1.
- Crossfading, multi-format/stereo stations (Phase 2 fixed mono + one station format).

## Architecture

New modules, MANY SMALL FILES (<400 lines each), dependency flow strictly downward (no cycles); the coordinator is the only module importing config + build + all the others.

```
__main__.py            NEW  entrypoint: logging setup -> load_config -> Coordinator.run()
logging_setup.py       NEW  structured-logging configuration (R8' stdout/journald)
coordinator.py         NEW  owns shared services (catalog, DJ chains, persona), DjContext
                            inputs, the midnight task; constructs + supervises N stations
supervisor.py          NEW  in-process restart-on-failure (R7 tier 2); known-good restart,
                            backoff, sibling isolation
station.py             NEW  per-station orchestration: load-or-generate schedule, find_now,
                            drive the daily slice; the supervised unit
pipeline/daily.py      NEW  DailySchedule + find_now + Clock -> the ordered items for "today
                            from now", fed to run_once; the seam run_once's docstring names
midnight.py            NEW  sleep-to-next-midnight (injected Clock, DST-correct) + regenerate
audio/sink.py          NEW  SoundDeviceSink (AudioSink Protocol); only the sd write is hardware
audio_devices.py       EDIT add real UdevAudioDeviceResolver (the reserved Phase-4 slot)
systemd/pirate-radio.service   NEW  R7 tier 1 unit (Restart, WatchdogSec, After=)
docs/ops/udev-audio.md NEW  the udev-rule recipe for stable USB dongle names (R10)
```

Reused **unchanged**: `pipeline/run_once` + `Producer`/`Player`/`LookAheadBuffer`/`timing.py`, `schedule/resume.py`, `schedule/generator.py`, `dj/build.py`, `config.py`, `catalog/`, `persistence.py`, `clock.py`.

### Control flow (one cold start)

```
__main__  -> logging_setup -> Coordinator(config, clock, resolver, sink_factory, sleeper)
   builds once (shared): CatalogCache per content_dir, RankedTextGenerator per resolved LLM,
                         persona per station, RankedTTSEngine per station, one backstop per format
   Supervisor.run([Station(...) for s in config.stations]) + midnight task, gathered
   each Station task -> load_or_generate(today) -> daily.slice_from_now(find_now) -> run_once(...)
```

## Per-Module Low-Level Design

### `pipeline/daily.py` — the daily-slice driver (the seam `run_once` names)
- `slice_from_now(anchored: AnchoredSchedule, now: datetime) -> tuple[list[ScheduleItem], float, float]` — PURE. Uses `AnchoredSchedule.find_now(now)` to compute: items from the current/next item through end-of-day, the **seek offset** into the first item (`NowPlaying.offset_seconds`), and the **leading gap silence** (`NowPlaying.gap_seconds`, R11).
- `async def play_day(...)`: if in a gap, play `gap_seconds` of silence via the sink first (R11), then call `run_once(items=remaining, ...)`. **Seek-into-first-item** is the one new mechanic — **Q1:** extend `run_once`/`Producer` with `first_offset_seconds` (clean but churns a frozen, 100%-covered signature) vs trim in `daily.play_day` (keeps `run_once` frozen). Recommendation: trim in `daily.play_day`.
- 100% pure/virtual-time; tested with `FixedClock`, `FakeAudioSink`, `VirtualSleeper`, `StubTTS`/`FakeDecoder`, synthetic `DailySchedule`.

### `station.py` — per-station orchestration (the supervised unit)
- `class Station` holding resolved **immutable** deps (config slice, `RankedTextGenerator`, `RankedTTSEngine`, persona, backstop, sink, clock, sleeper, refill budget, the per-station `recent_tracks` deque). Construction does no I/O, no network (R21).
- `async def run(self)`: (1) `_load_or_generate(today)` — `load_with_recovery(...)`; on `StateCorruptionError` (R6) or absence, `generate_schedule(...)` with `derive_seed(day, station.name)` + `atomic_write_json(...)` (first-start + R6 no-crash-loop). (2) `anchor(schedule, transition_silence=...)` (R12). (3) `slice_from_now(...)`. (4) `play_day(...)` threading the DJ chain/persona/station/loudness/format/backstop/sleeper/refill budget into `run_once`. (5) at end-of-day, await the next-day signal — **Q2:** poll `find_now` vs an `asyncio.Event` set by the midnight task. Recommendation: `asyncio.Event`.
- **§7-Q4 migration (CF1):** the DJ args `run_once`/`Producer` currently *default* are now **always supplied** by the Station from coordinator-owned values; the defaults stay for back-compat.
- **rolling `recent_tracks` (CF1):** coordinator owns a per-station `deque(maxlen=N)` of `TrackMeta`; **Q3:** record at the Player (air-accurate, touches a frozen file) vs `daily.play_day` (look-ahead-ordered, no churn). Recommendation: `daily.play_day`.
- Fully testable with fakes; the sink is injected.

### `coordinator.py` — shared services + DjContext inputs + midnight
- `class Coordinator(config, clock, resolver, sleeper, sink_factory)`. `sink_factory(port_id, sample_rate, channels) -> AudioSink` is the injection seam (tests → `FakeAudioSink`; prod → `SoundDeviceSink`; the coordinator never imports `sounddevice`).
- **Build-once shared services (§5.1):** per station resolve LLM (`resolve_station_llm`), `build_text_generator(llm)` (cache per identical resolved LLM — shared providers share one chain), `resolve_persona`, `build_tts_engine(...)`, `CatalogCache`, one pre-normalized backstop per station format.
- **DjContext inputs (§7-Q4, CF1):** **Q4:** physically move `build_dj_context` to the coordinator vs leave it in the producer and have the coordinator own only the *inputs*. Recommendation: leave it (moving churns a 100%-covered file); the coordinator supplies real persona/station/recent_tracks so the producer sentinels are never hit in production.
- **Worst-case refill budget (CF2 — load-bearing liveness):** compute `worst_case_render = Σ(llm timeouts) + Σ(tts timeouts)` (and the decode bound) from the *resolved config* (defaults: 3×20s LLM + 30s TTS ≈ 90s; decode 120s) — the coordinator is the only place that sees the whole chain. Set `refill_budget_seconds` + look-ahead `maxsize` so the R11 backstop fires promptly and the warm-buffer-at-boundary rule holds. **Q5:** also *cap* per-call timeouts so Σ < shortest item, vs accept R11 backstop coverage + a startup WARNING when `worst_case_render > shortest grid item`. Recommendation: WARNING + backstop coverage (R11 already guarantees no dead air; the stall degrades to the canned bumper, not silence).
- **decoder/TTS actual-rate verification (CF5, 0022/0032):** wire decoder + TTS + backstop from **one** `(sample_rate, channels)` per station so they agree by construction; **Q7:** + an explicit first-rendered-buffer assertion in the daily driver. Recommendation: both.
- `async def run(self)`: `asyncio.gather(supervisor.run(stations), midnight_task.run(stations))` under one `TaskGroup`.
- Imports no hardware; tested with `StaticAudioDeviceResolver` + a fake `sink_factory`.

### `supervisor.py` — in-process supervision (R7 tier 2)
- `class Supervisor(sleeper)`; `async def run(self, units)`. A `Supervisable` has `async def run()` + `name` (Station satisfies it).
- Per unit: run in a child task; on a non-cancellation exception, log (scrubbed — CF6), backoff via the injected `Sleeper` (R21), and **restart to known-good state** (re-enter `Station.run()` → re-loads/re-anchors from disk, R6/R12). **Sibling isolation (§5.4):** one unit's crash never cancels another.
- Backoff + crash-loop ceiling → escalate to process exit so the systemd tier restarts the process. **Q8:** escalation threshold + same-cause behavior.
- **Cannot** catch a native SIGSEGV (R7) — explicitly the systemd tier's job (documented).
- 100% pure with a crash-on-Nth-call `Supervisable` fake + `VirtualSleeper`.

### `midnight.py` — sleep-to-midnight + regenerate (§8.6, R18, DST-correct)
- `next_midnight(now, tz) -> datetime` — PURE, DST-correct via `zoneinfo` (the clock's `tz()`); seconds-to-sleep = `(next_midnight(now) - now).total_seconds()`.
- `async def run(self, stations)`: loop — compute sleep, `await sleeper.sleep(...)`, then per station re-read the grid (`resolve_grid_path`+`load_grid`+`validate_grid_against_catalog`, §8.7), `generate_schedule(...)`, `atomic_write_json(...)`, signal the day-roll (Q2).
- **In-flight segment NOT interrupted (§8.6, CF4):** regen writes only the *next* day's file + flips the signal; never cancels the running `run_once`. The station finishes its current item, then re-slices at the next boundary.
- `next_midnight` unit-tested across DST spring-forward + fall-back (explicit `ZoneInfo`); the loop with `FixedClock` + `VirtualSleeper`. Zero wall-clock.

### `audio/sink.py` — `SoundDeviceSink` (R20, the only new hardware)
- `class SoundDeviceSink` implementing `AudioSink` (`async def play(buf)`, returns only when fully consumed — gapless, §10). The blocking PortAudio write goes via `asyncio.to_thread`. **Q9:** persistent `sd.OutputStream` held open per station (genuinely gapless) vs per-buffer `sd.play`/`sd.wait`. Recommendation: persistent stream.
- **R20 thin seam:** ONLY the literal `stream.write(...)`/stream-open line is `# pragma: no cover` + `@pytest.mark.hardware`. Format coercion, the to_thread hop, and the stream lifecycle are pure, unit-tested with an injected `FakeOutputStream` (the stream factory is a constructor dependency, defaulting to the real `sd.OutputStream`). Plus a `@pytest.mark.hardware` smoke.

### `audio_devices.py` (EDIT) — real `UdevAudioDeviceResolver`
- Add `class UdevAudioDeviceResolver` implementing the `AudioDeviceResolver` Protocol: configured `audio_device` name → stable `PortId` keyed on the physical USB port path (R10/A2). The udev/ALSA enumeration call is the hardware seam; the mapping logic is pure (injected fake enumeration). `StaticAudioDeviceResolver` stays the CI resolver. Ship the udev-rule recipe in `docs/ops/udev-audio.md`.

### `__main__.py` + `logging_setup.py` (CF6 — Field-Op)
- `logging_setup.configure_logging(level)`: structured logging to stdout/journald (R8′).
- `__main__.py`: argparse (config path, `--regenerate`, log level), `configure_logging(...)` **first**, then `load_config(..., resolver=UdevAudioDeviceResolver(), clock=SystemClock(), preflight=True)`, construct `Coordinator` with the real `sink_factory` + `SystemClock` + `RealSleeper`, `asyncio.run(coordinator.run())`. Tested via a `main(argv, *, deps)` seam with injected fakes; the `asyncio.run` + real-resolver line is the only hardware-adjacent `pragma`. **Q10:** package is `src/pirate_radio` → `python -m pirate_radio`; confirm the entrypoint module path.

## How Each Carry-Forward Is Addressed

| # | Carry-forward | Addressed in | Increment |
|---|---|---|---|
| 1 | Coordinator owns DjContext inputs + threads DJ args (§7-Q4); rolling recent_tracks | coordinator owns persona/station/recent_tracks; station always supplies them; `build_dj_context` stays put (Q4) | P4-5, P4-6 |
| 2 | Worst-case summed-timeout refill budget (DA) | coordinator computes Σ timeouts, sets refill_budget+maxsize, startup WARNING; R11 backstop bounds dead air | P4-6 |
| 3 | Two-tier supervision (R7) | `supervisor.py` (tier 2) + `systemd/pirate-radio.service` (tier 1) | P4-3, P4-8 |
| 4 | Midnight regen, no mid-segment cut, first-start generates | `midnight.py` + `station._load_or_generate` | P4-7, P4-5 |
| 5 | Real SoundDeviceSink + distinct ports + decoder/TTS actual-rate (0022) | `audio/sink.py`; `UdevAudioDeviceResolver`; coordinator wires one format + first-segment assert | P4-1, P4-2, P4-6 |
| 6 | WARNING de-dup; `item_kind` removal; logging entrypoint; secret-scrub; tag-length cap | failover edit; Protocol param drop; `__main__`+`logging_setup`; supervisor scrub; cap in build_dj_context | P4-9, P4-5, P4-3 |

## Dependency-Ordered Increment Breakdown

Each increment: strict spec-driven TDD (tests authored → RED → focused panel reviews the tests, QA+SeniorDev+DA; full-seven for the plan + phase gate → GREEN → ruff/mypy `--strict`/pytest gate → one decision record).

- **P4-1 — `SoundDeviceSink` (`audio/sink.py`)** + `sounddevice` dep. First: pure-logic + thin hardware seam, depends only on the frozen `AudioSink` Protocol. Gate: format coercion + to_thread offload + gapless lifecycle unit-tested with `FakeOutputStream`; only `stream.write` hardware; CI green `-m "not hardware"`.
- **P4-2 — `UdevAudioDeviceResolver`** + `docs/ops/udev-audio.md`. Gate: name→PortId mapping unit-tested with fake enumeration; only the enumeration call hardware; `StaticAudioDeviceResolver` still the CI resolver.
- **P4-3 — `supervisor.py`** + secret-scrub. Gate: crash-on-Nth restart count, backoff via `VirtualSleeper`, sibling isolation, crash-loop ceiling → escalation; scrubbed logs.
- **P4-4 — `pipeline/daily.py`** (slice + seek/gap). Gate: `slice_from_now` correct across now-inside-item (R12 seek), now-in-gap (R11 silence + next), now-before-first, now-past-end (empty → regen signal); `play_day` plays gap then `run_once`; virtual time only.
- **P4-5 — `station.py`** + `item_kind` Protocol cleanup + tag-length cap. Gate: first-start generates+persists; load; corruption→regenerate not crash-loop (R6); mid-day resume re-anchors (R12); day-roll re-slices; `patter(context)` (no `item_kind`) green across callers+fakes; full fakes.
- **P4-6 — `coordinator.py`** (shared services, DjContext inputs, refill budget, actual-rate). Gate: shared-LLM reuse asserted (§5.1); real persona/station/recent_tracks; worst-case budget computed + startup WARNING when > shortest item (`caplog`); decoder+TTS+backstop one format + first-segment assert; injected `sink_factory`, no hardware.
- **P4-7 — `midnight.py`**. Gate: `next_midnight` DST spring/fall correct; `run` sleeps computed seconds (`VirtualSleeper`), re-reads grids, regenerates+persists, signals; in-flight segment not cancelled; `--regenerate` path; zero wall-clock.
- **P4-8 — `systemd/pirate-radio.service` + `__main__.py` + `logging_setup.py`** (CF6, R7 tier 1). Gate: unit has `Restart=on-failure`/`RestartSec`/`After=`/`WatchdogSec`/`EnvironmentFile=`; `logging_setup` asserted; `main(argv, *, deps)` tested with fakes (logging before config load).
- **P4-9 — housekeeping (fall-through WARNING de-dup) + Phase-4 deep-dive.** Gate: de-dup asserted via `caplog`; full-seven deep-dive CONFIRM, no CRITICAL/HIGH; phase-gate numbers recorded.

Parallelizable: P4-1, P4-2, P4-3 independent. P4-4 feeds P4-5. P4-5→P4-6→P4-7 chain. P4-8 depends on P4-6. P4-9 last.

## §21 Resolutions: Implemented vs Deferred

**Implemented:** R7 (P4-3+P4-8), R10/A2 (P4-2), R11 (P4-6 budget + shipped backstop/gap), R18 (P4-5/P4-7), R20 (P4-1/P4-2), R21 (every gate), R6 (P4-5), R9/D6 (P4-7), A6 (state_dir), R8′ (P4-8 logging).
**Carried, reused:** R5, R12, R15/R16/R17, R19, H4/H5/H14.
**Deferred (rationale):** R13 (player subprocess → systemd tier instead); R8′ `GET /logs` + R23 non-blocking handlers → Phase 6; D4 control API → Phase 6; §7-Q5 rate limiting → reserved.

## Open Questions for the Panel

1. **Seek-into-first-item:** `run_once` `first_offset_seconds` vs trim in `daily.play_day`. Rec: trim in `daily.play_day`.
2. **Day-roll handoff:** poll `find_now` vs an `asyncio.Event` from the midnight task. Rec: `asyncio.Event`.
3. **recent_tracks recording point:** Player (air-accurate, frozen file) vs `daily.play_day` (look-ahead, no churn). Rec: `daily.play_day`.
4. **DjContext assembly location:** move `build_dj_context` to coordinator vs leave it + coordinator owns inputs. Rec: leave it.
5. **Refill-budget enforcement:** cap per-call timeouts vs R11 backstop coverage + startup WARNING. Rec: WARNING + coverage.
6. **Phase-6 status surface:** how much in-memory station status to pre-build now (no HTTP)?
7. **Actual-rate verification:** construction-from-one-source vs + an explicit first-buffer assert. Rec: both.
8. **Supervisor crash-loop escalation:** restart ceiling + exit-for-systemd vs restart-in-process indefinitely?
9. **Sink gapless strategy:** persistent `sd.OutputStream` vs per-buffer `sd.play`/`sd.wait`. Rec: persistent stream.
10. **Entrypoint module path:** `python -m pirate_radio` (`src/pirate_radio/__main__.py`) — confirm.

## Risks & Hardening (H-series continued)

- **H21** native SIGSEGV in PortAudio → R7 tier-1 systemd `Restart`/`WatchdogSec`; in-process supervisor documents it cannot catch this (risk accepted, §5.4/R13).
- **H22** worst-case render stall → audible backstop, not dead air → P4-6 states/bounds the budget; startup WARNING when > shortest item.
- **H23** device reorder across reboots → R10 udev rules (P4-2) + config-load distinct-PortId enforcement (shipped); `docs/ops/udev-audio.md`.
- **H24** DST fold double/zero midnight → `next_midnight` via `zoneinfo` (P4-7), explicit spring/fall tests.
- **H25** midnight regen racing the in-flight segment → regen writes only the next file + flips a signal; never cancels the running `run_once`; splice at end-of-day (§8.6).
- **H26** state_dir on slow/unsafe SD → A6 (off boot SD, validated) + low-frequency writes only (A7).
- **H27** shared LLM/TTS client contention across N stations → shared chains built once (§5.1); reactive failover; `max_requests_per_minute` reserved.

## Success Criteria (Phase Gate — full-seven review)

- [ ] N stations run concurrently from one daemon, each on its own distinct physical device (R10), gapless (§10), R11 backstop intact.
- [ ] Each station: first-start generates+persists; restart resumes mid-day at the correct broadcast point (R6/R12); end-of-day re-slices.
- [ ] In-process supervisor restarts a crashed station to known-good state without affecting siblings (R7 tier 2); systemd unit owns the process + recovers SIGSEGV (R7 tier 1).
- [ ] Midnight task regenerates DST-correctly (R18/R9), re-reads grids, does **not** interrupt the in-flight segment (§8.6).
- [ ] `SoundDeviceSink` behind the unchanged `AudioSink` Protocol; **only** the literal `sounddevice` write is `@pytest.mark.hardware`/`pragma` (R20); CI green `-m "not hardware"`.
- [ ] Worst-case refill budget computed, stated, bounded; startup WARNING when it exceeds the shortest schedulable item (CF2).
- [ ] Coordinator wires decoder+TTS+backstop from one station format and guarantees actual-rate agreement (0022/0032 closed).
- [ ] `__main__.py` configures logging before the coordinator starts (CF6); systemd unit + udev recipe shipped.
- [ ] All CF (1–6) addressed; `item_kind` Protocol param removed; fall-through WARNING de-dup; secret-scrub; tag-length cap.
- [ ] Gate: ruff + ruff-format + mypy `--strict` clean; pytest green `-m "not hardware and not network"`; `--cov-fail-under=80` package-wide (R20); per-increment decision records + BUILD-LOG updated; full-seven deep-dive CONFIRM, no CRITICAL/HIGH.
