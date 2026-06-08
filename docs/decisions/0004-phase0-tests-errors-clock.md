# Phase 0 — Increment 1: `errors.py` + `clock.py` (tests-first)

> First increment under the **strict spec-driven TDD** directive
> (`docs/process/strict-tdd.md`): tests authored from spec, **reviewed by the panel
> before implementation**, then implemented to GREEN.

## Process record

1. **Tests authored** from plan §4.1 (`errors.py`) and §4.2 (`clock.py`):
   `tests/errors/test_errors.py`, `tests/clock/test_clock.py`.
2. **Confirmed RED** — both failed with `ModuleNotFoundError` (no implementation).
3. **Panel reviewed the TESTS** (not code). Vote: **7 AYE / 0 NAY → adopted.**
4. **Hardening folded in** from the review (all additive, adopted alongside the
   7-0 vote; provenance noted):
   - Error leaves asserted **distinct and not cross-subclassed** (Senior Dev + DA).
   - `tz()` asserted to return a real `tzinfo` (DA — protocol isinstance is
     presence-only).
   - `now()`/`tz()` **agreement on the default/production path** (DA + RPi).
   - Injected **DST zone** exercised, not only UTC (QA).
   - **Fixed-offset (no-IANA) zone** still works — the headless-Pi case (RPi).
5. **Implemented to GREEN.** `src/pirate_radio/errors.py`, `src/pirate_radio/clock.py`.
   A10 applied: `FixedClock` stores `_tz` at construction (no bare `assert` that
   `-O` would strip).

## Result

`ruff` clean · `ruff format` clean · `mypy` clean (3 files) · **24 passed** ·
coverage **95.83%** (clock.py's 2 uncovered lines are the `Protocol` `...` stubs —
intentionally not `pragma`'d, per QA's discipline; still above the 80% floor).

## Vote — Round 1 (2026-06-07)

| Agent | Vote | Note |
|---|---|---|
| Senior Dev | AYE | Contract pinned; asked for sibling-distinctness (folded in). |
| Old Man | AYE | Right-sized, no incidental-detail pinning, refactor-safe. |
| Raspberry Pi Expert | AYE | Zone-independent; asked for no-IANA + now/tz consistency (folded in). |
| Fact Checker | AYE | Every assertion empirically matches Python 3.12 semantics. |
| Devil's Advocate | AYE | Found the default-path now/tz + protocol-presence + leaf-distinctness gaps (folded in). |
| QA Engineer | AYE | Faithful, non-tautological; asked for a DST-zone assertion (folded in). |
| Field Operator | AYE | Message+path survival and tz-aware/injected-zone seam correctly specified. |

**Next increment:** `persistence.py` (R5/R6/R17) — tests first, per the same loop.
Requires adding `pydantic` to `pyproject.toml`.
