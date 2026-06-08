# P3-7 — `dj/build.py` (the boot seam: construct the ranked chains from config, H22)

Strict spec-driven TDD: tests authored from the adopted Phase-3 plan §4.5 / §6 → confirmed RED →
full focused panel (QA + Senior Dev + DA) reviewed the TESTS → folded the must-fixes → implemented
GREEN → gate → commit.

## Panel review of the tests (focused: QA + Senior Dev + Devil's Advocate)

**Tally: QA AYE, Senior Dev AYE, DA NAY → 1 NAY (adopts); the DA's substantive findings folded.**

- **H22 secret-VALUE test was missing (DA HIGH).** The `_secret` tests only proved the var name;
  the module's whole reason to exist (H22) was unverified. Added
  `test_no_secret_value_in_logs_after_failed_patter` — builds a chain with a sentinel
  `ANTHROPIC_API_KEY="SUPERSECRET"`, drives a failed patter through failover to the NullDJ floor,
  and asserts the value never appears in any log record.
- **`LLMConfig.request_timeout_seconds` (DA CRITICAL / QA / Senior).** The Rev-2 P3-7 note demanded
  config→constructor timeout threading; the §4.5 code block omitted it. Added the field (default
  20.0, gt=0) and threaded it UNIFORMLY into all three LLM backends; threaded the existing
  `config.tts_timeout_seconds` into all three TTS backends. Pinned by `_timeout`-value tests for
  Claude, Ollama, and ElevenLabs (distinct non-default values kill a hardcode).
- **NullDJ-exactly-once + empty-providers floor (DA).** Added `sum(isinstance(p, NullDJ)) == 1` and
  a `model_construct(providers=())` test proving an empty LLM list still yields a usable
  NullDJ-only chain (the text floor can never be absent, D2).
- **`build_text_generator` drops `persona_resolved` (QA/Senior).** Persona is per-`DjContext`, not
  per-provider (§4.5 note) — the generator takes only `llm`; persona is resolved separately by
  `resolve_persona` and threaded by the producer (P3-8).

Senior Dev confirmed: `build.py` is the single backend→class mapping site (failover/text/tts stay
agnostic); no import cycle (build is a pure sink; tts imported lazily to keep the text path light);
`model_construct` is the right way to exercise the CRITICAL totality guards (an unreachable-by-
construction branch the design deems CRITICAL must be executed + asserted, not `# pragma`'d);
private-attr assertions (`_providers`, `_timeout`) are necessary white-box contract pins.

## Implementation

`dj/build.py`: `_secret` (env by name, A1 blank-reject, names the var not the value);
`resolve_station_llm` (station.llm or config.llm, §12); `resolve_persona` (inline or
`schedule_dir / dj_personality_file`, matching the boot check); `build_text_generator` (Claude→
DeepSeek→Ollama→NullDJ floor, uniform timeout); `build_tts_engine` (Piper/Espeak/ElevenLabs, total
— exhaustive `else: raise ConfigError` + empty-chain guard + explicit ElevenLabs-provider raise,
timeout threaded). `config.py`: new `LLMConfig.request_timeout_seconds`.

## Gate

ruff + ruff-format + mypy `--strict` clean (38 files); **551 tests** (+19), 98.63% coverage;
`dj/build.py` 97% (the 1 uncovered line is the defensive ElevenLabs-provider-type raise —
unreachable via validated config, kept as the explicit-raise guard, not `assert`).

## Next

P3-8 (the Phase-3 capstone): producer wiring — `build_dj_context` + ranked text→TTS + the floors
(every TrackItem decoded; pure-patter → template fallback + WARNING; R11 backstop intact) +
`run_once` back-compat defaults, tests-first.
