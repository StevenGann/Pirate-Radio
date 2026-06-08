# P1-8 — catalog cache (A9) + committed golden determinism guard (P5)

Strict spec-driven TDD: tests authored from A9/H9 + P5 → confirmed RED → focused panel
reviewed the tests → adopted → implemented to GREEN → gate → commit. **Completes Phase 1.**

## Panel review of the tests (QA + Senior Dev/RPi + Devil's Advocate)

**Round 1 — QA NAY, Senior+RPi AYE, DA NAY → 2 NAY → revise + re-vote.** Sharp findings:

- **DA — the `is`-identity cache-hit check is gameable.** An impl that *always* rescans but
  returns the stored object would pass identity while defeating the cache's whole purpose.
  Fixed: `test_unchanged_tree_is_a_cache_hit_with_no_rescan` patches the cache's
  `scan_catalog` (wraps=real) and asserts `spy.assert_not_called()` on a hit. The real
  contract (no rescan) is now pinned.
- **QA + DA — the golden was byte-exact (`model_dump_json()`), conflating OUR determinism
  with pydantic's serialization stability** across the `>=2.7,<3` range (a pydantic bump
  could break it with no code change), and it crashed with `FileNotFoundError` before
  asserting. Fixed: the golden test now compares **parsed `DailySchedule` value-equality**
  (`_golden_schedule() == DailySchedule.model_validate_json(golden)`), robust to JSON
  formatting drift while still catching any change to generator *content* (items, durations,
  order, seed). Intra-environment byte-stability stays covered by
  `test_same_inputs_give_byte_identical_json`. The golden file is committed as the P5
  artifact, generated from `_golden_schedule()` — the single source of truth for both halves.
- **Senior/QA/DA — single-slot vs dict cache** ambiguity. Resolved: the cache is **keyed by
  content_dir** (a dict), pinned by `test_multiple_dirs_are_cached_independently` (A→B→A is a
  no-rescan hit). Safe for multi-station use.
- **RPi/H9 — FAT32/exFAT caveat.** Documented in the cache module + test docstrings: FAT
  dir-mtime has ~2 s resolution and may not update reliably, so the cache can stay hot
  across a structural change — use ext4 for the content dir if dependable invalidation
  matters.
- Plus: `_bump_mtime` ordering documented (runs AFTER the change; guards coarse FS); nested
  subdir invalidation pinned (`test_nested_subdir_change_invalidates_the_cache`).

**Round 2 — 3 AYE / 0 NAY → ADOPTED.** DA verified the value-equality golden holds despite
the round-trip turning `ZoneInfo` into pydantic's `TzInfo` (`==` compares by UTC offset).

## Implementation

- `catalog/cache.py` — `CatalogCache.load(content_dir)`: dict keyed by content_dir; the
  change signal is `_tree_signature` = sorted `(dir, st_mtime_ns)` for every directory in
  the tree (one `stat` per dir, no file opens). Hit → return stored Catalog; miss/changed →
  `scan_catalog` and store. A missing dir delegates to `scan_catalog` (raises `CatalogError`,
  never cached). Not thread-safe (single asyncio-loop use). H9 limits documented (in-place
  edits + FAT undetected).
- P5 golden: `tests/schedule/fixtures/golden_allday_seed7.json` committed; the guard catches
  cross-commit/cross-machine generator-content drift.

## Gate

ruff + ruff-format + mypy clean; **267 tests**, 98.60% coverage; cache.py + generator.py 100%.

## Phase 1 status

P1-1…P1-8 all complete. Phase 1 (single-station MVP slice: schedule models, AudioBuffer,
provider-error taxonomy, DJ/audio Protocol seams + fakes, generator, find_now/resume,
look-ahead pipeline, state_dir, catalog cache) is the validated, fully-tested foundation —
NOT yet a deployable radio (no coordinator/supervisor/midnight-regen/systemd/real audio;
those are Phase 4, H10).
