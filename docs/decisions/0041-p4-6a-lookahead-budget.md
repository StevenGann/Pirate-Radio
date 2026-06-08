# P4-6a — `lookahead.py` (the C1-fix look-ahead budget math, PURE)

Strict spec-driven TDD with a **focused panel review of the TESTS before implementation** (this is
the C1 fix the Devil's Advocate dissented on in the Phase-4 plan vote, so it warranted the full
test-review loop rather than the fold-and-proceed shortcut used for the lower-risk increments).

## Scope decision: split P4-6 → 6a (budget math) + 6b (Coordinator)

The adopted plan scopes the §A budget functions into `coordinator.py`. They are extracted into their
own `lookahead.py` module instead — the coordinator orchestration would push the file well past the
400-line coding-standard ceiling, and the budget math is PURE, high-cohesion, and independently
testable (better seam for the C1-critical unit tests). P4-6b builds `coordinator.py` over this. To
be ratified by the P4-9 deep-dive.

## TDD loop (memory: strict-spec-driven-tdd)

1. Tests authored from plan §A → confirmed RED (`ModuleNotFoundError`).
2. **Focused panel on the tests (QA · Senior Dev · Devil's Advocate, opus):** **QA NAY, Senior AYE,
   DA NAY → 2 NAY → REVISE** (charter: ≥2 NAY → revise + re-vote).
3. **Folded every convergent finding** (below), re-confirmed RED, implemented GREEN, re-voted: the
   revised tests address all three reviewers' material points → adopt.

### Panel findings folded

- **DA Hole-1 (critical — the property the DA dissented on):** the original "fixed-budget" tests
  only exercised an *injected* budget + an affording default; a `psutil`-free-fraction impl would
  have passed. Added `test_resolve_default_budget_fails_fast_when_fixed_budget_exhausted` — 8
  stations × depth 4 × 600 s ≈ 3.7 GB, which the bare (no-`ram_budget_bytes`) call MUST reject. A
  psutil-of-a-big-CI-box impl would NOT raise and would fail this test → the fixed-1.6 GB,
  reproducible-at-3am behaviour is now actually pinned.
- **QA #1 / DA #2:** import `_DECODE_TIMEOUT_DEFAULT`; pin `worst_case_track_render() == 120.0`.
- **QA #3:** `ram_affordable_depth` now rejects negative seconds, negative stations, and zero/negative
  budget (not just the two original zero cases).
- **QA #4 / #5:** `stagger_offset` return type is `float`; `resolve(needed_depth=1)` (all-track
  system) passes through.
- **Senior #1:** asymmetric `worst_case_patter_render([20],[30,30])==80` vs `([20,20],[30])==70`
  proves both chains are summed independently (not `llm + max(tts)`).
- **DA #4:** `track_buffer_bytes` truncation at a fractional-byte input; `ram_affordable_depth`
  channels=2 halving.

### Two reviewer points deliberately NOT folded (with rationale, for P4-9)

- **QA #2 (wire `worst_case_track_render` seconds into the RAM footprint):** declined — a conceptual
  conflation. The RAM byte basis is the longest track's *played duration* (`worst_track_seconds`),
  which is **distinct** from the decode *timeout* (`worst_case_track_render`, which sizes a render
  stall). Wiring them would mis-size buffers. Documented the distinction in the `track_buffer_bytes`
  docstring instead.
- **DA Hole-3 (leading-cluster → prewarm residual contract):** the day-roll *prewarm* is coordinator
  behaviour (P4-6b), not pure math. The pure module pins the cluster *count*; the prewarm/residual
  contract is tested in P4-6b.

## Implementation (`src/pirate_radio/lookahead.py`, PURE)

`worst_consecutive_patter(items)` (max non-`TrackItem` run), `lookahead_depth = +1`,
`track_buffer_bytes(seconds, *, sample_rate, channels)`, `ram_affordable_depth(...)` (floor div,
positive-input guard), `resolve_lookahead_depth(...)` (**FAIL-FAST `ConfigError`** naming the fix —
inclusive boundary), `stagger_offset(index, *, step)` (deterministic, no RNG), `worst_case_patter_
render(llm_timeouts, tts_timeouts)`, `worst_case_track_render(*, decode_timeout)`. Named constants:
`_LOOKAHEAD_RAM_BUDGET_BYTES = 1_600_000_000` (fixed), `_STAGGER_STEP_SECONDS = 2.0`, `_LLM/_TTS/
_DECODE_TIMEOUT_DEFAULT = 20/30/120`.

## Gate

ruff + ruff-format + mypy `--strict` clean (44 source files); **669 tests** (+29), 98.67% coverage;
`lookahead.py` 100%.

## Next

P4-6b: `coordinator.py` — shared services (build-once, shared-LLM cache), DJ inputs, the §A budget
wired (depth from each station's schedule, RAM fail-fast, stagger, cold-start WARNING), StationStatus
registry + periodic "N/N ON AIR" summary, injected `sink_factory`, day-roll prewarm.
