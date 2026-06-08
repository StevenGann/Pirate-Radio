# P3-6 — `ElevenLabsTTS` (D5) + cloud-credential preflight + Ollama endpoint shape

Strict spec-driven TDD: tests authored from the adopted Phase-3 plan §4.3 / §4.7 / §5 → confirmed
RED → full focused panel (QA + Senior Dev + DA) reviewed the TESTS → folded the must-fixes →
implemented GREEN → gate → commit.

## Panel review of the tests (focused: QA + Senior Dev + Devil's Advocate)

**Tally: QA NAY, Senior Dev AYE, DA NAY → 2 NAY, REVISE.** Both NAYs were convergent
test-completeness gaps (no implementation disagreement); all folded, then re-confirmed.

The decisive catch — **the DA found a repeat of the P2-5 bug class**: `test_pcm_s16le_golden` used
tolerance `1e-3`, which is ~66× looser than the `1.5e-5` error a wrong `/32767` divisor produces
(P2-5 tightened the Piper golden to `1e-7` for exactly this reason). Folded fixes:

- **PCM golden `1e-3 → 1e-7`** + a **multi-frame asymmetric golden** (`<hh` 16384,-8192 →
  0.5/-0.25, `frames == 2`) pinning byte-order + reshape (DA CRITICAL).
- **Resample test no longer gameable** — asserts `frames == 4800 (±1)` AND `samples.max() > 0`
  (not just `sample_rate == 48000`, which silence/wrong-length/no-resample would all pass) (DA).
- **429 → Quota** (QA — a hard §3.4/§6 gate row that was missing; a 429→Fatal impl now fails) +
  **5xx → Unavailable** (QA recommended).
- **Ollama endpoint: hostless `http://` rejected + `https://host` accepted** — a `startswith`-only
  impl that accepts scheme-only garbage or rejects all https now fails (DA). Implemented via
  `urlparse` (scheme ∈ {http,https} AND non-empty netloc), not a prefix check.
- **Missing-provider-block preflight** — an `elevenlabs` station with no `tts_providers.elevenlabs`
  block is now pinned as a clean boot `ConfigError`, not a `provider()` crash / die-at-first-synth
  (DA — the standing "false floor" concern).
- **Transport-path H22** — the api_key is absent from the error on the connect-error path too (DA).

Senior Dev confirmed the architecture: `ElevenLabsTTS` imports the HTTP mappers from `dj/_http`
(NOT `dj/text` — no sibling coupling), mirrors the PiperTTS pure-build/parse/error-map/one-lazy-
network-line idiom, the cloud preflight is a separate `_check_tts_env_vars_present` sibling of the
LLM check, the Ollama check is best as a `field_validator` (intrinsic shape), and there is no
config↔dj import cycle (arrow stays dj→config).

## Implementation

- `dj/tts.py` (extend): `build_elevenlabs_request` (PURE) + `pcm_s16le_to_buffer` (PURE,
  `/32768`, empty/misaligned→Fatal) + `ElevenLabsTTS` (lazy httpx in `_fetch`; the only
  `pragma: no cover` = the network lines; `map_http_status`/`map_httpx_exception` from `dj/_http`;
  empty-text→station-rate silence; `to_rate` to the station rate, H5).
- `config.py`: `OllamaLLMConfig._check_endpoint` `field_validator` (urlparse scheme+host);
  `_check_tts_env_vars_present` (elevenlabs `api_key_env` set+non-empty at boot, A1 blank rejected;
  missing-block → clean ConfigError) wired into `_validate_config`.

## Gate

ruff + ruff-format + mypy `--strict` clean (37 files); **532 tests** (+25), 98.68% coverage;
`dj/tts.py` 100%, `config.py` 99% (the 2 uncovered lines pre-date P3-6); ElevenLabs network lines
pragma'd; live ElevenLabs smoke deferred to the network-marked set (run on deployment).

## Next

P3-7: `dj/build.py` — construct the ranked Text/TTS chains from config (the boot seam, H22;
NullDJ floor last; total `build_tts_engine`; config→constructor timeout threading), tests-first.
