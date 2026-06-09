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
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

from pirate_radio.audio.buffer import DEFAULT_SAMPLE_RATE, AudioBuffer
from pirate_radio.audio.resample import to_rate
from pirate_radio.config import (
    ElevenLabsProviderConfig,
    ElevenLabsTTSConfig,
    EspeakProviderConfig,
    EspeakTTSConfig,
    PiperProviderConfig,
    PiperTTSConfig,
)
from pirate_radio.dj._http import map_http_status, map_httpx_exception
from pirate_radio.errors import ProviderError, ProviderFatal, ProviderUnavailable

logger = logging.getLogger(__name__)

_ESPEAK_BASE_WPM = 175  # espeak's ~default speaking rate; scaled by cfg.speed
_S16_FULL_SCALE = 32768.0  # s16 → float32 divisor (NOT 32767) — pinned by the 1e-7 golden test


def _s16le_to_buffer(raw: bytes, *, sample_rate: int, channels: int) -> AudioBuffer:
    """PURE: little-endian s16 PCM bytes -> ``AudioBuffer`` (the shared decode for the WAV path and
    the ElevenLabs raw-PCM path). Callers do their own framing/guards first; this is only the
    frombuffer → /32768 → reshape(-1, channels) core (cycle-3 consolidation)."""
    ints = np.frombuffer(raw, dtype="<i2").astype(np.float32) / np.float32(_S16_FULL_SCALE)
    samples = np.ascontiguousarray(ints.reshape(-1, channels), dtype=np.float32)
    return AudioBuffer(samples, sample_rate, channels)


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
    return _s16le_to_buffer(pcm, sample_rate=rate, channels=ch)


