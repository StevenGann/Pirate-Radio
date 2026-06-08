# 0032 — Phase-3 full-team deep-dive (code quality + documentation) — overnight-mandate finale

The standing seven-agent panel deep-dived the **shipped** Phase-3 code and docs (not a test review).
**No CRITICAL.** One HIGH from the Devil's Advocate (a genuine dead-air hole the increment reviews
never tested) and one HIGH from the Old Man (a `-O`-strippable assert), plus high-value MEDIUM/LOW
operability and quality items. All HIGH + the cheap high-value items were remediated; the rest are
recorded as Phase-4 cleanups.

## Verdicts

- **Senior Dev** — ship-quality, no CRITICAL/HIGH; MEDIUM: vestigial `item_kind` param, `block_reminder`
  prompt contradiction; LOWs.
- **Old Man** — HIGH: bare `assert` in `resolve_persona` strips under `-O`; MEDIUM: persona file read
  unwrapped; LOWs. Confirmed the `_ranked_call` catch-all is adequately *loud* (logs the real type).
- **RPi Expert** — Pi-deployable; wheels verified clean on arm64 cp311/cp312; MEDIUM: worst-case
  summed-timeout stall under outage; LOW: README Ollama-timeout figure inaccurate.
- **Fact Checker** — documentation factually sound; every number/pin/field/URL verified; no corrections.
- **Devil's Advocate** — **HIGH: a present-but-zero-frame segment airs 0 s of silence** — the player
  backstop fires only on a buffer *miss*, never on `frames==0`, and a degenerate valid WAV reaches
  that state; LOWs (raw-exception interpolation, uncapped tag length).
- **QA Engineer** — test suite sound; coverage honest (pragmas conservative, mutation-proven); marker
  discipline + isolation clean; two cosmetic coverage-accounting nits.
- **Field Operator** — runtime field-safe + secret-clean, but **can't deploy from docs alone** (no
  complete example config); `max_requests_per_minute` is a dead knob; logging needs the Phase-4 entrypoint.

## Remediated (this round, strict-TDD where behavior changed)

- **HIGH (DA) zero-frame dead-air:** `Producer.run` now treats a `frames == 0` render as a backstop
  trigger (raises `ProviderUnavailable` → the existing R11 catch → backstop + WARNING). Test:
  `test_zero_frame_render_substitutes_backstop`.
- **HIGH (Old Man) `-O` assert:** `resolve_persona` replaces `assert dj_personality_file is not None`
  with an explicit `raise ConfigError`, and wraps the file read in `try/except (OSError,
  UnicodeDecodeError) → ConfigError` naming the path. Test:
  `test_resolve_persona_unreadable_file_raises_configerror`.
- **MEDIUM (Field Op) deployability:** ship `config.example.json` — a complete, copy-able pure-JSON
  station config (validated at model level); README points to it.
- **MEDIUM (Field Op) dead knob:** `LLMConfig.max_requests_per_minute` documented RESERVED/NOT-ENFORCED
  (§7-Q5) in config + README.
- **MEDIUM (Senior) prompt contradiction:** `block_reminder` task reworded to grounded-only (dropped
  "what's coming up" — no next-block grounding exists for it).
- **MEDIUM (RPi) doc fixes:** README corrected to "20 s for every LLM backend (incl. Ollama), 30 s TTS";
  added the worst-case summed-timeout note + local-first ordering guidance; DeepSeek named as metered;
  logging-needs-Phase-4 note.
- **LOW polish:** `post_json -> dict[str, object]`; `_ESPEAK_BASE_WPM = 175` constant.

## Deferred to Phase 4 (noted, not defects)

- **`item_kind` redundant Protocol param** (Senior MEDIUM) — `patter(item_kind, context)` duplicates
  `context.kind`; real backends ignore it. Removal touches the Protocol + all backends + fakes +
  producer; deferred to avoid churn on the proven seam. Harmless today.
- **Raw-exception interpolation could echo a secret IF an underlying exception ever embedded it**
  (DA LOW) — real httpx/anthropic exceptions don't carry headers; defense-in-depth scrub deferred.
- **Uncapped track-tag length** (DA LOW, H27/H30) — single-line, not injection; output bounded by
  `_MAX_TOKENS`; a per-tag input cap is deferred.
- **Worst-case refill budget under outage** (RPi/DA, already a plan carry-forward) — the Phase-4
  coordinator must state/bound it; README now documents the worst case + the local-first mitigation.
- **Logging setup** (Field Op) — belongs to the Phase-4 daemon entrypoint (none exists yet).
- LOW coverage-accounting nits (QA): `_http` pragmas are conservative (mutation-proven); `build.py:121`
  defensive guard uncovered — both cosmetic at 99%.

## Gate

ruff + ruff-format + mypy `--strict` clean (38 files); **568 tests** (+2), 98.56% coverage.

## Phase 3 — COMPLETE and deep-dive-validated. Next: Phase 4 (coordinator/supervisor/systemd/real
sink/midnight regen) needs a plan (planner + full-seven panel).
