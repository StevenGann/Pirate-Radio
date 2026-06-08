# P4-4 — `pipeline/daily.py` (daily slice + seek + R11 gap) + `recent_tracks` grounding

Strict spec-driven TDD: tests authored from the adopted Phase-4 plan §B / P4-4 → confirmed RED →
implemented GREEN → gate. Per the autonomous-to-completion directive, the remaining Phase-4
increments are authored with the lessons from the P4-1/2/3 panel rounds folded directly into the
tests (seek offset-past-frames guard, gap-at-station-format, look-ahead-ordered recent_tracks); the
full-seven **Phase-4 deep-dive (P4-9)** is the quality backstop that reviews all of it.

## Implementation

- `pipeline/daily.py`: `slice_from_now(anchored, now) -> (items, offset, gap)` — PURE, the
  index-derived slice mirroring `find_now`'s bisect (airing → offset; gap/before-first → leading
  silence, R11; past end-of-day → empty). `play_day(*, anchored, now, **run_once_kwargs)` — plays
  the R11 leading gap at the station format, **seeks into the first track** by decode+trim with the
  **offset-past-decoded-frames → skip guard** (VBR/truncated/metadata-lying files never emit an
  empty buffer, DA H2), then delegates the remainder to the FROZEN `run_once` (Q1 — trim here, don't
  churn `run_once`). The seek trim is `ascontiguousarray` + `normalize_to` (loudness-consistent).
- `pipeline/producer.py` + `build_dj_context`: `recent_tracks` grounding (§9.2). `build_dj_context`
  gains a `recent_tracks` param (default `()`); the Producer owns a bounded `deque(maxlen=5)`,
  appends each `TrackItem`'s `TrackMeta` as it renders (look-ahead-ordered = schedule order, so a
  patter item sees the tracks scheduled before it — Q3), and passes it to `build_dj_context`. No
  `run_once` signature change (the deque is Producer-internal; resets per day, acceptable for v1).

## Tests (26)

`slice_from_now` across airing / midway / in-gap / before-first / past-end; `play_day` leading-gap
(asserted at the station `(sample_rate, channels)` + exact sample count), seek-trim (60s of a 100s
track resumed at 40s), **offset-past-decoded-frames → skip** (10s file, 40s offset → first item
skipped, never an empty buffer), past-end airs nothing; `recent_tracks` grounding (two tracks before
a station_id appear in its DjContext, look-ahead-ordered). play_day integration patches
`normalize_to`→identity + `to_thread`→inline (the P2-6 virtual-time determinism pattern).

## Gate

ruff + ruff-format + mypy `--strict` clean (42 files); **632 tests** (+10), 98.59% coverage;
`pipeline/daily.py` 100%, `pipeline/producer.py` 100%.

## Next

P4-5: `station.py` (load-or-generate + resume + day loop + StationStatus + skip_item) — and P4-5b
(`item_kind` Protocol-param removal).
