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

### Phase 1 — MVP vertical slice (single station, stub TTS, gapless playback)  — PLAN ADOPTED
- [x] Implementation plan authored (planner) + panel review distilled `0009` →
  **adopted 6 AYE / 0 NAY / 1 abstain** (Fact Checker transient rate-limit).
  Governing amendments appended to `docs/plans/phase-1-implementation-plan.md`.
  Resolved: Q1 A6-governs (state_dir off boot SD), Q2 exact-track re-anchor,
  Q3 fixed refill default. Must-fix P1–P7, hardening H1–H13.
- [x] P1-1 `schedule/models.py` (ScheduleItem union + DailySchedule, R17) — focused 3-0 (QA/SeniorDev/DA); folded next_block_starts_at tz, variant-frozen, missing-fields, TrackItem-stray-field. +`--import-mode=importlib`. 155 tests, 98.63% cov.
- [x] P1-2 errors-R15 (ProviderError taxonomy) + `audio/buffer.py` (AudioBuffer R14, DEFAULT_SAMPLE_RATE H5) — focused 3-0; folded channels>=1, fractional-rounding, zero-seconds. numpy dep. 170 tests, 98.73%.
- [x] P1-3 dj/protocols+fakes (TextGenerator/TTSEngine/AudioSink + NullDJ/StubTTS/FakeAudioSink) + audio/decode (Decoder/FakeDecoder) — 2-1 (DA NAY on coverage-gaming, fixed: parametrized exact-duration + non-trivial wpm + silent assert). pytest-asyncio. 186 tests, 98.25%. (FailingTTS/FailingDecoder + SoundDeviceSink → later increments)
- [ ] P1-4 `schedule/generator.py` (R19, P3 boundary, H1) · P1-5 `schedule/resume.py` (find_now R11/R12, P6, H4)
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

### Phase 2 — Local voice (Piper, loudness)  — NOT STARTED
### Phase 3 — AI DJ (LLM patter, ranked failover)  — NOT STARTED
### Phase 4 — Multi-station (supervisor, systemd)  — NOT STARTED
### Phase 5 — Offline tagging tool  — NOT STARTED
### Phase 6 — Control API (FastAPI, in v1 per D4)  — NOT STARTED

### Final — deep-dive code-quality + documentation review  — MANAGER-LED (team validation pending)
- Manager-led pass `0010` (full team blocked by a transient provider rate-limit).
  No CRITICAL/HIGH code defects; A4/R5/R6/R10/A2/R14-R17/D6 spot-verified in code.
  Fixed HIGH: stale README rewritten. Fixed MEDIUM: strict-tdd.md focused-panel note.
  Carry-forward: loudness_target_lufs bound (Phase 2); design-doc §6/§8.4 corrections
  (when resume/generator land). Re-run full team staggered once throttle clears.

## Notes
- Quality gate as of grid: ruff clean, mypy clean (10 files), 101 tests, 98.30% cov.
- Hardware/external code is built behind Protocols + unit-tested with fakes; real
  integrations (audio device, Piper, LLM/TTS, FastAPI bind) are deferred/marked.
