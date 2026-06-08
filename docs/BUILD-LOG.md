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

### Phase 2 — Local voice (Piper, loudness)  — ✅ COMPLETE
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
- [x] P2-2 `audio/resample.py` (`to_rate` via scipy `resample_poly`, per-channel; no-op
  identity; `target_rate<=0` guard) — focused panel QA AYE / DA NAY → adopted; folded DA's
  gameable-stereo (distinct channels) + guard-match fixes. mypy override for pyloudnorm/scipy
  (also clears a P2-1 latent stub error). `0018`. 287 tests, 98.60% cov, resample.py 100%.
- [x] P2-3 `audio/decode.py` `FfmpegDecoder` (real ffmpeg subprocess via asyncio.to_thread;
  pure argv/parser/error-map/exc-map; f32le @ station rate; H14 timeout; H12 corrupt→backstop)
  — focused panel Rev1 2-NAY → Rev2 **3 AYE / 0 NAY**; folded argv+timeout spy (patched real
  subprocess.run), thread-offload assertion, spaces-in-path, non-UTF-8 stderr, partial-output
  timeout. `0019`. 314 tests (+1 hardware smoke), 98.68% cov, decode.py 99%.
- [x] P2-4 typed `tts_providers` (R16: Piper/Espeak/ElevenLabs provider configs, PrivateAttr
  stash, `provider()`) + `ffmpeg_binary`/timeouts (H14) + `audio/binaries.py`
  (resolve_binary/preflight_binaries) + A1 wiring (`load_config(preflight=True)`, H20-separate)
  — focused panel Rev1 2-NAY → Rev2 **3 AYE / 0 NAY**; folded A1-delta proof, mouse `match`,
  PrivateAttr copy-safety, H20 negative test, production-remedy matches. `0020`. 334 tests, 98.63% cov.
- [x] P2-5 `dj/tts.py` `PiperTTS` + `EspeakTTS` (real local voice; pure WAV parser + argv/speed
  math + error/exc maps; subprocess via asyncio.to_thread; resample to station rate H5; H14
  timeout; H16 piper explicit-binary) — focused panel Rev1 2-NAY → Rev2 **2 AYE / 0 NAY**;
  folded direct map tests, espeak argv spy, 1e-7 golden, non-bypassable resample. `0021`.
  364 tests, 98.74% cov, tts.py 100%.
- [x] P2-6 producer loudness wiring (normalize each segment via asyncio.to_thread, Q9) +
  run_once threading (C3) + format-desync assert (C4) + player resume logging + README Phase-2
  prereqs (H19) — focused panel Rev1 (QA AYE-cond/DA NAY) → Rev2 **2 AYE / 0 NAY**; folded the
  normalize-result-enqueued marker test, nothing-aired desync assert, order-bound resume + negative.
  `0022`. 371 tests, 98.76% cov, pipeline 100%.
- **Phase 2 COMPLETE** — P2-1..P2-6 all green. Real decode (ffmpeg), EBU R128 loudness, Piper +
  espeak TTS, binary preflight, loudness-normalized gapless playback. Carry-forward (Phase 4):
  run_once can't verify decoder/TTS *actual* rate vs declared (coordinator's job). Still NOT a
  deployable radio (no coordinator/supervisor/midnight-regen/systemd/real-sink; AI DJ + ranked
  failover + ElevenLabs = Phase 3).
### Phase 3 — AI DJ (LLM patter, ranked failover)  — ✅ COMPLETE
- **Plan adopted 2026-06-08, 7 AYE / 0 NAY** after one revision round (Rev 1 → Rev 2 under the
  ≥2-NAY charter). Plan: `docs/plans/phase-3-implementation-plan.md`; vote + must-fix audit trail:
  `docs/decisions/0023-phase3-plan-adopted.md`.
- **Rev-1 → Rev-2 must-fixes:** intro/outro TrackItem no longer drops the song (decode every
  TrackItem; segment assembly → Phase 4); no cross-sibling `tts→text` import (mappers + `post_json`
  → new `dj/_http.py`); `build_tts_engine` total (exhaustive `else: raise` + empty-chain guard +
  explicit raise, no `assert`); failover floor total (`_ranked_call` catches every exc, re-types
  non-ProviderError → Unavailable); P3-8 back-compat defaults (existing ~13 call sites stay valid);
  real offload proof (`get_ident` + `sys.modules` import-guard + grep guard); `anthropic` pin gated
  PLACEHOLDER (verified-live 0.107.1, resolve at P3-5); ElevenLabs 401 dual-meaning; QA's 12 named
  tests + H26 `_sanitize` newline-strip; Field-Op degrade WARNING + README prereqs.
- **Ratified rulings:** skip-on-Fatal, `DjContext | None`, PCM whole-clip, deps `anthropic`+`httpx`,
  no in-place retry, rate-limit → Phase 4.
