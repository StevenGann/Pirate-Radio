"""Local TTS engines (R22): PiperTTS (primary, §11/D2 floor) + EspeakTTS (fallback).

Each engine: build argv (PURE, including speed/pitch MATH), feed text on stdin, read the WAV
output, parse it (stdlib ``wave``, PURE), and resample to the station rate via ``to_rate``
(H5). The ``subprocess.run`` call is the ONLY hardware-bound line (R20); every failure maps
to a typed ``ProviderError`` so the producer backstops rather than crashing. ElevenLabs
(cloud, D5) ships in Phase 3 alongside ranked failover (sequencing override, 0016).
"""

from __future__ import annotations

import asyncio
import io
import logging
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

from pirate_radio.audio.buffer import DEFAULT_SAMPLE_RATE, AudioBuffer
from pirate_radio.audio.resample import to_rate
from pirate_radio.config import (
    EspeakProviderConfig,
    EspeakTTSConfig,
    PiperProviderConfig,
    PiperTTSConfig,
)
from pirate_radio.errors import ProviderError, ProviderFatal, ProviderUnavailable

logger = logging.getLogger(__name__)


def wav_bytes_to_buffer(raw: bytes) -> AudioBuffer:
    """PURE: canonical s16 PCM-WAV bytes -> ``AudioBuffer`` at the WAV's own rate (the caller
    resamples). Structural garbage / non-s16 / bad rate -> ``ProviderFatal``."""
    try:
        with wave.open(io.BytesIO(raw), "rb") as w:
            ch, width, rate, nframes = (
                w.getnchannels(),
                w.getsampwidth(),
                w.getframerate(),
                w.getnframes(),
            )
            pcm = w.readframes(nframes)
    except (wave.Error, EOFError) as exc:
        raise ProviderFatal(f"tts: unreadable WAV ({exc})") from exc
    if rate <= 0:
        raise ProviderFatal(f"tts: WAV framerate must be > 0, got {rate}")
    if width != 2:  # piper/espeak emit s16; guard anything else
        raise ProviderFatal(f"tts: unexpected WAV sample width {width} bytes (expected 2)")
    if ch < 1:  # pragma: no cover - defensive; the wave module never yields < 1 channel
        raise ProviderFatal(f"tts: WAV channels must be >= 1, got {ch}")
    ints = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / np.float32(32768.0)
    samples = np.ascontiguousarray(ints.reshape(-1, ch), dtype=np.float32)
    return AudioBuffer(samples, rate, ch)


def build_piper_argv(binary: str, model: Path, out_path: str, *, speed: float) -> list[str]:
    """PURE incl. speed math: piper ``--length_scale = 1/speed`` (guard speed > 0)."""
    if speed <= 0:
        raise ProviderFatal(f"piper: speed must be > 0, got {speed}")
    return [
        binary,
        "--model",
        str(model),
        "--output_file",
        out_path,
        "--length_scale",
        repr(1.0 / speed),  # speed MATH is here, unit-tested
    ]


def build_espeak_argv(binary: str, cfg: EspeakTTSConfig, out_path: str) -> list[str]:
    """PURE incl. speed math: espeak ``-s round(175*speed)`` wpm (guard speed > 0)."""
    if cfg.speed <= 0:
        raise ProviderFatal(f"espeak: speed must be > 0, got {cfg.speed}")
    return [
        binary,
        "-v",
        cfg.voice,
        "-s",
        str(round(175 * cfg.speed)),  # ~175 wpm default; speed MATH here
        "-p",
        str(cfg.pitch),  # 0..99
        "-w",
        out_path,
        "--stdin",
    ]


def _map_tts_error(engine: str, returncode: int, stderr: bytes) -> ProviderError:
    """PURE: (engine, returncode, stderr) -> typed ``ProviderError``. Last stderr line decides."""
    lines = stderr.decode("utf-8", "replace").strip().splitlines()
    tail = lines[-1] if lines else f"exit {returncode}"
    lowered = tail.lower()
    if any(s in lowered for s in ("voice", "model", "not found")):
        return ProviderFatal(f"{engine} bad voice/model: {tail}")
    return ProviderUnavailable(f"{engine} failed (exit {returncode}): {tail}")  # retryable default


