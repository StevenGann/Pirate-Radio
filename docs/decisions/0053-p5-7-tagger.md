# P5-7 — `tagging/tagger.py` (orchestration)

Strict spec-driven TDD (tests from plan §Pipeline + §P5-7 → RED → GREEN → gate).

## Implementation

- **`tag_library(*, content_dir, fingerprinter, acoustid, musicbrainz, read_tags, write, walk,
  lower_priority, force, dry_run, limit, min_score) -> TagSummary`** — all collaborators are injected
  seams (CI-tested with fakes; the real defaults are `read_existing_tags` / `apply_tag_plan` /
  `_walk_audio` / `_default_lower_priority`). Lowers process priority ONCE at the start (`nice -n 19`
  + best-effort `ionice -c3`, no shell), walks audio files in **stable sorted order**, applies a
  deterministic `limit`, and runs each file ISOLATED: `TaggingError` → WARNING (scrubbed) + continue;
  any other exception → CRITICAL (scrubbed) + continue — one bad file never aborts the batch (H-T4).
  Returns + logs a `TagSummary(tagged, skipped, failed, total)`.
- **`_tag_one`** — the per-file pipeline: skip-tagged gate (`title` AND `artist` present, unless
  `force`) BEFORE the expensive fingerprint; fingerprint → AcoustID lookup → `best_match` (sub-floor
  → skip, NO MusicBrainz call) → MusicBrainz recording → `choose_best` → atomic `write` (`dry_run`
  threaded). Returns whether it wrote.
- `read_existing_tags` (added to `tag_writer.py`) reads the current tags for the gate + the merge.

## Tests (`tests/tagging/test_tagger.py` 7, `test_tag_writer.py` +2)

tags untagged files; skip-tagged short-circuits BEFORE fingerprint; sub-floor match skips without a
MusicBrainz call; per-file failure isolated (sibling still tagged); dry-run writes nothing; `--limit`
deterministic over a stable order; `lower_priority` called once. `read_existing_tags` maps easy keys /
unreadable→untagged.

## Gate

ruff + ruff-format + mypy `--strict` clean (54 source files); **788 tests** (+9), 97.40% coverage.

## Next

P5-8: `__main__.py` CLI (`main(argv, *, deps)` + startup fail-fast on fpcalc/key/UA + broadcast-WARN)
+ `docs/ops/tagging.md` runbook.
