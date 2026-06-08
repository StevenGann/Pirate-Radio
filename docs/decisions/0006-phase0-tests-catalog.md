# Phase 0 — Increment 3: `catalog/` (models, metadata, scanner) (tests-first)

> Folder scan → tagged `Track` index (§7), built under strict spec-driven TDD.

## Process record

1. **Tests authored** from plan §4.4–4.6 / §6.4–6.5 with the amendments baked in
   (A5b caplog, A5c real-order + insertion-independence, A5d mandatory tagged
   fixture, A9 nested-collapse, A10 year bound). Real-WAV fixtures via stdlib
   `wave` + mutagen's `WAVE` tag interface (no mocks). Added `mutagen` dep + a mypy
   override (mutagen ships no stubs).
2. **Confirmed RED** (`ModuleNotFoundError`).
3. **Panel reviewed the TESTS — 6 AYE / 1 NAY → adopted.** The Devil's Advocate's
   lone NAY was correct and valuable: the tagged fixture was **WAV+ID3 only**, so
   the **Vorbis/MP4 branches of `_first` were untested** — an ID3-only impl would
   silently extract zero tags from a FLAC/OGG/M4A library. Adoption was already
   satisfied (≤1 NAY), but the finding was real, so it was folded in regardless.
4. **Hardening folded in** (all additive):
   - Direct `_first` dialect test (Vorbis lowercase-list, MP4 `\xa9` keys, ID3,
     empty-skip) — no FLAC/M4A encoder available in CI, so the dialect contract is
     pinned on `_first` directly. *(Devil's Advocate, BLOCKING — addressed)*
   - `read_metadata` swallows a raising mutagen (recognized-but-malformed file) via
     monkeypatch. *(Devil's Advocate)*
   - `_parse_year` messy/garbage dates + a plausibility guard (1..9999) so the
     scanner can't build an out-of-range `Track.year`. *(QA, A10)*
   - opens-but-zero-duration → None (0-frame WAV). *(Old Man, QA)*
   - unknown-suffix skip + case-insensitive suffix — pins `_AUDIO_SUFFIXES`. *(RPi)*
   - `Catalog` frozen-ness + tuple/frozenset return types. *(Senior Dev, Q1)*
5. **Implemented to GREEN.** `catalog/__init__.py`, `models.py` (Track, `year`
   `ge=1,le=9999`), `metadata.py` (`read_metadata`/`_first`/`_parse_year` guarded),
   `scanner.py` (`Catalog` value object + `scan_catalog`, recompute `groups()` per
   the majority Q1 view; mtime-cached rescan deferred to Phase 1 per RPi A9).

## Result

`ruff` clean · `mypy` clean (8 files) · **67 passed** · coverage **97.71%**
(4 uncovered defensive branches, not pragma'd). New dep: `mutagen>=1.47` + mypy
override.

## Next increment

`schedule/grid.py` (Slot/Grid models + YAML loader + day-of-week resolution + full
tiling validation, with the Q2/Q3 resolutions). Needs `PyYAML` added.