def _map_tts_exception(engine: str, binary: str, exc: Exception) -> ProviderError:
    """PURE: a caught subprocess exception -> typed ``ProviderError``."""
    if isinstance(exc, FileNotFoundError):
        return ProviderFatal(f"{engine} binary not found: {binary}")
    if isinstance(exc, subprocess.TimeoutExpired):
        return ProviderUnavailable(f"{engine} timed out after {exc.timeout}s")
    return ProviderUnavailable(f"{engine} subprocess error: {exc}")


class PiperTTS:
    """Local neural TTS (primary). Requires an explicit binary (H16: no PATH fallback)."""

    def __init__(
        self,
        *,
        cfg: PiperTTSConfig,
        provider: PiperProviderConfig,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        timeout_seconds: float = 30.0,  # H14
    ) -> None:
        if provider.binary is None:  # H16: no PATH fallback for piper
            raise ProviderFatal(
                "piper: tts_providers.piper.binary is required (Debian 'piper' is an unrelated "
                "mouse tool; set the explicit piper-TTS path)"
            )
        self._cfg = cfg
        self._binary = str(provider.binary)
        self._model = provider.voices_dir / f"{cfg.voice}.onnx"
        self._sample_rate = sample_rate
        self._timeout = timeout_seconds

    async def synthesize(self, text: str) -> AudioBuffer:
        if not text.strip():
            return AudioBuffer.silence(seconds=0.0, sample_rate=self._sample_rate)
        try:
            buf = await asyncio.to_thread(self._run_to_buffer, text)  # R21: off the loop
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise _map_tts_exception("piper", self._binary, exc) from exc
        return to_rate(buf, self._sample_rate)  # H5

    def _run_to_buffer(self, text: str) -> AudioBuffer:
        with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:  # H15: per-call, unique
            argv = build_piper_argv(self._binary, self._model, tmp.name, speed=self._cfg.speed)
            proc = subprocess.run(  # pragma: no cover  (R20: the ONLY hardware line)
                argv,
                input=text.encode("utf-8"),
                capture_output=True,
                check=False,
                timeout=self._timeout,
            )
            if proc.returncode != 0:
                raise _map_tts_error("piper", proc.returncode, proc.stderr)
            return wav_bytes_to_buffer(Path(tmp.name).read_bytes())


class EspeakTTS:
    """Retro/robotic fallback TTS. ``binary`` may be None -> PATH lookup (espeak-ng/espeak)."""

    def __init__(
        self,
        *,
        cfg: EspeakTTSConfig,
        provider: EspeakProviderConfig,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._cfg = cfg
        self._binary = str(provider.binary) if provider.binary else "espeak-ng"
        self._sample_rate = sample_rate
        self._timeout = timeout_seconds

    async def synthesize(self, text: str) -> AudioBuffer:
        if not text.strip():
            return AudioBuffer.silence(seconds=0.0, sample_rate=self._sample_rate)
        try:
            buf = await asyncio.to_thread(self._run_to_buffer, text)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise _map_tts_exception("espeak", self._binary, exc) from exc
        return to_rate(buf, self._sample_rate)

    def _run_to_buffer(self, text: str) -> AudioBuffer:
        with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
            argv = build_espeak_argv(self._binary, self._cfg, tmp.name)
            proc = subprocess.run(  # pragma: no cover  (R20: the ONLY hardware line)
                argv,
                input=text.encode("utf-8"),
                capture_output=True,
                check=False,
                timeout=self._timeout,
            )
            if proc.returncode != 0:
                raise _map_tts_error("espeak", proc.returncode, proc.stderr)
            return wav_bytes_to_buffer(Path(tmp.name).read_bytes())
