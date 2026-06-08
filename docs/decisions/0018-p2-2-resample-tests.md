# P2-2 — `audio/resample.py` (`to_rate` via scipy `resample_poly`)

Strict spec-driven TDD: tests authored from the adopted Phase-2 plan §4.2 → confirmed RED
→ focused panel reviewed the tests → adopted → GREEN → gate → commit.

## Panel review of the tests (focused: QA + Devil's Advocate)

**QA AYE, DA NAY → 1 NAY → ADOPTED.** The DA's two MAJORs were genuinely valuable and
folded in despite the adopt:
- **Stereo test was gameable** — the draft used identical channels (`column_stack([mono]*2)`),
  so a lazy impl that resamples ch0 and copies it to ch1 (or resamples the wrong axis) would
  pass. **Fixed:** `test_stereo_is_resampled_independently_per_channel` now uses DISTINCT
  content (1 kHz on ch0, 440 Hz on ch1), asserts the channels stay distinct
  (`not np.allclose`), and checks per-channel RMS preservation.
- **Guard test passed even without our guard** — scipy's `resample_poly` raises `ValueError`
  for `up/down < 1` on its own, so `to_rate(buf, 0)` would raise regardless. **Fixed:**
  `pytest.raises(ValueError, match="target_rate")` pins that OUR guard (naming `target_rate`)
  fires first.
- Easy MINORs folded: added `sample_rate`/`channels`/`dtype` asserts to the downsample test;
  tightened the energy tolerance 0.02 → 0.005; added the downsample energy polarity.

Both reviewers confirmed (against scipy 1.17.1) the suite is non-gameable: a relabel-only
impl fails the frame-count (round(in*tgt/src)±1), duration-preserved, and RMS-energy gates;
the ±1 tolerance is moot for 22050↔48000 (exact 320/147 ratio) but correct in general.

## Implementation

- `audio/resample.py`: `to_rate(buf, target_rate)` — `scipy.signal.resample_poly(up, down,
  axis=0)` with `gcd` reduction, cast to float32, contiguous. No-op identity (`is buf`) when
  already at rate; `ValueError` for `target_rate <= 0`. ONE resampler in the codebase (Q2);
  decode resamples ffmpeg-side, TTS WAVs convert here.
- `pyproject.toml`: mypy override extended to `pyloudnorm.*` + `scipy.*` (no type stubs) —
  also retroactively clears P2-1's `pyloudnorm` import-untyped error a stale mypy cache had
  masked.

## Gate

ruff + ruff-format + mypy clean (30 files); **287 tests**, 98.60% coverage; resample.py 100%.
