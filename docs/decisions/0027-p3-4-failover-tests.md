# P3-4 — `dj/failover.py` (ranked provider failover — R15/§9.3, the phase crux)

Strict spec-driven TDD: tests authored from the adopted Phase-3 plan §4.4 / §5 / §6 → confirmed
RED → full focused panel (QA + Senior Dev + DA) reviewed the TESTS → folded the convergent adds →
implemented GREEN → gate (incl. mypy `--strict`) → commit. This is the load-bearing §9.3
"never dead air" floor.

## Panel review of the tests (focused: QA + Senior Dev + Devil's Advocate)

**Tally: QA AYE, Senior Dev AYE, DA AYE → 3 AYE, ADOPTED.** Two convergent improvements folded
in (cheap, strengthen the crux); one Senior-Dev required follow-through honored as a gate.

- **DA gap — TTS-side laziness unpinned.** The text chain had an order-spy proving provider #2 is
  never called, but the TTS chain did not (an eager TTS impl could call every engine and ship
  green). Added a `_SpyTTS` call-recorder + `test_ranked_tts_order_spy_second_never_called`.
- **Senior Dev recommendation — pin "per-skip".** The single-skip WARNING test proved "≥1 warning",
  not "one per skip". Added `test_failover_logs_exactly_one_warning_per_skip` (two failures →
  exactly two WARNING records).
- **Senior Dev required (non-code) — the `TypeVar[T]` (str/AudioBuffer) contract can't be pinned by
  runtime tests; mypy is the gate.** Honored: `mypy src/pirate_radio` clean across 35 files.

Panel-confirmed the tests kill every dangerous wrong impl: `except ProviderError`-only (fails the
non-ProviderError-contained tests), abort-on-Fatal (fails the three Fatal-skip tests),
re-raise-last-Fatal-on-exhaustion (fails all-Fatal→Unavailable), eager/non-lazy (fails the order
spies), and — DA's critical catch — **falsy-return-is-failure** (`test_nulldj_floor_yields_empty_not_raise`
pins that `""` is a stopping SUCCESS, so the NullDJ floor degrades to no-patter rather than
exhausting the chain).

## Implementation

`dj/failover.py`: `_ranked_call(providers, call, *, op)` — the generic core; tries each provider,
**catches every exception** (re-typing non-`ProviderError` → `ProviderUnavailable`, the total floor),
logs a per-skip WARNING, and raises `ProviderUnavailable` on exhaustion (so the producer's R11
backstop fires) — Fatal and retryable alike skip (skip-on-Fatal, §7-Q2). `RankedTextGenerator` /
`RankedTTSEngine` are the two thin Protocol adapters injecting `p.patter(...)` / `p.synthesize(...)`.
`AudioBuffer`/`DjContext` imports are under `TYPE_CHECKING` (annotations only — no import cycle, no
runtime cost).

## Gate

ruff + ruff-format + mypy `--strict` clean (35 files); **454 tests** (+21 new), 98.69% coverage;
`dj/failover.py` 92% (only the `TYPE_CHECKING` guard uncovered — above the 90% real-logic floor).

## Next

P3-5: `dj/_http.py` (mappers + `post_json`) + `dj/text.py` (Claude/DeepSeek/Ollama) — **first task:
resolve the `anthropic` pin against PyPI/docs** (the `PLACEHOLDER` blocks RED — Fact-Checker gate).
