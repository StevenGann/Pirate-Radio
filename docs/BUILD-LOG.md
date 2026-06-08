# PiRate Radio — Autonomous Build Log

Running log of the overnight autonomous build (started 2026-06-07 night). Updated
after each increment so progress survives context summarization. Process for every
increment: **tests authored from spec → confirmed RED → panel reviews the tests
(≤1 NAY adopts) → implement to GREEN → ruff/mypy/pytest gate → commit.**

Mandate: proceed through phases (§20), commit per phase, then a full-team deep-dive
code-quality + documentation review. See memory `overnight-autonomous-build`.

## Status

### Phase 0 — Skeleton (config + validation, catalog, grid loader, flat-JSON state) — ✅ COMPLETE
- [x] **errors + clock** — 7-0. `0004`. (commit d1d4fe1)
- [x] **persistence** (atomic durable JSON) — 5-2 → Rev2 → 7-0. `0005`. (06b0c03)
- [x] **catalog** (models, metadata, scanner) — 6-1. `0006`. (dfbb696)
- [x] **grid** (loader + validation) — 6-1. `0007`. (25ef32c)
- [x] **audio_devices + config** (R10/A2 resolver + §12 validation) — 4-3 → Rev2 (A2 restored) → 7-0. `0008`.
- [x] **PR10 cleanup** — `hello()` retired; smoke imports real modules.
- [x] Phase 0 COMPLETE — 133 tests, ruff/mypy clean, 98.51% cov.

### Phase 1 — MVP vertical slice (single station, stub TTS, gapless playback)  — ✅ COMPLETE
- [x] Implementation plan authored (planner) + panel review distilled `0009` →
  **adopted 6 AYE / 0 NAY / 1 abstain** (Fact Checker transient rate-limit).
  Governing amendments appended to `docs/plans/phase-1-implementation-plan.md`.
  Resolved: Q1 A6-governs (state_dir off boot SD), Q2 exact-track re-anchor,
  Q3 fixed refill default. Must-fix P1–P7, hardening H1–H13.
- [x] P1-1 `schedule/models.py` (ScheduleItem union + DailySchedule, R17) — focused 3-0 (QA/SeniorDev/DA); folded next_block_starts_at tz, variant-frozen, missing-fields, TrackItem-stray-field. +`--import-mode=importlib`. 155 tests, 98.63% cov.
- [x] P1-2 errors-R15 (ProviderError taxonomy) + `audio/buffer.py` (AudioBuffer R14, DEFAULT_SAMPLE_RATE H5) — focused 3-0; folded channels>=1, fractional-rounding, zero-seconds. numpy dep. 170 tests, 98.73%.
- [x] P1-3 dj/protocols+fakes (TextGenerator/TTSEngine/AudioSink + NullDJ/StubTTS/FakeAudioSink) + audio/decode (Decoder/FakeDecoder) — 2-1 (DA NAY on coverage-gaming, fixed: parametrized exact-duration + non-trivial wpm + silent assert). pytest-asyncio. 186 tests, 98.25%. (FailingTTS/FailingDecoder + SoundDeviceSink → later increments)
- [x] P1-4 `schedule/generator.py` (§8.4 fill, R19 seedable, P3 midnight roll, H1 constants,
  H2 soft repeat, H3 typed `ScheduleError`) — focused 3-panel: Rev1 3-NAY → Rev2 **2 AYE / 1
  NAY → adopted**; DA's two post-adoption blockers (false overflow assertion → guaranteed
  residual-gap invariant; loose transition-duration bound → drift relationship) both folded in.
  `0011`. 211 tests, 98.29% cov, generator.py 100%.
- [x] P1-5 `schedule/resume.py` (`find_now` → typed `NowPlaying`; R11 gap path, R12 re-anchor,
  H4 anchor-once + binary search) — focused 3-panel **3 AYE / 0 NAY**; folded strictly-increasing
  starts invariant + R11 gap assertion + single-item/patter-first/inclusive-start coverage.
  Wrong-patter-duration & patter-first-drift scoped to Phase 2 (StubTTS is deterministic).
  Applied the deferred §6 design-doc correction (H13). `0012`. 227 tests, 98.39% cov, resume.py 100%.