def build_piper_argv(python: str, model: Path, out_path: str, *, speed: float) -> list[str]:
    """PURE incl. speed math: piper ``--length_scale = 1/speed`` (guard speed > 0). Invokes the
    piper1-gpl module (``python -m piper``); ``--model`` takes the ``.onnx`` path, ``--output_file``
    /``--length_scale`` are the fork's compatible aliases, and text is fed on stdin."""
    if speed <= 0:
        raise ProviderFatal(f"piper: speed must be > 0, got {speed}")
    return [
        python,
        "-m",
        "piper",
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
        str(round(_ESPEAK_BASE_WPM * cfg.speed)),  # speed MATH here
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
    # "no such file" / "onnx" catch a missing model OR its companion .onnx.json (piper's
    # FileNotFoundError tail) — a permanent misconfig, NOT a retryable transient (panel DA).
    if any(s in lowered for s in ("voice", "model", "not found", "no such file", "onnx")):
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
    """Local neural TTS (primary): the piper1-gpl fork, run as ``python -m piper`` (no binary)."""

    def __init__(
        self,
        *,
        cfg: PiperTTSConfig,
        provider: PiperProviderConfig,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        timeout_seconds: float = 30.0,  # H14
    ) -> None:
        self._cfg = cfg
        # `python -m piper` (piper1-gpl): default to the daemon's own interpreter, where
        # `pip install piper-tts` naturally lands; an operator with piper in a separate venv sets
        # tts_providers.piper.python. (No PATH binary -> the old Debian-`piper` footgun is gone.)
        self._python = str(provider.python) if provider.python else sys.executable
        self._model = provider.voices_dir / f"{cfg.voice}.onnx"
        self._sample_rate = sample_rate
        self._timeout = timeout_seconds

    async def synthesize(self, text: str) -> AudioBuffer:
        if not text.strip():
            return AudioBuffer.silence(seconds=0.0, sample_rate=self._sample_rate)
        try:
            buf = await asyncio.to_thread(self._run_to_buffer, text)  # R21: off the loop
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise _map_tts_exception("piper", self._python, exc) from exc
        return to_rate(buf, self._sample_rate)  # H5

    def _run_to_buffer(self, text: str) -> AudioBuffer:
        with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:  # H15: per-call, unique
            argv = build_piper_argv(self._python, self._model, tmp.name, speed=self._cfg.speed)
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


# ---- ElevenLabs cloud TTS (D5) — mirrors PiperTTS over httpx instead of subprocess ---------
_ELEVEN_BASE = "https://api.elevenlabs.io/v1/text-to-speech"


def build_elevenlabs_request(
    cfg: ElevenLabsTTSConfig, *, base_url: str = _ELEVEN_BASE
) -> tuple[str, dict[str, object]]:
    """PURE: (url, json body) for an ElevenLabs TTS call. voice_id -> URL;
    stability/similarity_boost -> voice_settings. ``text`` is filled by ``synthesize``."""
    url = f"{base_url.rstrip('/')}/{cfg.voice_id}"
    body: dict[str, object] = {
        "text": "",
        "voice_settings": {"stability": cfg.stability, "similarity_boost": cfg.similarity_boost},
    }
    return url, body


def pcm_s16le_to_buffer(raw: bytes, *, sample_rate: int, channels: int = 1) -> AudioBuffer:
    """PURE: ElevenLabs raw PCM (s16le) -> AudioBuffer at ``sample_rate``. Mirrors the Phase-2
    WAV parser's guards: empty / non-frame-aligned -> ProviderFatal. Divisor is /32768 (NOT
    /32767) — pinned by the 1e-7 golden test."""
    if len(raw) == 0:
        raise ProviderFatal("elevenlabs: empty audio body")
    bytes_per_frame = 2 * channels
    if len(raw) % bytes_per_frame != 0:
        raise ProviderFatal(
            f"elevenlabs: PCM length {len(raw)} not divisible by frame size {bytes_per_frame}"
        )
    return _s16le_to_buffer(raw, sample_rate=sample_rate, channels=channels)


class ElevenLabsTTS:
    """Cloud TTS (D5), ranked alongside Piper (the local floor). httpx, native async (R23).

    Requests s16le PCM at a known rate (output_format=pcm_24000), parses it like Piper, then
    resamples to the station rate via ``to_rate`` (H5). The ONE network line is pragma:no cover
    (R20); the HTTP error mappers come from ``dj/_http`` (NOT dj/text — no sibling import)."""

    _REQUEST_RATE = 24_000  # ElevenLabs pcm_24000 output_format; resampled to the station rate

    def __init__(
        self,
        *,
        cfg: ElevenLabsTTSConfig,
        provider: ElevenLabsProviderConfig,  # noqa: ARG002 — kept for build.py call symmetry
        api_key: str,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        timeout_seconds: float = 30.0,  # H14/H23
    ) -> None:
        self._cfg = cfg
        self._api_key = api_key
        self._sample_rate = sample_rate
        self._timeout = timeout_seconds

    async def synthesize(self, text: str) -> AudioBuffer:
        if not text.strip():
            return AudioBuffer.silence(seconds=0.0, sample_rate=self._sample_rate)
        url, body = build_elevenlabs_request(self._cfg)
        body["text"] = text
        raw = await self._fetch(url, body)
        buf = pcm_s16le_to_buffer(raw, sample_rate=self._REQUEST_RATE)  # PURE
        return to_rate(buf, self._sample_rate)  # H5: to the station rate

    async def _fetch(self, url: str, body: dict[str, object]) -> bytes:
        import httpx  # R21: lazy — never imported at module scope / on the faked path

        headers = {"xi-api-key": self._api_key, "accept": "audio/pcm"}
        params = {"output_format": f"pcm_{self._REQUEST_RATE}"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:  # pragma: no cover (net)
                resp = await client.post(  # pragma: no cover (network)
                    url, headers=headers, params=params, json=body
                )
                if resp.status_code >= 400:  # tested via the fake-httpx seam (no real socket)
                    raise map_http_status("elevenlabs", resp.status_code, resp.text)
                return resp.content
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 — re-typed by the pure mapper
            raise map_httpx_exception("elevenlabs", exc) from exc
