# P5-6 — `tagging/tag_writer.py` (atomic tag write — the one destructive op)

Strict spec-driven TDD (tests from plan §Pipeline step 6 / P5-6 → RED → GREEN → gate).

## Implementation

- **`apply_tag_plan(plan, *, write_tags=None, dry_run=False) -> bool`** — no-op plan or `dry_run`
  writes nothing (dry-run logs the intended changes); else `_atomic_apply`. Returns whether it wrote.
- **`_atomic_apply(path, changes, write_tags)`** — copy to a **same-directory** temp (`.pirate-tmp`),
  `write_tags(tmp, changes)`, **`fsync`** the temp, then **`os.replace(tmp, path)`** (atomic
  same-filesystem rename). On ANY exception the temp is unlinked and re-raised — a power loss / Ctrl-C
  mid-write **leaves the original intact** (H-T4/RPi; the same-dir temp avoids a cross-device
  copy+unlink that wouldn't be atomic).
- **`_mutagen_write` / `_open_mutagen`** — the thin adapter: `changes()` → mutagen easy keys (`title`/
  `artist`/`album`, `year`→`date`, stringified), `save()`; an unreadable container → `TaggingFatal`.
  Only `_open_mutagen` (the real `mutagen.File` open) is the hardware seam.

No `TagWriter` Protocol (Old Man: one impl) — plain functions; the write seam is injected as a
callable for testing.

## Test strategy (deep-dive QA: no destructive logic hidden behind `@hardware`)

No audio codec is available in CI, so a real FLAC/OGG fixture can't be generated. Instead **all of our
logic is CI-tested** and only mutagen's real-container parse is hardware: (1) the **atomic
orchestration** is tested via an injected `write_tags` on plain files — same-dir temp, atomic replace,
**dry-run/no-op write nothing**, and **a mid-write failure leaves the original bytes intact + cleans up
the temp**; (2) the **mutagen mapping** is tested against a `mutagen.File` mock (`_open_mutagen`
monkeypatched) asserting the easy-key mapping (`year`→`date`) + `save()`, and unreadable→`TaggingFatal`.

## Tests (`tests/tagging/test_tag_writer.py`, 6)

no-op→no write; dry-run→no write, file unchanged; apply→same-dir temp + atomic replace + correct
changes; failure→original intact + temp cleaned; mapping→easy keys (`year`→`date`) + save; unreadable→
`TaggingFatal`.

## Gate

ruff + ruff-format + mypy `--strict` clean (53 source files); **779 tests** (+6), 97.56% coverage.

## Next

P5-7: `tagger.py` orchestration (walk → skip-tagged → fingerprint → AcoustID → MusicBrainz → choose →
atomic write; per-file isolation; dry-run; ordered `--limit`; nice/ionice; summary).
