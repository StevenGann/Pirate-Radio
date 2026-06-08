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

## Team validation (after the throttle cleared)

- **Senior Dev — CONFIRM.** Independently re-read persistence/config/grid/models/
  scanner; agreed no CRITICAL/HIGH; README rewrite accurate. Noted two impl wins the
  manager pass undersold (the `next_block_starts_at` tz validator; the A2 dict→PortId
  migration).
- **Devil's Advocate — DISPUTE, found a HIGH the manager pass missed:**
  - **HIGH — `clock.py` `_resolve_local_zone()` freezes a fixed UTC offset →
    DST-broken.** `datetime.now().astimezone().tzinfo` returns a fixed-offset
    `timezone` (verified: identical Jan/Jul offset), not a DST-aware `ZoneInfo`.
    Captured once at construction, a long-lived `SystemClock()` drifts an hour across
    a DST transition — contradicting the module's own "zoneinfo owns DST" docstring,
    R9, and D6. Latent in Phase 1 (no daemon yet) but it's foundation clock code with
    the DST contract in its own docstring → HIGH. **Being remediated now (bug-fix
    TDD):** `_resolve_local_zone` honors `PIRATE_RADIO_TZ` (Q5) then resolves the
    system IANA zone (`/etc/timezone` / `/etc/localtime`) → `ZoneInfo`; fixed-offset
    only as a logged last resort. Regression tests added to `tests/clock/`.
  - **MEDIUM — `config._check_env_vars_present` only checks LLM `api_key_env`,** not
    `tts_providers` credentials, so an ElevenLabs station boots clean and fails at
    first synth; the docstring's "every referenced *_env" overclaims. Soften the
    docstring now; the real tts-credential env check lands in Phase 2 when a TTS
    engine reads them. *(Carry-forward.)*
  - LOW — single-generation `.bak` (already documented/accepted, A7).

**Net:** the deep-dive's value was the DST HIGH — exactly what manager-led review
missed and team validation caught. Remediation in progress; remaining validators
(Old Man, QA, RPi, Fact Checker, Field Op) to run staggered.

## Remediation (bug-fix TDD, completed)

- **HIGH clock DST — FIXED.** Strict-TDD bug fix: 8 regression tests authored from
  spec → confirmed RED → adopted (3-0, focused panel) → implemented GREEN.
  `clock._resolve_local_zone()` now honors `PIRATE_RADIO_TZ` (Q5) → resolves the
  system IANA name via `_system_zone_name()` (`/etc/timezone`, then the
  `/etc/localtime` symlink's `zoneinfo/<name>` tail) → `ZoneInfo`; a fixed offset is
  only a logged last resort. Tests pin: env override is DST-aware (Jan≠Jul offset),
  default path returns a real `ZoneInfo` (not `datetime.timezone`), bad env WARNs and
  degrades without raising, unresolvable host degrades with a WARNING, and the
  `_ETC_TIMEZONE`/`_ETC_LOCALTIME` parsing seam (file / symlink / unresolvable→None).
- **MEDIUM tts_providers-env overclaim — FIXED (docstring).** `config` module +
  `_check_env_vars_present` docstrings now state the check covers LLM `api_key_env`
  only; the TTS-credential preflight is an explicit Phase-2 carry-forward. (The real
  check still lands in Phase 2 when a TTS engine reads those vars.)
- Gate after remediation: ruff + ruff-format + mypy clean, **194 tests**, 97.81% cov.

## Team validation — Batch 1 (Old Man, QA Engineer, RPi Expert), staggered

All three **CONFIRM**; no new CRITICAL/HIGH. Independent re-reads validated A4, R5/R6/R17
(persistence), R10/A2 (audio devices), R14-R17, D6, and the clock DST fix itself
(`_system_zone_name` parses `/etc/timezone` + the `/etc/localtime` `zoneinfo/<name>`
symlink tail correctly for Raspberry Pi OS Bookworm; fixed-offset fallback is visibly
WARNed, not silent).

- **Convergent finding — QA MEDIUM / Old Man LOW: clock.py third fallback tier untested.**
  When `_system_zone_name()` returns a *name* but `ZoneInfo(name)` raises (e.g. tzdata
  absent), the `try/except` → fixed-offset path (clock.py ~145-146) had no test, so an
  impl that dropped the guard would pass. **Remediated:** added
  `test_unloadable_system_name_degrades_to_fixed_offset_with_warning` (monkeypatches
  `_system_zone_name`→`"Fake/Zone"`, asserts no-raise + tz-aware + WARNING names the
  value) and tightened `test_unresolvable_system_zone_degrades...` to assert the WARNING
  names `PIRATE_RADIO_TZ`. Branch now covered.
- **LOW housekeeping (Old Man):** README test count refreshed; BUILD-LOG "(commit
  pending)" language removed.
