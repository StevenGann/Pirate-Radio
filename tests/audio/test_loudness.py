"""RED tests for ``pirate_radio.audio.loudness`` — Phase 2 plan §4.1 (EBU R128, R22).

Tests first. ``measure_lufs`` / ``normalize_to`` wrap pyloudnorm (the ONE loudness path,
R22) to gain every element — tracks AND TTS — to a common target so music and speech sit
at consistent levels (§10). Pinned behaviors:
  - NON-GAMEABLE round-trip, BOTH polarities: a loud tone is attenuated to target, a quiet
    tone is amplified to target (precondition + post≈target + correction direction).
  - Immutability: the input buffer's samples are never mutated.
  - Pad-then-measure (Q4/A2): a short audible clip (<400ms) is padded, measured, and gained
    so it actually reaches target — NOT raw passthrough (which would violate §10).
  - True passthrough ONLY for empty / digitally-silent buffers.
  - Gain clamp (H16/H17): never amplifies past _MAX_GAIN_DB; logs a WARNING naming the track.
"""

from __future__ import annotations

import logging

import numpy as np

from pirate_radio.audio.buffer import AudioBuffer
from pirate_radio.audio.loudness import (
    _MAX_GAIN_DB,
    _MIN_BLOCK_SECONDS,
    _PAD_TARGET_SECONDS,
    measure_lufs,
    normalize_to,
)

_SR = 48_000


def _tone(freq: float, amp: float, seconds: float, sr: int = _SR) -> AudioBuffer:
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False, dtype=np.float32)
    return AudioBuffer((amp * np.sin(2 * np.pi * freq * t)).reshape(-1, 1), sr, 1)


# --- non-gameable round-trip, both polarities ------------------------------------


def test_loud_tone_is_attenuated_to_target() -> None:
    loud = _tone(1000.0, 0.9, 2.0)
    pre = measure_lufs(loud)
    assert pre is not None and pre > -23.0  # precondition: it WAS louder than target
    out = normalize_to(loud, target_lufs=-23.0)
    post = measure_lufs(out)
    assert post is not None and abs(post - (-23.0)) < 0.6  # post ~= target
    assert float(np.max(np.abs(out.samples))) < float(np.max(np.abs(loud.samples)))  # DOWN


def test_quiet_tone_is_amplified_to_target() -> None:
    quiet = _tone(1000.0, 0.02, 2.0)
    pre = measure_lufs(quiet)
    assert pre is not None and pre < -23.0  # precondition: it WAS quieter than target
    out = normalize_to(quiet, target_lufs=-23.0)
    post = measure_lufs(out)
    assert post is not None and abs(post - (-23.0)) < 0.6  # post ~= target
    assert float(np.max(np.abs(out.samples))) > float(np.max(np.abs(quiet.samples)))  # UP


def test_normalization_is_idempotent() -> None:
    once = normalize_to(_tone(1000.0, 0.5, 2.0), target_lufs=-20.0)
    twice = normalize_to(once, target_lufs=-20.0)
    lufs_once, lufs_twice = measure_lufs(once), measure_lufs(twice)
    assert lufs_once is not None and lufs_twice is not None
    assert abs(lufs_twice - lufs_once) < 0.3  # already at target: second pass barely changes it


def test_pad_target_exceeds_min_block() -> None:
    # Module invariant (Old Man amendment): the pad target must clear the gating block min,
    # else a padded short buffer still raises ValueError inside pyloudnorm at runtime.
    assert _PAD_TARGET_SECONDS > _MIN_BLOCK_SECONDS


# --- immutability + output invariants --------------------------------------------


def test_input_buffer_is_never_mutated() -> None:
    loud = _tone(1000.0, 0.9, 2.0)
    before = loud.samples.copy()
    normalize_to(loud, target_lufs=-30.0)
    np.testing.assert_array_equal(loud.samples, before)  # element-wise, not identity


def test_output_is_a_new_buffer_within_clip_range() -> None:
    src = _tone(1000.0, 0.9, 2.0)
    out = normalize_to(src, target_lufs=-6.0)
    assert out is not src  # a new buffer, never the input (independent of the polarity tests)
    assert isinstance(out, AudioBuffer)
    assert float(np.max(np.abs(out.samples))) <= 1.0  # H16: never exceeds full scale
    assert out.samples.dtype == np.float32


# --- gain clamp (H16/H17) --------------------------------------------------------


def test_gain_clamp_engages_and_warns_naming_track(caplog) -> None:
    # A near-silent buffer wants > _MAX_GAIN_DB of gain; the clamp must engage, cap the
    # amplification, and log a WARNING naming the track (so an operator spots a bad file).
    very_quiet = _tone(1000.0, 0.0005, 2.0)  # ~-66 LUFS; target -16 wants ~50 dB
    with caplog.at_level(logging.WARNING, logger="pirate_radio.audio.loudness"):
        out = normalize_to(very_quiet, target_lufs=-16.0, track_label="oldies/quiet.flac")
    # Applied gain is capped at _MAX_GAIN_DB, so it does NOT reach target.
    applied_db = 20.0 * np.log10(
        float(np.max(np.abs(out.samples))) / float(np.max(np.abs(very_quiet.samples)))
    )
    assert applied_db <= _MAX_GAIN_DB + 0.1
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert "oldies/quiet.flac" in caplog.text


# --- pad-then-measure short patter (Q4 / amendment A2) ---------------------------


def test_short_audible_patter_is_normalized_to_target_not_passed_through(caplog) -> None:
    # 250ms quiet clip: must be padded+measured+gained (NOT raw passthrough), reaching
    # ~target. A2: assert measured-LUFS-to-target (within a tolerance widened for the
    # documented sub-block gating-dilution bias), not merely "louder".
    patter = _tone(200.0, 0.05, 0.25)
    out = normalize_to(patter, target_lufs=-16.0, track_label="patter")
    assert out is not patter  # NOT passthrough
    assert out.frames == patter.frames  # padding never reaches the output
    assert float(np.max(np.abs(out.samples))) > float(np.max(np.abs(patter.samples)))  # amplified
    # A2: assert measured-LUFS-to-target. measure_lufs(out) re-pads identically, so the
    # sub-block dilution bias self-cancels and a correct impl lands ~exactly on target;
    # 0.6 (the long-buffer tolerance) is the real gate, not the loose 2.5 of the draft.
    post = measure_lufs(out)
    assert post is not None and abs(post - (-16.0)) < 0.6


def test_empty_buffer_is_true_passthrough() -> None:
    empty = AudioBuffer.silence(seconds=0.0)
    assert normalize_to(empty, target_lufs=-16.0) is empty


def test_digital_silence_measures_none_and_passes_through(caplog) -> None:
    silent = AudioBuffer.silence(seconds=1.0)
    assert measure_lufs(silent) is None
    with caplog.at_level(logging.DEBUG, logger="pirate_radio.audio.loudness"):
        assert normalize_to(silent, target_lufs=-16.0) is silent
    assert any(r.levelno == logging.DEBUG for r in caplog.records)  # passthrough is logged
