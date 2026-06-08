# Phase 2 plan review — Local voice (Piper TTS · real decode · loudness)

Full seven-agent panel review of `docs/plans/phase-2-implementation-plan.md` (phase-gate
plan ⇒ full seven, per `docs/process/strict-tdd.md`).

## Rev 1 — 2 AYE / 5 NAY → revise
- **AYE:** Senior Dev, RPi Expert. **NAY:** Old Man, Fact Checker, Devil's Advocate, QA, Field Operator.
- Convergent blockers: `pyloudnorm>=0.1.1,<0.2` **unsatisfiable** (CRITICAL, Fact Checker);
  pyloudnorm short-buffer behavior mis-described (raises `ValueError` vs returns `-inf`);
  Producer wiring left broken (P2-6 changed `Producer.__init__` but not its sole caller
  `run_once`); transition-silence H5 mis-analyzed; short-patter raw passthrough violates
  §10 consistent-levels; subprocess timeout/partial-read/exit logic hidden behind
  `pragma: no cover` (untested in CI); `parse_pcm_f32le` truncation → bare `ValueError` →
  producer death → dead air; ElevenLabs deferral misquoted §21/D5; config-load binary
  preflight would break the binary-free config test suite; many test-strategy gaps
  (gameable loudness round-trip, missing immutability/resample/caplog/golden cases).
- The 9 open questions were ruled on by the panel (see plan §7 Resolutions): f32le; scipy
  `resample_poly`; stdlib `wave` (drop soundfile); pad-then-measure short patter;
  `ge=-40,le=0` loudness bound + WARNING on clamp; mono v1 + one station format; loudness
  mandatory; preflight fail-fast but SEPARATE from `_validate_config`; `normalize_to` via
  `asyncio.to_thread` now.

## Rev 2 — 6 AYE / 1 NAY → ADOPTED
- **AYE:** Old Man, Fact Checker, QA, Field Operator, Senior Dev, RPi Expert.
  **NAY:** Devil's Advocate.
- Re-verified fixes: pin → `pyloudnorm>=0.2.0,<0.3`, `scipy>=1.15,<2`; short-buffer
  behavior corrected; timeouts committed (`decode=120s`, `tts=30s`, config-tunable) and a
  P2-3/P2-5 gate; subprocess exception→`ProviderError` mapping moved to PURE helpers (only
  the literal `subprocess.run` is `pragma: no cover`); speed math in the pure
  `build_piper_argv`; `parse_pcm_f32le` raises `ProviderFatal`; ElevenLabs D5 acknowledged
  + Phase-3 sequencing justified; `preflight_binaries` separated from `_validate_config`;
  non-gameable loudness round-trip (both polarities + direction) + committed PCM golden.
- **DA's lone NAY carried a real CRITICAL** → folded in as binding amendment A1
  (`preflight_binaries` had no caller ⇒ wire it into `load_config(preflight=True)`), plus
  HIGH amendment A2 (short-patter must assert measured-LUFS-to-target, not just "louder";
  correct the gating-bias prose). See the plan's "Rev 2 — Panel disposition & binding
  amendments" section.

## ElevenLabs sequencing (D5)
D5 puts ElevenLabs in v1; this plan **sequences** it to Phase 3 (it is a cloud provider,
meaningless without `dj/failover.py` + ranked providers, which is Phase 3). The adoption
vote **ratifies that sequencing** — it is a phasing decision, not a scope drop.

## Increments (adopted, dependency-ordered)
P2-1 loudness + deps + `le/ge` bound · P2-2 resample · P2-3 FfmpegDecoder · P2-4 typed
provider configs + `binaries.py` + `preflight_binaries` wiring (A1) · P2-5 PiperTTS/EspeakTTS
· P2-6 producer loudness wiring + player format/logging. Each is strict-TDD with a
pre-RED focused-panel test review and a `docs/decisions/00XX` record.
