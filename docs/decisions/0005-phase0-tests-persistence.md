# Phase 0 — Increment 2: `persistence.py` (tests-first)

> Atomic durable JSON over Pydantic models (R5 / R6 / R17), built under the
> strict spec-driven TDD process. **Notable: the tests needed a Rev 2** — the
> process caught a gap before any implementation existed.

## Process record

1. **Tests authored** from plan §4.3 / §6.3 with QA's A5a crash-injection
   hardening: `tests/persistence/test_persistence.py`. Added `pydantic` dep.
2. **Confirmed RED** (`ModuleNotFoundError`).
3. **Panel reviewed the TESTS — Round 1: 5 AYE / 2 NAY → revise.**
   QA and the Devil's Advocate independently found the same hole: the **parent-dir
   fsync (`_fsync_dir`) was never proven to run** (because the fsync-crash test
   raised on the first/temp fsync, the dir-fsync path was never reached). An
   implementation that omits the dir-fsync — the load-bearing R5 power-loss line —
   would have passed 100% green.
4. **Tests revised (Rev 2)** — folded in the blocking fix + all additive hardening:
   - `test_parent_directory_is_fsynced_on_success` — spies `os.fsync`, asserts a
     **directory fd** is synced (`stat.S_ISDIR`); a dir-fsync-omitting impl now
     fails RED. *(QA + DA, BLOCKING)*
   - `test_crash_after_replace_before_dir_fsync_keeps_committed_value` — pins
     post-replace ordering and committed-value-survives semantics. *(QA #2)*
   - keyword-only `schema_version` *(Senior Dev)*; `Path`/`datetime` round-trip
     *(Senior Dev)*; live-missing/`.bak` recovery *(Field Op)*; standalone-`.bak`
     prior generation *(Old Man + DA GAP C)*.
5. **Re-vote — Round 2: 7 AYE / 0 NAY → adopted.** (QA and DA confirmed their
   blocking item resolved; the five prior AYEs stood — additive changes only.)
6. **Implemented to GREEN.** `src/pirate_radio/persistence.py`
   (temp → fsync → `os.replace` → dir-fsync; copy-then-replace `.bak`;
   recovery; `schema_version` envelope; A7 caveats in the docstring).

## Result

`ruff` clean · `mypy` clean (4 files) · **41 passed** · coverage **98.44%**
(persistence.py 100%). New dep: `pydantic>=2.7,<3`. Also added
`[tool.ruff.lint.isort] known-first-party = ["pirate_radio"]`.

## Why this increment matters

It is the clearest demonstration so far of the strict-TDD value: **a non-durable
implementation gap was caught and fenced in the tests before a line of
implementation was written.** Had the implementation been written first, the
missing parent-dir fsync would likely have shipped behind green tests.

**Next increment:** `catalog/` (models, mutagen metadata, scanner) — tests first.
Needs `mutagen` added to `pyproject.toml`.