- **Increment order (strict spec-driven TDD each):** P3-1 `dj/context.py` → P3-2 `dj/prompts.py`
  → P3-3 Protocol narrow + `ScriptedDJ` → P3-4 `dj/failover.py` → P3-5 `dj/_http.py` + `dj/text.py`
  (anthropic pin resolved FIRST) → P3-6 `ElevenLabsTTS` + cloud preflight → P3-7 `dj/build.py`
  → P3-8 producer wiring.
- **Phase-4 carry-forwards opened:** summed-timeout refill budget (DA); fall-through WARNING de-dup
  (Old Man); config→constructor timeout threading detail (P3-7).
- **P3-1 ✅** `dj/context.py` (DjContext/BlockContext/TrackMeta, R16; year bounded; H26-safe) — `0024`.
- **P3-2 ✅** `dj/prompts.py` (grounded "invent nothing" prompts; `_sanitize` H26 in-path) — `0025`.
- **P3-3 ✅** narrow `patter`→`DjContext|None` + `ScriptedDJ` fake (mypy-strict gate) — `0026`.
- **P3-4 ✅** `dj/failover.py` (ranked, skip-on-Fatal, TOTAL floor, R15/§9.3) — `0027`.
- **P3-5 ✅** `dj/_http.py` + `dj/text.py` (Claude/DeepSeek/Ollama; anthropic pinned 0.107; R21
  positive import-guard + ast guard; real to_thread offload; H22 backend secret tests) — `0028`.
  Deps added: `anthropic>=0.107,<1`, `httpx>=0.27,<1`; new `network` marker (env-gated live smokes).
- **P3-6 ✅** `ElevenLabsTTS` (D5, mirror Piper) + cloud-credential preflight + Ollama endpoint
  shape (`config.py`). DA caught a repeat P2-5 bug class (PCM golden tol 1e-3→1e-7) — `0029`.
- **P3-7 ✅** `dj/build.py` boot seam (ranked chains from config; NullDJ floor last; total
  build_tts_engine; `LLMConfig.request_timeout_seconds` + config→ctor timeout threading; H22) — `0030`.
- **P3-8 ✅** producer wiring (`build_dj_context`; every TrackItem decodes; empty patter→template
  + WARNING; R11 backstop intact; run_once back-compat defaults). Senior caught empty-sentinel
  ValidationError bypassing R11 (→ non-empty sentinels) — `0031`.
- **PHASE 3 COMPLETE.** The AI DJ ships: grounded LLM patter (Claude/DeepSeek/Ollama), ranked
  LLM+TTS failover (skip-on-Fatal, total floor), ElevenLabs cloud TTS, boot seam, producer wiring —
  all behind the unchanged Phase-1 Protocols, fakes-only on CI (R21, lazy network imports).
- Gate after P3-8: **566 tests** (3 network smokes + 2 hardware deselected), 98.65% cov,
  ruff/mypy `--strict` clean (38 files). Deps: `anthropic>=0.107,<1`, `httpx>=0.27,<1`.
- README updated (Phase-3 prereqs: env creds, Ollama-on-LAN, spend cap, _MAX_TOKENS, timeouts);
  CI excludes `network` marker; governance refs 0001–0031.
- **Phase-4 carry-forwards (opened during Phase 3):** summed-timeout refill budget (DA); repeated
  fall-through WARNING de-dup (Old Man); the run_once DJ-arg signature should migrate to a Phase-4
  coordinator that owns DjContext assembly (§7-Q4); decoder/TTS *actual*-rate verification (0022).
- **Phase-3 deep-dive ✅ COMPLETE — all 7 agents (`0032`).** No CRITICAL. Fixed 2 HIGH: DA found a
  **zero-frame-segment dead-air hole** (player backstop only fires on a buffer miss → producer now
  backstops a `frames==0` render); Old Man found a `-O`-strippable `assert` in `resolve_persona`
  (→ explicit raise + file-read error wrap). Fixed MEDIUM/LOW: shipped `config.example.json`
  (operator deployability), `max_requests_per_minute` marked reserved/not-enforced, `block_reminder`
  prompt reworded grounded-only, README Ollama-timeout/worst-case-stall/DeepSeek/logging doc fixes,
  `post_json` return type, `_ESPEAK_BASE_WPM` constant. Fact Checker: docs factually sound.
  Gate: **568 tests, 98.56%, ruff/mypy --strict clean (38 files)**.
- **Deferred to Phase 4 (noted, not defects):** `item_kind` redundant Protocol param; raw-exception
  secret-scrub (defense-in-depth); track-tag length cap; worst-case refill budget under outage;
  logging entrypoint; minor coverage-accounting nits.
### Phase 4 — Multi-station (coordinator/supervisor/systemd/real sink/midnight regen) — PLAN ADOPTED (building)
- **Plan Rev 1 drafted** (`docs/plans/phase-4-implementation-plan.md`) + full-seven panel reviewed:
  **5 AYE / 2 NAY → REVISE** (`0033`). Fact Checker verified every seam symbol (no corrections).
