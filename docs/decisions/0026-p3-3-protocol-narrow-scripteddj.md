# P3-3 — Protocol narrowing (`patter(kind, DjContext | None)`) + `ScriptedDJ` fake

Strict spec-driven TDD: tests authored from the adopted Phase-3 plan §3.3 / §6 P3-3 → confirmed
RED → focused panel reviewed the TESTS → folded the must-fixes → implemented GREEN → gate (incl.
mypy `--strict` on the whole package — the actual narrowing gate) → commit. Ratifies §7-Q3
(`DjContext | None`), recorded in `0023`.

## Panel review of the tests (focused: QA + Devil's Advocate — proportionate for a mechanical increment)

**Tally: QA AYE, DA NAY → 1 NAY (adopts under the charter); the DA's three unpinned-contract
holes on `ScriptedDJ` were folded in because that fake is *used* to assert failover/producer
behavior in P3-4/P3-8, so its contract must be pinned now.**

DA's blocking gaps (all folded):
1. **`calls` context-capture unpinned** — the old order-spy test discarded the tuple's second
   element (`[k for k, _ in dj.calls]`), so the spy's payload shape was unspecified. Replaced with
   `test_scripteddj_records_kind_and_context_in_order` asserting the full `(kind, context)` tuples.
2. **Record-vs-raise ordering undefined** — added `test_scripteddj_records_the_attempt_before_raising`
   pinning **record-then-raise** (a failed provider still appears in the spy, so failover diagnostics
   see every attempt).
3. **text+error precedence unpinned** — added `test_scripteddj_error_wins_over_text` and
   `test_scripteddj_error_wins_over_by_kind` (error dominates, faithfully folding `FailingDJ`).

QA's GREEN-side condition (the narrowing is a static change only — mypy `--strict` is the real
gate, not the runtime tests) was honored: `mypy src/pirate_radio` is clean across all 34 files,
confirming no `patter` caller breaks under `object | None` → `DjContext | None`.

## Implementation

- `dj/protocols.py`: `TextGenerator.patter(item_kind, context: DjContext | None)` (narrowed; docstring
  updated). `runtime_checkable` unaffected (checks names).
- `dj/fakes.py`: `NullDJ.patter` annotation → `DjContext | None = None` (behavior unchanged); new
  `ScriptedDJ(text=…/by_kind=…/error=…)` — returns canned patter (per-kind override → default) or
  raises the seeded error (error wins), recording every `(kind, context)` attempt before raising.

## Gate

ruff + ruff-format + mypy `--strict` clean (34 files); **433 tests** (+11 new), 98.85% coverage.

## Next

P3-4: `dj/failover.py` — `_ranked_call` generic core + `RankedTextGenerator`/`RankedTTSEngine`
adapters (R15/§9.3 skip-on-Fatal, total floor), tests-first.
