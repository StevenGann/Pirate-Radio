# 0023 — Phase 3 plan (AI DJ: grounded LLM patter · ranked failover · ElevenLabs) — ADOPTED

Strict spec-driven TDD governs Phase 3 (PiRate standing directive). The implementation plan
(`docs/plans/phase-3-implementation-plan.md`) was authored from spec, reviewed by the full
seven-agent panel, **revised once (Rev 1 → Rev 2)** under the ≥2-NAY charter, and **adopted
unanimously on the re-vote**.

## Vote history

**Rev 1 — REVISE** (≥2 NAY): Senior Dev AYE/cond (C1/C2/C3), Old Man NAY/cond, RPi Expert AYE,
Fact Checker NAY, Devil's Advocate NAY, QA NAY, Field Operator AYE/cond.

**Rev 2 — ADOPTED, 7 AYE / 0 NAY** (2026-06-08).

## Convergent must-fixes folded into Rev 2

- **CRITICAL (DA):** intro/outro `TrackItem` in §4.6 `_render` could play patter *instead of* the
  song. Fixed: Phase 3 **decodes every `TrackItem`**; only the three §20-named pure-patter items
  (`station_id`, `block_transition`, `block_reminder`) go through DJ→TTS. The track+glued-intro/outro
  *segment assembly* is deferred to Phase 4 (§7-Q8). Regression test:
  `test_producer_intro_trackitem_still_decodes_the_song` (decoder called, DJ never called).
- **CRITICAL (Senior/Old Man):** no cross-sibling `tts → text` import. `map_http_status` /
  `map_httpx_exception` + the shared `post_json` moved to a new leaf module `dj/_http.py`; both
  `dj/text.py` and `dj/tts.py` import the mappers from there. No import cycle.
- **CRITICAL (Senior/Old Man):** `build_tts_engine` made total — exhaustive `isinstance` +
  `else: raise ConfigError`, empty-chain guard, and the ElevenLabs-provider check is an explicit
  `raise ConfigError`, not a `-O`-strippable `assert`.
- **HIGH (DA/QA):** P3-8 keeps existing pipeline call sites valid — new `Producer`/`run_once` DJ
  args are **defaulted** (None → `RankedTextGenerator([NullDJ()])`); `test_run_once_old_signature_still_works`.
- **HIGH (DA):** the failover floor is now **total** — `_ranked_call` catches every exception per
  provider and re-types non-`ProviderError` to `ProviderUnavailable`, so a provider bug (e.g. a bare
  `ValueError`) can never escape the chain past the producer's `except ProviderError`.
- **HIGH (DA/QA):** the R23-offload / R21-no-import tests are no longer theater — real proof via
  `threading.get_ident() != main` inside the blocking call + a `sys.modules` import-guard + a
  top-level-import grep guard (H28).
- **HIGH (Fact Checker):** `anthropic` pin held as a gated `PLACEHOLDER` (current verified-live
  `0.107.1`; resolve at the start of P3-5, blocks RED); ElevenLabs `401` documented dual-meaning
  (auth OR quota — both skip to the Piper floor under skip-on-Fatal); DeepSeek URL pinned
  `https://api.deepseek.com` + `/chat/completions` (no `/v1/`), Bearer auth. Schedule field names
  verified against `schedule/models.py`.
- **QA:** twelve named-test gaps filled across §5 (H22 caplog-no-secret, ElevenLabs per-status map,
  RankedTTSEngine Fatal-skip/all-fail/caplog, `build_dj_context` for every emitted kind,
  `map_claude_exception` timeout/5xx/unknown, Ollama shell, order-spy proving #2 never called,
  `is_sparse` partials, per-station `llm` override, H26 newline-injection, the two filled producer stubs).
- **QA/H26:** prompt-injection hardening (`_sanitize`) is in the build path — interpolated tag/persona
  values are newline-/control-char-stripped so a tag cannot inject prompt lines.
- **Field Op:** producer logs a WARNING on the NullDJ/empty-patter degrade; timeouts config-tunable
  (H23); README Phase-3 prereqs (Ollama-on-LAN, spend cap, `_MAX_TOKENS`); `factoid` documented as a
  dormant (unscheduled) kind in Phase 3.

## Open-question rulings ratified (§7, now closed)

Q1 generic core + two adapters · Q2 **skip-on-Fatal** (+ total floor; all-Fatal→`ProviderUnavailable`)
· Q3 narrow to `DjContext | None` · Q4 assemble in producer, grid tagline/description + history → Phase 4
· Q5 rate-limit → Phase 4 · Q6 no in-place retry · Q7 ElevenLabs PCM whole-clip · Q8 intro/outro segment
assembly → Phase 4 (decode every TrackItem in Phase 3) · Q9 real `get_ident` offload + import-guard.

## Non-blocking impl-time notes (folded inline)

- `dj/build.py` must thread a **config-sourced** timeout into each backend (P3-7) — defaults are bounded.
- §3.1 wheel prose corrected: `httpx` is pure-Python; `anthropic` pulls native `jiter`/`pydantic-core`,
  clean on arm64 cp311/cp312 only via prebuilt wheels (another reason 32-bit Pi OS is unsupported).
- `test_producer_dj_and_tts_all_fail_then_backstop` asserts the backstop segment actually reaches the
  buffer, not merely that `run()` didn't raise.

## Phase-4 carry-forwards opened here

- **Summed-timeout refill budget (DA):** worst-case serial LLM-chain + TTS-chain ≈ 100s of hung-not-fast
  time per item; liveness-safe (backstop), but the Phase-4 coordinator must state/bound a refill budget.
- **WARNING de-dup (Old Man):** a persistently-broken primary logs one fall-through WARNING per item;
  Phase 4 should de-dupe / periodically summarize.

## Next

Implement P3-1 (`dj/context.py`) tests-first per the adopted §6 increment order.