- [x] P1-6 `pipeline/` (timing/segment/buffer/producer/player + `run_once`) — look-ahead
  producer/consumer: P1 no-drop, R11 backstop (producer-substitution + player gap-fill, kept
  distinct), P2 Sleeper seam + R21 virtual time (zero wall-clock), §10 transition silence.
  Added `FailingTTS`/`FailingDecoder` fakes. Focused 3-panel Rev1 3-NAY → Rev2 **3 AYE / 0 NAY**
  (DA caught the `AudioBuffer ==`→ValueError; QA/Senior caught the P1 "don't drop slow item"
  contradiction). `0013`. 250 tests, 98.54% cov, pipeline ~100%.
- [x] P1-7 config `state_dir` (A6: mutable state off the boot SD; required, exists+writable,
  logged). Focused panel 1-NAY → adopted; A6 narrowing (only state_dir writable; content/
  schedule readable) was already ratified 7/7 in 0009 §Q1. Folded: state_dir-as-file, a
  deterministic mocked-os.access writability test, isinstance(Path) + resolved-path log
  assertions, `match=`. `0014`. 257 tests, 98.56% cov.
- [x] P1-8 catalog cache (A9) + committed golden P5 guard — focused panel Rev1 2-NAY → Rev2
  **3 AYE / 0 NAY** (DA caught the `is`-identity cache gaming → scan-spy; QA/DA caught the
  byte-exact golden's pydantic fragility → value-equality compare). `CatalogCache` dict-keyed
  by content_dir, dir-mtime signature, FAT/in-place-edit limits documented (H9). Golden
  fixture committed. `0015`. **267 tests, 98.60% cov.**
- **Phase 1 COMPLETE** — P1-1..P1-8 all green. NOT a deployable radio yet (coordinator/
  supervisor/midnight-regen/systemd/real audio = Phase 4, H10).
- NOTE: the committed golden-JSON cross-run determinism guard (P5) still pending — fold into P1-8.
- NOTE: `run_once` is the producer+player harness over pre-selected items; the
  `DailySchedule → find_now → run_once` daily slice is the Phase-4 coordinator's job.
- [ ] P1-6 `pipeline/` (P1 no-drop, P2 Sleeper-seam, R21) · P1-7 config state_dir (A6) · P1-8 catalog cache (A9)

#### Resume handoff (paused mid-Phase-1)
Paused before P1-4 deliberately: the generator's `_transition` / `_slot_boundary` /
`_bind` helpers were elided in the plan and need real design decisions (best made
fresh, not improvised at the end of a long session); the pipeline (P1-6) needs the
virtual-time/Sleeper-seam contract (P2) nailed. All committed; resume is lossless.

**Settle these in P1-4 before implementing:**
- `_slot_boundary`: roll `Slot.end == time(0,0)` to **next-day midnight** (P3) — else
  the final block computes a negative span and emits zero tracks. RED test: PM block
  of a `00:00→12:00 / 12:00→00:00` grid fills.
- `_transition`: a `block_transition` at each slot start (§8.4.1) — decide closing
  (`block_name`=prior slot) vs opening (`next_block_name`/`next_block_starts_at`=this
  slot); handle slot 0 (no prior). Pin via observable-field tests.
- H1 name `station_id` 5.0s / `block_reminder` 8.0s / `0.05` down-weight as constants.
  H2 document repeat_window = soft down-weight (a recent track CAN repeat). H3
  `groups[slot.group]` → typed `PirateRadioError` when a grid group is absent.
- Test with a **synthetic Catalog** (build `Track(...)` with long durations directly —
  no real file needed) so a 24h schedule is ~dozens of items, fast + deterministic.
  R19/P5: two-run `model_dump_json` identical + persist→load→regenerate identical
  (reuse `persistence.atomic_write_json`); committed golden JSON can land with P1-5.
- NOTE: Phase 1 is NOT a deployable radio (no coordinator/supervisor/midnight-regen
  /systemd — those land in Phase 4). Per-increment reviews may use a focused panel
  (QA + Senior Dev + Devil's Advocate, the highest-signal for test quality) given
  overnight throughput; the final deep-dive uses all seven.

### Phase 2 — Local voice (Piper, loudness)  — PLAN ADOPTED
- [x] Implementation plan authored (planner) + full seven-agent review. Rev 1 **2 AYE / 5
  NAY** → revised → Rev 2 **6 AYE / 1 NAY → adopted** (`0016`). DA's lone-NAY CRITICAL folded
  in as binding amendment A1 (wire `preflight_binaries` into `load_config(preflight=True)`)
  + A2 (short-patter assert-to-target). Resolutions: f32le, scipy `resample_poly`, stdlib
  `wave` (drop soundfile), pad-then-measure, loudness `ge=-40/le=0` + WARNING clamp, mono v1
  + one station format, loudness mandatory, separate boot preflight, `normalize_to` via
  `asyncio.to_thread`. Deps: `pyloudnorm>=0.2.0,<0.3`, `scipy>=1.15,<2`.
- [x] P2-1 `audio/loudness.py` (EBU R128 via pyloudnorm; pad-then-measure; clamp+WARNING;
  immutable) + deps (`pyloudnorm`, `scipy`) + `loudness_target_lufs` `ge=-40,le=0` bound
  (0010 carry-forward resolved) — focused panel **3 AYE / 0 NAY**; folded A2 tolerance 2.5→0.6,
  pad-invariant test, DEBUG-passthrough caplog, new-buffer identity. `0017`. 280 tests, 98.58% cov.
- [ ] P2-2 `audio/resample.py` — **next** · P2-3 `audio/decode.py` FfmpegDecoder · P2-4 typed provider
  configs + `audio/binaries.py` + preflight wiring · P2-5 `dj/tts.py` Piper/Espeak · P2-6
  producer loudness wiring + player format/logging.
### Phase 3 — AI DJ (LLM patter, ranked failover)  — NOT STARTED
### Phase 4 — Multi-station (supervisor, systemd)  — NOT STARTED
### Phase 5 — Offline tagging tool  — NOT STARTED
### Phase 6 — Control API (FastAPI, in v1 per D4)  — NOT STARTED

### Final — deep-dive code-quality + documentation review  — ✅ COMPLETE (all 7 validated)
- Manager-led pass `0010` (full team initially blocked by a transient provider rate-limit).
  No CRITICAL/HIGH code defects; A4/R5/R6/R10/A2/R14-R17/D6 spot-verified in code.
  Fixed HIGH: stale README rewritten. Fixed MEDIUM: strict-tdd.md focused-panel note.
  Carry-forward: loudness_target_lufs bound (Phase 2); design-doc §6/§8.4 corrections
  (when resume/generator land).
- **Team validation:** Senior Dev CONFIRM. **Devil's Advocate DISPUTE → found a HIGH
  the manager pass missed: clock.py DST freeze.** Both DA findings remediated via
  bug-fix TDD (clock regression tests, 3-0; config docstring softened). (commit 5d377de)
- **Batch 1 (Old Man + QA + RPi) — all CONFIRM, no new CRITICAL/HIGH.** Convergent
  finding (QA MEDIUM / Old Man LOW): clock.py third fallback tier (system name resolves
  but `ZoneInfo()` can't load it — missing tzdata) was untested → added regression test
  + tightened the unresolvable-host WARNING assertion. LOW housekeeping: README count
  refreshed; "(commit pending)" language removed. RPi LOW (numpy platform marker)
  **declined** — an `aarch64` marker would strip numpy from x86_64 dev/CI; prose warning
  stands. Gate after batch-1 remediation: 195 tests, ruff/mypy clean.
- **Batch 2 (Fact Checker + Field Operator) — both CONFIRM, no new CRITICAL/HIGH.**
  Fact Checker re-verified all gate numbers + the DST-bug premise empirically; LOW: stale
  pyproject description (fixed). Field Operator found an operability MEDIUM: `PIRATE_RADIO_TZ`
  undocumented for operators → `.env.example` rewritten with real vars + the TZ knob, README
  Configuration section added; second-tier clock WARNING now names the remedy (test asserts it).
- **Deep-dive COMPLETE — all 7 agents validated. No CRITICAL/HIGH remain.** Carry-forwards
  (Phase 2): loudness_target_lufs bound, TTS-credential env preflight; (later) design-doc
  §6/§8.4 text. Gate: 195 tests, 98.08% cov, ruff/mypy clean.

## Notes
- Quality gate as of grid: ruff clean, mypy clean (10 files), 101 tests, 98.30% cov.
- Hardware/external code is built behind Protocols + unit-tested with fakes; real
  integrations (audio device, Piper, LLM/TTS, FastAPI bind) are deferred/marked.