- **LOW declined (RPi Expert): numpy `platform_machine == "aarch64"` marker.** Pinning
  it would strip numpy from x86_64 dev/CI (this host + GitHub runners), breaking the
  suite; numpy ships x86_64 + aarch64 wheels and only 32-bit armhf lacks one (not
  cleanly expressible as a marker). The documented prose warning in README/pyproject
  stands as the right mitigation.
- Gate after Batch-1 remediation: ruff + ruff-format + mypy clean, **195 tests**, 98.08% cov.

## Team validation — Batch 2 (Fact Checker, Field Operator), staggered

Both **CONFIRM**; no new CRITICAL/HIGH. Deep-dive validation now complete across all
seven agents (Senior Dev, Devil's Advocate, Old Man, QA, RPi, Fact Checker, Field Op).

- **Fact Checker — CONFIRM.** Independently re-verified every quantitative claim against
  HEAD: 195 tests / 98.08% cov / ruff+mypy clean; `datetime.now()` only in clock.py
  (config hits are docstrings); no TODO/FIXME/XXX; the DST-bug premise empirically true
  (`datetime.now().astimezone().tzinfo` → fixed-offset, identical Jan/Jul); `datetime.UTC`
  valid on 3.11+; `Path.resolve()` symlink behavior as assumed. One LOW: stale
  `pyproject.toml` description ("design doc pending"). **Remediated.**
- **Field Operator — CONFIRM**, with an operator-facing MEDIUM the prior passes missed:
  - **MEDIUM — `PIRATE_RADIO_TZ` undocumented** where an operator would look. The clock
    WARNING tells the operator to set it, but it appeared nowhere in `.env.example` or
    `README.md`. **Remediated:** `.env.example` rewritten (real LLM/TTS credential vars +
    `PIRATE_RADIO_TZ`, dropping the stale `AUDIO_DEVICE`/`LOG_LEVEL` placeholders); README
    gained a Configuration section documenting it.
  - **LOW — second-tier clock WARNING** (system name resolves but `ZoneInfo()` can't load
    it) named the bad value but not the remedy. **Remediated:** message now names
    `PIRATE_RADIO_TZ` (and hints at the `tzdata` package); the regression test asserts it.
  - Confirmed: config/grid/persistence error messages name the offending station/file/
    path/weekday; recovery is non-crash-looping; all three clock fallback tiers log.
- Gate after Batch-2 remediation: ruff + ruff-format + mypy clean, **195 tests**, 98.08% cov.

## Deep-dive — final disposition

Complete. No CRITICAL or HIGH defects remain. The one HIGH (clock DST freeze) and the
operator-facing MEDIUM (`PIRATE_RADIO_TZ` discoverability) are fixed; all docstring/doc
overclaims reconciled. Accepted carry-forwards (tracked, not defects): `loudness_target_lufs`
range bound → Phase 2; TTS-credential env preflight → Phase 2; design-doc §6/§8.4 text
corrections → when resume/generator land; single-generation `.bak` (A7, accepted). One LOW
declined with rationale (numpy `aarch64` marker — would break x86_64 dev/CI).
