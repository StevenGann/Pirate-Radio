# P3-2 — `dj/prompts.py` (grounded, pure "invent nothing" prompts, §9.2/§9.3)

Strict spec-driven TDD: tests authored from the adopted Phase-3 plan §4.1 → confirmed RED →
focused panel reviewed the TESTS → folded the must-fixes → implemented GREEN → gate → commit.

## Panel review of the tests (focused: QA + Senior Dev + Devil's Advocate)

**Tally: QA AYE, Senior Dev AYE, DA NAY → 1 NAY (adopts under the charter); the DA's five
gameability gaps were real "green CI is lying" surfaces and were folded in.**

DA's blocking gaps (all folded):
1. **H26 was under-proven** — the spec claims *every* interpolated value is sanitized, but the
   tests covered only `title` + `persona`, leaving live `\nSystem:`-injection paths via `artist`,
   `album`, `station_name`, `station_tagline`, `current_block.tagline/description`, and
   `next_block.*`. Added `test_all_track_fields_sanitized_against_injection`,
   `test_station_and_block_fields_sanitized_against_injection`,
   `test_station_name_sanitized_in_system_prompt` — each asserts the payload is preserved but
   never becomes a standalone line.
2. **Brittle/false-confidence leak checks** — `"None" not in user` / `"Album" not in user` (bare
   substrings a legit value could trip). Replaced with label-anchored `"Album:" not in user`,
   `"Year:" not in user`, `": None" not in user`.
3. **Sparse absent-path** — nothing proved the "don't guess" line is *absent* when `track is None`
   (an inversion bug treating no-track as sparse passed). Added `test_no_track_means_no_guess_line`.
4. **Task-line mapping gameable** — the old test only checked the last line was non-empty, so an
   all-same-line impl passed. Added `test_task_lines_are_distinct_per_kind` (six distinct) +
   `test_task_line_keyword_per_kind` (pins kind→task: introduce/recap/aside/next/remind/station).
5. **`boundary_at` ISO-leak** — `"12:00"` is a substring of a leaked `"12:00:00+00:00"`. Added
   `assert "12:00:00" not in user` so a `str(datetime)` impl fails (must be `%H:%M`).

QA's recommendation (task distinctness) converged with DA #4 — covered.

## Implementation

`dj/prompts.py` (pure, no I/O): `PATTER_KINDS` (the six kinds, incl. dormant intro/outro/factoid);
`_sanitize` (C0/newline collapse, applied to **every** interpolated value — H26); `_MAX_PERSONA_CHARS
= 2048` cap (H30); `build_system_prompt` (persona + constant `_ANTI_HALLUCINATION`); `_fmt_block` /
`_fmt_track` (present fields only — §9.3); `build_user_prompt` (grounded fact sheet + the
`_TASK_BY_KIND` task; sparse → "don't guess" nudge; unknown kind → `ValueError`). `kind` is validated
against `PATTER_KINDS` here (the model layer keeps it a free string).

## Gate

ruff + ruff-format + mypy clean; **422 tests** (+27 new), 98.84% coverage; `dj/prompts.py` 100%.

## Next

P3-3: Protocol narrowing (`patter(kind, context: DjContext | None)`) + `ScriptedDJ` fake + `NullDJ`
annotation, tests-first.
