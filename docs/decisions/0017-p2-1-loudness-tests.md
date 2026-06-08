# P2-1 — `audio/loudness.py` (EBU R128 via pyloudnorm) + `loudness_target_lufs` bound

Strict spec-driven TDD: tests authored from the adopted Phase-2 plan §4.1 + amendment A2
→ confirmed RED → focused panel reviewed the tests → adopted → GREEN → gate → commit.

## Panel review of the tests (focused: QA + Senior Dev + Devil's Advocate)

**3 AYE / 0 NAY → ADOPTED.** All three independently verified (against real pyloudnorm
0.2.0 / scipy 1.17.1) that every LUFS precondition holds: a 1 kHz sine at amp 0.9 ≈ -4 LUFS
(> -23), amp 0.02 ≈ -37 (< -23), amp 0.0005 ≈ -69 (wants > 30 dB → clamp). The round-trip
is non-gameable in both polarities (precondition + post≈target + correction direction), so
no constant-gain or passthrough impl can pass.

Improvements folded in before GREEN:
- **A2 tolerance tightened** 2.5 → 0.6 LUFS. QA+DA showed the sub-block dilution bias
  *self-cancels* (the verifying `measure_lufs(out)` re-pads identically), so a correct impl
  lands ~exactly on target; 2.5 was ~50× too loose to gate anything.
- **`_PAD_TARGET_SECONDS > _MIN_BLOCK_SECONDS` invariant test** added (Old Man binding
  amendment) — plus a module-load `assert` of the same in loudness.py.
- **DEBUG passthrough log** pinned via caplog on the digital-silence test.
- **`out is not src`** identity check added so the new-buffer test stands alone.
- **Idempotence None-deref** fixed with explicit `is not None` guards.

Deferred (advisory, not blocking): a stereo round-trip test — Phase 2 ships mono (Q6); the
plan names stereo as the H7/H21 streaming trigger, so a stereo guard test lands with P2-6.

## Implementation

- `audio/loudness.py`: `measure_lufs(buf) -> float | None` and `normalize_to(buf, *,
  target_lufs, track_label) -> AudioBuffer`. ONE pyloudnorm call site (`_integrated`,
  warnings-suppressed; `astype(float64, copy=True)` always copies ⇒ input immutable).
  Pad-then-measure for short audible buffers (pad with trailing silence to ~450 ms, measure
  padded, gain the ORIGINAL); true passthrough only for empty/`-inf`-silent buffers. Gain
  clamped to ±`_MAX_GAIN_DB`=30 with a WARNING naming the track (H17); output clipped to
  ±1.0 (H16); always a NEW buffer.
- `config.StationConfig.loudness_target_lufs`: `Field(default=-16.0, ge=-40.0, le=0.0)` —
  resolves the 0010 carry-forward; positive and absurdly-low (-160) targets now rejected at
  config load.
- Deps: `pyloudnorm>=0.2.0,<0.3`, `scipy>=1.15,<2` (aarch64 wheels; README note added).

## Gate

ruff + ruff-format + mypy clean; **280 tests**, 98.58% coverage; loudness.py 98% (one
defensive `pad_frames > 0` partial branch).
