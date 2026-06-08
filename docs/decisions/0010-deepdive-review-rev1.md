# Deep-Dive Review — committed foundation (Phase 0 + Phase-1 P1-1..P1-3)

> **Status:** Manager-led pass. The full seven-agent deep-dive was dispatched but
> the provider hit a **transient burst rate-limit** ("not your usage limit") and no
> agent could complete, even at a 3-agent batch. Rather than idle, this is a
> manager-conducted audit of the actual shipped code + docs against the adopted
> resolutions and quality rules. **The full team will validate this once the
> throttle clears** (re-dispatch staggered).

## Scope
`src/pirate_radio/`: errors, clock, persistence, audio_devices, config,
catalog/{models,metadata,scanner}, schedule/{grid,models}, audio/{buffer,decode},
dj/{protocols,fakes}. Plus docs (design §21, decisions 0001–0009, README, BUILD-LOG,
process/strict-tdd, agent notes). 186 tests, 98.25% coverage, ruff+mypy clean.

## Code quality

- **Resolutions honored (spot-audited):** A4 verified — `datetime.now()` appears
  only in `clock.py` (config uses `clock.now().weekday()`); R5/R6/R17 intact in
  `persistence.py` (temp→fsync→replace→dir-fsync, copy-then-`.bak`, recovery,
  `schema_version` envelope); R10/A2 in `config._check_audio_devices` (distinctness
  on resolved `PortId`); R14/R15/R16/R17 in models/errors/config; D6 tz-aware
  throughout. No `TODO/FIXME/XXX` leftover.
- **Coverage misses are honest** (98.25%): the 5 missed lines / 7 partial branches
  are Protocol `...` stubs (clock, dj/protocols, audio_devices, decode) and
  defensive branches (`metadata` `audio.info is None`, `config` env-loop) — not
  coverage-gamed, consistent with QA's pragma discipline.
- **MEDIUM — `loudness_target_lufs` has no range bound** (`config.StationConfig`):
  it's an unbounded float; a nonsensical value (e.g. +50) passes. Low impact (no
  Phase-0 reader; Phase 2 loudness will read it) — add a `le=0` bound when Phase 2
  wires loudness, or now. *(Carry to Phase 2.)*
- **LOW — `persistence._replace_keep_bak` reads the whole file into memory** and the
  `.bak` is single-generation. Both are documented (A7) and fine for the small
  low-frequency state this primitive is for; flagged so it's not used on a hot path.
- **No CRITICAL/HIGH code defects found** in the shipped modules. The discriminated
  unions, atomic-write/recovery, grid tiling fence (Q3), and R10/A2 resolution were
  each adversarially reviewed at increment time and hold up on re-read.

## Documentation

- **HIGH — `README.md` is severely stale.** It still says *"The design document is
  pending… No application code yet — awaiting the design doc."* Reality: a full
  design doc (+§21), Phase 0 complete, Phase 1 in progress, 186 tests. This is the
  one finding a newcomer would hit first. **Remediated in this pass** (rewritten to
  reflect actual status, layout, deps, process, and honest "not yet a deployable
  radio" status).
- **MEDIUM — `docs/process/strict-tdd.md` says "seven-agent panel"** but Phase-1
  per-increment reviews used a **focused 3-agent panel** (QA + Senior Dev + DA) for
  overnight throughput. The deviation was logged in BUILD-LOG but not in the process
  doc itself. **Remediated** (process doc now documents the focused-panel option for
  routine increments, with the full seven for plans/phase-gates/the deep-dive).
- **LOW — design-doc §6 (`NowPlaying`, H13) and §8.4 (`state_dir`, Q1) corrections
  not yet applied** to the design doc body — correctly deferred until the resume/
  generator modules land (tracked in 0009 + BUILD-LOG). No action now.
- **Audit trail is honest and complete** (0001–0010, BUILD-LOG, agent notes); no
  contradictory or duplicated decision content found.

## Actions taken in this pass
1. Rewrote `README.md` to current reality (HIGH).
2. Reconciled `docs/process/strict-tdd.md` with the focused-panel practice (MEDIUM).
3. Logged the two carry-forward items (`loudness_target_lufs` bound → Phase 2;
   design-doc §6/§8.4 corrections → when resume/generator land).

## Pending
Full seven-agent validation of this report once the provider throttle clears
(re-dispatch staggered, 2–3 at a time). No CRITICAL/HIGH *code* issue blocks
resuming construction at P1-4.
