# P5-2 — `tagging/selection.py` (PURE tag selection — the corruption-safety heart)

Strict spec-driven TDD with a **focused-panel test review** (QA · Senior · DA) before implementation,
because this is the H-T2 corruption gate (it decides what gets written to irreplaceable music files).

## TDD loop

Tests authored from the plan → confirmed RED → **focused panel: QA NAY, Senior AYE, DA NAY → 2 NAY →
revised** → re-confirmed RED → implemented GREEN. The panel's decisive finding (DA, QA-adjacent): the
two-function split (`best_match` + `merge_tags`) left the below-floor no-op to *orchestrator
discipline* — `merge_tags` ignores score, so "a below-confidence match writes nothing even with
perfect metadata" was not pinned at the unit.

### Folded

- **`choose_best` is the authoritative gate** (the plan's named function): composes
  `best_match` + `merge_tags`; below-floor / empty matches → a NO-OP `TagPlan`, even with a perfect
  recording. The corruption invariant is now a property of selection, not orchestrator ordering.
  Tests: below-floor + perfect → no-op; empty → no-op; above-floor → merge; force threaded.
- **force+fill matrix** (QA/DA): `force` must STILL fill gaps, not only overwrite present.
- **per-field never-erase** for album AND year, in force mode (DA).
- **blank CANDIDATE refused** (not just blank existing) — whitespace/empty candidate is "no value",
  never written, fill or force (DA/Senior).
- **determinism** (DA): `best_match` proven input-order-independent over all permutations.
- explicit `min_score` kwarg honored; floor+tie interaction; `force`+equal-value → no-op.

## Implementation

- `best_match(matches, *, min_score=_MIN_ACOUSTID_SCORE)` — `min((-score, id))` so highest score wins,
  ties broken by lexicographically lowest MBID (deterministic, order-independent); `None` if empty or
  sub-floor.
- `merge_tags(recording, existing, *, path, force)` — per field, take the candidate only if present
  (`_present`: non-None, non-blank for text) AND (`force` OR existing missing) AND it differs; returns
  a `TagPlan` of only the changed fields (via `model_validate`). Never erases, never blanks, never
  churns an equal value.
- `choose_best(...)` — re-checks the floor → no-op `TagPlan` or `merge_tags`.
- `_MIN_ACOUSTID_SCORE = 0.85` (named, conservative — a wrong fill is worse than no fill, §9.3).

## Gate

ruff + ruff-format + mypy `--strict` clean (51 source files); **745 tests** (+25), 97.69% coverage.

## Next

P5-3: `clients.py` — `fpcalc` subprocess (argv/parse PURE) + the `RateLimiter` (injected clock,
deficit math, retry re-arm).