- **Adopt-blocking CRITICALs for Rev 2 (full brief in `0033`):** (C1, DA) the "refill budget"
  documents rather than fixes the serial-render-vs-short-patter-cluster **audible backstop-loop** —
  needs a hard config-load invariant (Σ patter timeouts < shortest patter item) and/or pre-render
  the patter run at block entry (converges w/ RPi "stagger patter" + RAM budget); (C2, DA+FieldOp)
  **render-poison crash-loop** globalized by escalation — supervisor must advance past the poison item
  + systemd `StartLimit*`; (RPi) `sounddevice` needs system `libportaudio2` (apt); `WatchdogSec`
  without `sd_notify` bricks the box → drop or wire heartbeat; `After=sound.target`→`network-online`
  +device-retry. **HIGH:** midnight regen-fail isolation + straddle-midnight flow; seek offset-past-
  decoded-frames guard; udev PHYSICAL-PORT-PATH keying; RAM-aware budget; operator log vocabulary +
  StationStatus + first-boot runbook; recent_tracks/item_kind are real churn (correct the framing).
- **Plan Rev 2 ADOPTED 6 AYE / 1 NAY (`0034`).** Folded all of `0033`; the DA's 1-NAY dissent +
  convergent Senior/Old-Man/RPi conditions folded as amendments: (C2) advance-past-poison keyed on
  the producer-tagged **item INDEX** (clock-offset drifts, never trips); (RAM) `_ram_bounded_depth`
  below the worst cluster is a **FAIL-FAST ConfigError** against a **fixed** byte budget (not psutil);
  (C1) **day-roll prewarm** renders the new day's opening cluster during the outgoing day's final item
  (only true cold-start hits the bounded one-cluster backstop residual). `StationStatus` adds
  `airing_backstop` vs `on_air`. Constants set: RAM ≈40% of total 4 GB (no psutil dep), stagger ≈2 s×i.
- **Increment order:** P4-1 sink → P4-2 udev → P4-3 supervisor+status → P4-4 daily → P4-5 station →
  P4-5b item_kind removal → P4-6 coordinator+budget → P4-7 midnight → P4-8 systemd+entrypoint →
  P4-9 housekeeping + Phase-4 deep-dive. Each strict spec-driven TDD (focused-panel TEST review).
- **P4-1 ✅** `audio/sink.py` `SoundDeviceSink` (persistent gapless stream, dedicated executor, xrun-glitch recovery, lifecycle teardown; R20/R21) — `0035`. Gate: 583 tests, 98.51%, ruff/mypy clean; sink.py 97%. Deps: `sounddevice>=0.4,<1` (+libportaudio2 apt note).
- **P4-2 ✅** `UdevAudioDeviceResolver` (port-path keyed, NOT serial; PortAudio↔ALSA bridge; ambiguous→None; enumeration-only-hardware) + `docs/ops/udev-audio.md` — `0036`. DA caught index-vs-port_path indistinguishability + missing hardware smoke. Gate: 597 tests, 98.53%, clean.
- **P4-3 ✅** `supervisor.py` (R7 tier-2: restart-to-known-good, sibling isolation+concurrency, advance-past-poison keyed on item INDEX + bounded skip budget, ceiling→injected on_escalate, multi-pattern secret-scrub) + `status.py` (StationStatus, on_air vs airing_backstop) + `PoisonItemError` — `0037`. DA caught no-skip_item infinite-loop + unbounded-skip starvation + per-index counting; gather-swallows-SystemExit → prod on_escalate must os._exit. Gate: 622 tests, 98.55%, clean.
- **P4-4 ✅** `pipeline/daily.py` (`slice_from_now` PURE + `play_day`: R11 gap, seek-trim first track with offset-past-frames→skip guard, delegates to frozen run_once) + `recent_tracks` grounding (producer-owned deque→build_dj_context) — `0038`. Gate: 632 tests, 98.59%; daily 100%, producer 100%. NOTE: remaining increments authored with prior-panel lessons folded in; P4-9 full-seven deep-dive is the backstop.
- **P4-5 ✅** `station.py` `Station` (the per-station `Supervisable`: load-or-generate today's schedule [R6 corruption/absence→regenerate-and-persist, never crash-loop], anchor [R12], drive `play_day`, await day-roll Event [write-then-signal §E], re-slice; cold-start==restart path §6; `skip_item` poison net; `on_status` push) — `0039`. Fixed the `sleeper=None` placeholder → `sleeper: Sleeper` constructor dep forwarded to run_once. In-band render-poison: producer backstops ANY render exception (CRITICAL log) rather than propagating index-mapped poison (documented §C deviation, **P4-9 must ratify**). Gate: 640 tests, 98.64%; station.py 100%.
- **RESUME POINT: build P4-5b** (item_kind Protocol-param removal) then P4-6 (coordinator).
  deep-dive-validated; gate 568 tests / 98.56% / ruff+mypy clean.)
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
