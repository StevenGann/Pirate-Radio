# Phase 0 — Increment 4: `schedule/grid.py` (tests-first)

> Grid models + YAML loader + day-of-week resolution + fail-fast tiling validation
> (§8.2/§8.3) — the largest Phase-0 module. Built under strict spec-driven TDD.

## Process record

1. **Tests authored** from plan §4.7 / §6.6 with the Q3 fence built in (single
   all-day accepted; two all-day / non-final-midnight / zero-length rejected).
2. **Confirmed RED.**
3. **Panel reviewed the TESTS — 6 AYE / 1 NAY (QA) → adopted.** QA's NAY was
   correct: §8.3's "time formats parse" rule had **zero coverage** — an impl that
   let a raw Pydantic `ValidationError` escape un-wrapped (instead of the typed
   `GridValidationError` the system catches) would pass. Folded in regardless.
   The Devil's Advocate AYE'd with a proof that the Q3 fence genuinely forces the
   "midnight-end only on final slot" rule and that non-adjacent overlaps cannot
   slip through (pairwise + `start<end` + endpoints force a single-wrap chain).
4. **Hardening folded in** (all additive):
   - **time-format parse** → `GridValidationError` (`"25:99"`). *(QA, BLOCKING)*
   - Saturday `weekday=5` → `weekend.yaml` boundary. *(RPi — off-by-one guard)*
   - missing-`slots`-key, empty-file (`touch`→None), slot-not-a-mapping,
     unreadable-path (dir → OSError), empty-group. *(QA, DA, Senior Dev)*
   - minimal-slot optional-None, slot-order-preservation, actionable gap message
     (names slots + times). *(Senior Dev, DA, Field Op)*
   - **Shared `test_phase0_models_are_frozen`** parametrized over Track / Catalog /
     Slot / Grid — closes the recurring frozen-ness gap (incl. the earlier Catalog
     miss) in one place. *(Senior Dev)*
   - `match="final"` on the two midnight-rejection tests so they can't go green for
     an unrelated reason.
5. **Implemented to GREEN.** `schedule/__init__.py`, `schedule/grid.py` — with the
   Q3 rule added to `_validate_tiling` (non-final slot ending at 00:00 → reject).

## Result

`ruff` clean · `mypy` clean (10 files) · **101 passed** · coverage **98.30%**
(grid.py 100%). New deps: `PyYAML>=6.0` + `types-PyYAML` (dev).

## Next increment

`audio_devices.py` (R10 resolver seam — `resolve(name)->PortId` per A2) +
`config.py` (discriminated-union TTS/LLM configs, all §12 fail-fast validation incl.
empty-env A1, state_dir A6, Q2 validate-all-grids). Then PR10: retire the `hello()`
placeholder.
