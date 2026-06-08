# Strict Spec-Driven TDD — Standing Process

> **Directive (2026-06-07):** Every new feature or change is implemented as
> **tests first**, the tests are **reviewed by the panel before any implementation
> exists**, and the implementation is written only to satisfy the reviewed tests.
> The tests are the executable contract; the code is graded against them.

## Why

- Tests written from the **spec** (not from the code) keep the implementation from
  drifting from intent, and prevent the code being "graded by its own author."
- Reviewing tests **before** code catches missing cases, wrong assertions, and
  spec misreadings while they are cheapest to fix.
- A reviewed, adopted test file is a precise, unambiguous brief for implementation.

## The loop (per unit of work)

1. **Author tests from the spec.** Translate the relevant design-doc / plan
   section into test files under `tests/<module>/test_*.py`. No implementation yet.
2. **Confirm RED.** Run the tests; they must fail/err (module not implemented).
   A test that passes before implementation is suspect — fix it.
3. **Panel review of the TESTS.** Brief the seven agents to review the tests, not
   code: Are they faithful to the spec? Complete (all rules, edge cases, error
   paths)? Correct assertions (no tautologies, no coverage-gaming)? Then run the
   charter vote (**≤ 1 NAY → adopted; ≥ 2 NAY → revise tests, re-vote**).
4. **Implement to GREEN.** Write the minimal implementation that satisfies the
   adopted tests. The tests do not change to fit the code; the code changes to fit
   the tests (a test only changes if review later proves it wrong).
5. **Refactor** with the green suite as the safety net. Keep the 80% floor honest.

## Notes

- This sits **on top of** the standing TDD rules (RED→GREEN→REFACTOR, 80% floor,
  `@pytest.mark.hardware` exclusion). The new constraint is the **pre-implementation
  team review of the tests**.
- The QA Engineer owns test-quality enforcement (no tautologies, `caplog` on log
  paths, real fixtures over mocks, crash-injection where durability is claimed —
  see the Phase 0 amendments A5).
- Applies to bug fixes too: a bug fix starts with a failing test that reproduces
  the bug, reviewed, then the fix.
- **Panel size.** Plans, phase-gates, and the final deep-dive use the **full seven**.
  Routine per-increment test reviews may use a **focused panel** — QA + Senior Dev +
  Devil's Advocate (the highest-signal reviewers for test quality) — to keep
  throughput up; the increment's commit/BUILD-LOG records which panel reviewed it.
  Any agent may still be pulled in when an increment touches their lane.
