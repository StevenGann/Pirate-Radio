"""Decoder Protocol (R14) + FakeDecoder (Phase 1) + FfmpegDecoder (Phase 2, R22).

Phase 1 uses ``FakeDecoder`` (silent buffer at the track's exact metadata duration).
Phase 2 adds the real ``FfmpegDecoder``: a direct ffmpeg subprocess (no pydub, R22) that
decodes a whole track to a float32 ``AudioBuffer`` at the station rate. The subprocess runs
via ``asyncio.to_thread`` (R21/R23, never blocks the loop); ALL logic — argv construction,
the f32le PCM parser, the stderr→error map, the subprocess-exception map — is pure and
unit-tested. Only the literal ``subprocess.run`` call is hardware-bound (R20). H7 streaming
(whole-buffer → chunked) is the named Phase-3 refinement, triggered by stereo.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from typing import Protocol, runtime_checkable

import numpy as np

from pirate_radio.audio.buffer import DEFAULT_SAMPLE_RATE, AudioBuffer
from pirate_radio.catalog.models import Track
from pirate_radio.errors import ProviderError, ProviderFatal, ProviderUnavailable

logger = logging.getLogger(__name__)


@runtime_checkable
class Decoder(Protocol):
    """Track file -> ``AudioBuffer`` (R14). Raises ``ProviderError`` (R15) on a
    bad/missing file. Blocking native decoders MUST use ``asyncio.to_thread``."""

    async def decode(self, track: Track) -> AudioBuffer: ...


class FakeDecoder:
    """Phase-1 decode stub: silence at the track's exact metadata duration (§7)."""

    def __init__(self, *, sample_rate: int = DEFAULT_SAMPLE_RATE, channels: int = 1) -> None:
        self._sample_rate = sample_rate
        self._channels = channels

    async def decode(self, track: Track) -> AudioBuffer:
        return AudioBuffer.silence(
            seconds=track.duration, sample_rate=self._sample_rate, channels=self._channels
        )


class FailingDecoder:
    """A decoder that always raises ``ProviderError`` (R15) — drives the pipeline's R11
    backstop path in tests. Error class configurable (default ``ProviderUnavailable``)."""

    def __init__(self, *, error: ProviderError | None = None) -> None:
        self._error = error if error is not None else ProviderUnavailable("stub decode failure")

    async def decode(self, track: Track) -> AudioBuffer:
        raise self._error


def build_ffmpeg_argv(binary: str, src: str, *, sample_rate: int, channels: int) -> list[str]:
    """PURE: the ffmpeg command line. Decode ``src`` -> raw f32le on stdout, resampled to
    ``sample_rate`` and down/upmixed to ``channels`` (ffmpeg-side, Q2)."""
    return [
        binary,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        src,
        "-vn",  # drop any cover-art video stream
        "-ar",
        str(sample_rate),  # H5: resample ffmpeg-side (Q2)
        "-ac",
        str(channels),  # channel policy (Q6: mono v1)
        "-f",
        "f32le",  # raw 32-bit float LE -> maps 1:1 to float32 (Q1)
        "-",  # stdout
    ]


def parse_pcm_f32le(raw: bytes, *, sample_rate: int, channels: int) -> AudioBuffer:
    """PURE: interleaved f32le bytes -> ``AudioBuffer`` (frames, channels).

    Guards run BEFORE ``np.frombuffer`` so a malformed stream raises ``ProviderFatal`` — a
    bare ``ValueError`` would escape the producer's ``except ProviderError`` and crash the
    task (dead air). Empty / non-4-multiple / non-frame-aligned PCM -> ``ProviderFatal``.
    """
    if channels < 1:
        raise ProviderFatal(f"decode: channels must be >= 1, got {channels}")
    bytes_per_frame = 4 * channels  # f32 = 4 bytes/sample
    if len(raw) == 0:
        raise ProviderFatal("decode: ffmpeg produced empty PCM (0 bytes)")
    if len(raw) % 4 != 0:  # not even whole float32 samples
        raise ProviderFatal(f"decode: PCM byte length {len(raw)} not a multiple of 4")
    if len(raw) % bytes_per_frame != 0:  # whole samples but not whole frames
        raise ProviderFatal(
            f"decode: PCM byte length {len(raw)} not divisible by frame size "
            f"{bytes_per_frame} (channels={channels})"
        )
    flat = np.frombuffer(raw, dtype="<f4")  # only NOW is this safe
    samples = np.ascontiguousarray(flat.reshape(-1, channels), dtype=np.float32)
    return AudioBuffer(samples, sample_rate, channels)


def map_ffmpeg_error(returncode: int, stderr: str) -> ProviderError:
    """PURE: (returncode, stderr) -> typed ``ProviderError``. The LAST stderr line decides;
    a recognised decode failure is terminal (``ProviderFatal``), everything else is the
    retryable default (``ProviderUnavailable``)."""
    lines = stderr.strip().splitlines()
    msg = lines[-1] if lines else f"exit {returncode}"
    lowered = msg.lower()
    if any(s in lowered for s in ("no such file", "invalid data", "does not contain")):
        return ProviderFatal(f"ffmpeg cannot decode file: {msg}")
    return ProviderUnavailable(f"ffmpeg failed (exit {returncode}): {msg}")  # retryable default


def map_subprocess_exception(binary: str, exc: Exception) -> ProviderError:
    """PURE: a caught subprocess exception -> typed ``ProviderError``. A missing binary is
    terminal for this provider (``ProviderFatal``); a timeout is retryable
    (``ProviderUnavailable``)."""
    if isinstance(exc, FileNotFoundError):
        return ProviderFatal(f"ffmpeg binary not found: {binary}")
    if isinstance(exc, subprocess.TimeoutExpired):
        return ProviderUnavailable(f"ffmpeg timed out after {exc.timeout}s")
    return ProviderUnavailable(f"ffmpeg subprocess error: {exc}")


class FfmpegDecoder:
    """Real decode (R22): a direct ffmpeg subprocess to a whole-track f32 buffer at the
    station rate (H5/H7). The blocking call is offloaded via ``asyncio.to_thread`` (R21)."""

    def __init__(
        self,
        *,
        binary: str = "ffmpeg",
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        channels: int = 1,
        timeout_seconds: float = 120.0,  # H14
    ) -> None:
        self._binary = binary
        self._sample_rate = sample_rate
        self._channels = channels
        self._timeout = timeout_seconds

    async def decode(self, track: Track) -> AudioBuffer:
        argv = build_ffmpeg_argv(
            self._binary, str(track.path), sample_rate=self._sample_rate, channels=self._channels
        )
        try:
            proc = await asyncio.to_thread(self._run, argv)  # R21: blocking -> worker thread
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise map_subprocess_exception(self._binary, exc) from exc
        if proc.returncode != 0:
            raise map_ffmpeg_error(proc.returncode, proc.stderr.decode("utf-8", "replace"))
        return parse_pcm_f32le(proc.stdout, sample_rate=self._sample_rate, channels=self._channels)

    def _run(self, argv: list[str]) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(  # pragma: no cover  (R20: the ONLY hardware-bound line)
            argv, capture_output=True, check=False, timeout=self._timeout
        )
