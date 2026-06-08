"""EBU R128 / ITU-R BS.1770 loudness normalization (§10, R22).

ONE loudness path: pyloudnorm (pure-Python, unit-testable). Measures integrated loudness
(LUFS) of an ``AudioBuffer`` and returns a NEW buffer gained to a target LUFS, so every
element — tracks AND TTS — sits at a common level (§10). Immutable: never mutates the input.

pyloudnorm 0.2.x short-buffer behavior:
  * < 400 ms NON-silent  -> ``integrated_loudness`` RAISES ``ValueError`` (block too short).
  * >= 400 ms but below the -70 LUFS absolute gate (digital/near silence) -> RETURNS ``-inf``.
So we PAD short-but-audible buffers with trailing silence up to one gating block, measure
the padded buffer, then gain the ORIGINAL. The trailing silence sits inside the straddling
gating blocks and dilutes their K-weighted power slightly (a small, bounded bias) — this is
preferable to raw passthrough, which would leave short patter at a different level than the
music around it. True passthrough survives only for empty / digitally-silent buffers.

H7/H21: measures over the WHOLE buffer (Phase 2 decodes whole tracks); streaming /
running-loudness reconciliation is the named Phase-3 refinement, triggered by STEREO.
"""

from __future__ import annotations

import logging
import warnings

import numpy as np
import pyloudnorm as pyln

from pirate_radio.audio.buffer import AudioBuffer

logger = logging.getLogger(__name__)

# ITU-R BS.1770 integrated loudness gates on 400 ms blocks (75% overlap); a buffer shorter
# than one block cannot be measured.
_MIN_BLOCK_SECONDS = 0.4
# A hair over one block, so a padded short buffer always has >= 1 full gating block.
_PAD_TARGET_SECONDS = 0.45
# Module invariant: padding to below the block minimum would still raise inside pyloudnorm.
assert _PAD_TARGET_SECONDS > _MIN_BLOCK_SECONDS  # noqa: S101 (load-time guard, Old Man amendment)

# Clamp applied gain so a near-silent buffer can't be amplified into clipping/noise.
_MAX_GAIN_DB = 30.0


def _integrated(samples: np.ndarray, sample_rate: int) -> float:
    """The single pyloudnorm call site. ``astype(float64, copy=True)`` ALWAYS copies, so
    pyloudnorm cannot reach our float32 input — immutability holds. pyloudnorm emits a
    ``UserWarning`` for quiet/clipped input; suppress it here so it can't trip ``-W error``."""
    meter = pyln.Meter(sample_rate)  # BS.1770-4 K-weighting at this rate
    f64 = samples.astype(np.float64, copy=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return float(meter.integrated_loudness(f64))


def measure_lufs(buf: AudioBuffer) -> float | None:
    """Integrated loudness in LUFS, or ``None`` if the buffer is empty OR digital silence.

    Pads short (< 400 ms) audible buffers with trailing silence to ~450 ms before measuring
    (so BS.1770 has >= 1 gating block). Returns ``None`` only for empty / truly-silent
    buffers (which measure ``-inf`` even after padding).
    """
    if buf.frames == 0:
        return None
    samples = buf.samples
    if buf.duration_seconds < _MIN_BLOCK_SECONDS:
        pad_frames = int(round(_PAD_TARGET_SECONDS * buf.sample_rate)) - buf.frames
        if pad_frames > 0:
            silence = np.zeros((pad_frames, buf.channels), dtype=np.float32)
            samples = np.concatenate([buf.samples, silence], axis=0)  # NEW array; original intact
    loudness = _integrated(samples, buf.sample_rate)
    if not np.isfinite(loudness):  # -inf: digital/near silence (gated out)
        return None
    return loudness


def normalize_to(
    buf: AudioBuffer, *, target_lufs: float, track_label: str = "<unknown>"
) -> AudioBuffer:
    """Return a NEW ``AudioBuffer`` gained so its integrated loudness ~= ``target_lufs``.

    Measurement uses pad-then-measure; the gain is applied to the ORIGINAL buffer (padding
    never reaches the output). TRUE passthrough only for empty / digitally-silent buffers.
    Never raises, never produces NaN. The §10 "tracks AND TTS at a common target" rule holds
    for everything audible.
    """
    measured = measure_lufs(buf)
    if measured is None:
        logger.debug(
            "loudness: empty/silent buffer (%.3fs, %s) -> passthrough",
            buf.duration_seconds,
            track_label,
        )
        return buf
    raw_gain_db = target_lufs - measured
    gain_db = float(np.clip(raw_gain_db, -_MAX_GAIN_DB, _MAX_GAIN_DB))
    if gain_db != raw_gain_db:
        logger.warning(  # H17: WARNING, names track + LUFS so an operator spots a bad file
            "loudness: gain clamp engaged for %s (measured %.1f LUFS, target %.1f, "
            "wanted %+.1f dB, clamped to %+.1f dB) -- check for a mis-tagged/quiet file",
            track_label,
            measured,
            target_lufs,
            raw_gain_db,
            gain_db,
        )
    gain_lin = np.float32(10.0 ** (gain_db / 20.0))
    gained = (buf.samples * gain_lin).astype(np.float32)  # NEW array (immutability)
    np.clip(gained, -1.0, 1.0, out=gained)  # H16: guard inter-sample overs
    return AudioBuffer(gained, buf.sample_rate, buf.channels)
