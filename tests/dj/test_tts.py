"""RED tests for ``pirate_radio.dj.tts`` — PiperTTS + EspeakTTS — Phase 2 plan §4.4 (R22).

Tests first. Real local TTS shells out to piper/espeak, but ALL logic is pure and CI-covered:
the WAV parser, the argv builders (INCLUDING speed/pitch math), and the error/exception maps.
The async ``synthesize`` orchestration is exercised by monkeypatching (no real binary). The
subprocess call is the only hardware line; a real-binary smoke is ``@pytest.mark.hardware``.

Pinned: WAV golden (s16 endianness) + framerate≤0/width≠2 → ProviderFatal; piper
``--length_scale = 1/speed`` and espeak ``-s round(175*speed)`` (math in the PURE builders);
speed≤0 → ProviderFatal; missing binary → ProviderFatal; timeout → ProviderUnavailable;
output resampled to the station rate (H5); empty text → 0s silence at the station rate; piper
with no configured binary → ProviderFatal (H16); synth offloaded off the event loop (R21).
"""

from __future__ import annotations

import io
import struct
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from pirate_radio.audio.buffer import DEFAULT_SAMPLE_RATE, AudioBuffer
from pirate_radio.config import (
    EspeakProviderConfig,
    EspeakTTSConfig,
    PiperProviderConfig,
    PiperTTSConfig,
)
from pirate_radio.dj.protocols import TTSEngine
from pirate_radio.dj.tts import (
    EspeakTTS,
    PiperTTS,
    _map_tts_error,
    _map_tts_exception,
    build_espeak_argv,
    build_piper_argv,
    wav_bytes_to_buffer,
)
from pirate_radio.errors import ProviderError, ProviderFatal, ProviderUnavailable


def _wav_bytes(
    *, rate: int = 22_050, value: int = 16_384, frames: int = 100, channels: int = 1
) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", value) * frames * channels)
    return buf.getvalue()


def _write_wav(path: str, *, rate: int = 22_050, value: int = 16_384, frames: int = 100) -> None:
    Path(path).write_bytes(_wav_bytes(rate=rate, value=value, frames=frames))


# --- wav_bytes_to_buffer (pure) -------------------------------------------------


def test_wav_golden_s16_endianness() -> None:
    buf = wav_bytes_to_buffer(_wav_bytes(rate=22_050, value=16_384, frames=1))
    assert buf.sample_rate == 22_050
    assert buf.samples.shape == (1, 1)
    # 1e-7 (not 1e-4): pins the /32768 scaling exactly — a wrong /32767 divisor (0.50002)
    # would slip through a loose tolerance.
    assert abs(float(buf.samples[0, 0]) - 0.5) < 1e-7  # 16384/32768 == 0.5 exactly
    assert buf.samples.dtype == np.float32


def test_wav_unreadable_is_fatal() -> None:
    with pytest.raises(ProviderFatal):
        wav_bytes_to_buffer(b"not a wav at all")


def test_wav_bad_sample_width_is_fatal() -> None:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(4)  # 32-bit, not the expected s16
        w.setframerate(22_050)
        w.writeframes(b"\x00\x00\x00\x00" * 10)
    with pytest.raises(ProviderFatal):
        wav_bytes_to_buffer(buf.getvalue())


def test_wav_zero_framerate_is_fatal() -> None:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(1)  # wave rejects 0; patch the header to 0 below
        w.writeframes(b"\x00\x00" * 10)
    raw = bytearray(buf.getvalue())
    # zero out the sample-rate field in the fmt chunk (offset 24, little-endian uint32)
    raw[24:28] = (0).to_bytes(4, "little")
    with pytest.raises(ProviderFatal):
        wav_bytes_to_buffer(bytes(raw))


# --- _map_tts_error / _map_tts_exception (pure) ---------------------------------


@pytest.mark.parametrize("stderr", [b"voice not found", b"no such model", b"file not found"])
def test_map_tts_error_voice_model_is_fatal(stderr: bytes) -> None:
    assert isinstance(_map_tts_error("piper", 1, stderr), ProviderFatal)


def test_map_tts_error_unknown_is_unavailable() -> None:
    assert isinstance(_map_tts_error("piper", 70, b"segmentation fault"), ProviderUnavailable)


def test_map_tts_error_empty_stderr_is_unavailable_with_exit() -> None:
    err = _map_tts_error("espeak", 3, b"")
    assert isinstance(err, ProviderUnavailable)
    assert "3" in str(err)


def test_map_tts_error_multiline_classifies_on_last_line() -> None:
    err = _map_tts_error("piper", 1, b"loading model\nvoice not found")
    assert isinstance(err, ProviderFatal)
    benign_last = _map_tts_error("piper", 1, b"voice not found\nretrying over network")
    assert isinstance(benign_last, ProviderUnavailable)  # last line wins


def test_map_tts_exception_classification() -> None:
    assert isinstance(_map_tts_exception("piper", "piper", FileNotFoundError()), ProviderFatal)
    timeout = subprocess.TimeoutExpired(cmd=["espeak"], timeout=30.0)
    assert isinstance(_map_tts_exception("espeak", "espeak-ng", timeout), ProviderUnavailable)
    assert isinstance(
        _map_tts_exception("espeak", "espeak-ng", OSError("busy")), ProviderUnavailable
    )


# --- argv builders (pure, incl. speed/pitch math) -------------------------------


def test_piper_argv_includes_model_output_and_length_scale() -> None:
    argv = build_piper_argv("piper", Path("/v/en.onnx"), "/tmp/o.wav", speed=2.0)
    assert argv[0] == "piper"
    assert "/v/en.onnx" in argv
    assert argv[argv.index("--output_file") + 1] == "/tmp/o.wav"
    # speed math: length_scale = 1/speed -> 0.5 (in the PURE builder, unit-tested)
    assert float(argv[argv.index("--length_scale") + 1]) == pytest.approx(0.5)


def test_piper_argv_rejects_non_positive_speed() -> None:
    with pytest.raises(ProviderFatal):
        build_piper_argv("piper", Path("/v/en.onnx"), "/tmp/o.wav", speed=0.0)


def test_espeak_argv_maps_voice_speed_pitch() -> None:
    cfg = EspeakTTSConfig(backend="espeak", voice="en-us", speed=2.0, pitch=40)
    argv = build_espeak_argv("espeak-ng", cfg, "/tmp/o.wav")
    assert argv[argv.index("-v") + 1] == "en-us"
    assert argv[argv.index("-s") + 1] == str(round(175 * 2.0))  # 350 wpm
    assert argv[argv.index("-p") + 1] == "40"
    assert argv[argv.index("-w") + 1] == "/tmp/o.wav"
    assert "--stdin" in argv


def test_espeak_argv_rejects_non_positive_speed() -> None:
    cfg = EspeakTTSConfig(backend="espeak", voice="en", speed=0.0)
    with pytest.raises(ProviderFatal):
        build_espeak_argv("espeak-ng", cfg, "/tmp/o.wav")


# --- synthesize orchestration (no real binary) ----------------------------------


def _piper() -> PiperTTS:
    return PiperTTS(
        cfg=PiperTTSConfig(backend="piper", voice="en_US-ryan-high", speed=1.0),
        provider=PiperProviderConfig(binary=Path("/opt/piper"), voices_dir=Path("/v")),
        sample_rate=48_000,
    )


def test_piper_satisfies_tts_protocol() -> None:
    assert isinstance(_piper(), TTSEngine)


def test_piper_without_binary_is_fatal() -> None:
    # H16: piper has no PATH fallback; an unset binary fails loudly at construction.
    with pytest.raises(ProviderFatal):
        PiperTTS(
            cfg=PiperTTSConfig(backend="piper", voice="en", speed=1.0),
            provider=PiperProviderConfig(binary=None, voices_dir=Path("/v")),
        )


async def test_piper_empty_text_returns_zero_silence_at_station_rate() -> None:
    buf = await _piper().synthesize("   ")
    assert buf.frames == 0
    assert buf.sample_rate == 48_000  # H5: station rate even for the empty buffer


async def test_piper_synthesize_resamples_to_station_rate(monkeypatch) -> None:
    # _run_to_buffer yields the voice's native 22.05k; synthesize must resample to 48k (H5).
    # Use a NON-silent buffer + frame-count + energy assertions so an impl that merely rebuilds
    # silence at the station rate (without actually calling to_rate) cannot pass.
    dec = _piper()
    native = wav_bytes_to_buffer(_wav_bytes(rate=22_050, value=16_384, frames=22_050))  # 1s, 0.5 DC
    monkeypatch.setattr(dec, "_run_to_buffer", lambda text: native)
    out = await dec.synthesize("hello")
    assert out.sample_rate == 48_000
    assert abs(out.frames - round(native.frames * 48_000 / 22_050)) <= 1  # really resampled
    assert float(np.sqrt(np.mean(out.samples.astype(np.float64) ** 2))) > 0.4  # energy survived


async def test_piper_missing_binary_at_run_maps_to_fatal(monkeypatch) -> None:
    dec = _piper()

    def _boom(text):
        raise FileNotFoundError("piper")

    monkeypatch.setattr(dec, "_run_to_buffer", _boom)
    with pytest.raises(ProviderFatal):
        await dec.synthesize("hello")


async def test_piper_timeout_maps_to_unavailable(monkeypatch) -> None:
    dec = _piper()

    def _slow(text):
        raise subprocess.TimeoutExpired(cmd=["piper"], timeout=30.0)

    monkeypatch.setattr(dec, "_run_to_buffer", _slow)
    with pytest.raises(ProviderUnavailable):
        await dec.synthesize("hello")


async def test_piper_synthesize_builds_argv_and_forwards_timeout(monkeypatch) -> None:
    # Patch the REAL subprocess.run (exercising _run_to_buffer): the fake writes a WAV to the
    # --output_file path and captures argv/kwargs. Proves argv construction + timeout wiring.
    dec = PiperTTS(
        cfg=PiperTTSConfig(backend="piper", voice="en_US-ryan-high", speed=2.0),
        provider=PiperProviderConfig(binary=Path("/opt/piper"), voices_dir=Path("/voices")),
        sample_rate=48_000,
        timeout_seconds=55.0,
    )
    captured: dict = {}

    def _fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        _write_wav(argv[argv.index("--output_file") + 1], rate=22_050)
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    out = await dec.synthesize("coming up next")
    argv = captured["argv"]
    assert argv[0] == "/opt/piper"
    assert "/voices/en_US-ryan-high.onnx" in argv  # voices_dir/{voice}.onnx
    assert float(argv[argv.index("--length_scale") + 1]) == pytest.approx(0.5)  # 1/speed
    assert captured["kwargs"].get("timeout") == 55.0  # H14
    assert out.sample_rate == 48_000


async def test_piper_nonzero_exit_maps_through_run_to_buffer(monkeypatch) -> None:
    # Exercise the REAL _run_to_buffer returncode!=0 branch (the spy above returns 0): a
    # piper failure stderr is classified by _map_tts_error and surfaces as ProviderError.
    dec = _piper()
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, b"", b"voice not found"),
    )
    with pytest.raises(ProviderFatal):
        await dec.synthesize("hello")


async def test_espeak_nonzero_exit_maps_through_run_to_buffer(monkeypatch) -> None:
    eng = _espeak()
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 5, b"", b"audio device busy"),
    )
    with pytest.raises(ProviderUnavailable):
        await eng.synthesize("hello")


async def test_piper_offloads_to_worker_thread(monkeypatch) -> None:
    import threading

    dec = _piper()
    seen: dict = {}

    def _run(text):
        seen["tid"] = threading.get_ident()
        return AudioBuffer.silence(seconds=0.1, sample_rate=22_050)

    monkeypatch.setattr(dec, "_run_to_buffer", _run)
    await dec.synthesize("hi")
    assert seen["tid"] != threading.get_ident()  # R21: off the event loop


# --- espeak orchestration -------------------------------------------------------


def _espeak() -> EspeakTTS:
    return EspeakTTS(
        cfg=EspeakTTSConfig(backend="espeak", voice="en", speed=1.0, pitch=50),
        provider=EspeakProviderConfig(binary=None),
        sample_rate=48_000,
    )


def test_espeak_satisfies_tts_protocol() -> None:
    assert isinstance(_espeak(), TTSEngine)


def test_espeak_defaults_binary_to_path_lookup() -> None:
    # H15: espeak (unlike piper) allows binary=None and falls back to PATH at run time.
    assert isinstance(_espeak(), EspeakTTS)  # construction with binary=None must not raise


async def test_espeak_empty_text_returns_zero_silence_at_station_rate() -> None:
    buf = await _espeak().synthesize("  ")
    assert buf.frames == 0
    assert buf.sample_rate == 48_000  # H5: station rate even for the empty buffer


async def test_espeak_synthesize_builds_argv_and_forwards_timeout(monkeypatch) -> None:
    # Parity with the piper spy: patch the real subprocess.run, assert espeak argv (-v/-s/-p/-w,
    # --stdin), text fed via stdin, and the configured timeout are all wired through.
    eng = EspeakTTS(
        cfg=EspeakTTSConfig(backend="espeak", voice="en-us", speed=2.0, pitch=40),
        provider=EspeakProviderConfig(binary=None),
        sample_rate=48_000,
        timeout_seconds=12.0,
    )
    captured: dict = {}

    def _fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        _write_wav(argv[argv.index("-w") + 1], rate=22_050)
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    out = await eng.synthesize("hello there")
    argv = captured["argv"]
    assert argv[0] == "espeak-ng"  # binary=None -> PATH default name
    assert argv[argv.index("-v") + 1] == "en-us"
    assert argv[argv.index("-s") + 1] == "350"  # round(175*2.0)
    assert argv[argv.index("-p") + 1] == "40"
    assert "--stdin" in argv
    assert captured["kwargs"].get("input") == b"hello there"  # text fed on stdin
    assert captured["kwargs"].get("timeout") == 12.0
    assert out.sample_rate == 48_000


async def test_espeak_synthesize_resamples_and_is_a_provider_error_on_fail(monkeypatch) -> None:
    eng = _espeak()
    monkeypatch.setattr(
        eng, "_run_to_buffer", lambda t: AudioBuffer.silence(seconds=0.3, sample_rate=22_050)
    )
    out = await eng.synthesize("hello")
    assert out.sample_rate == 48_000

    def _boom(text):
        raise FileNotFoundError("espeak-ng")

    monkeypatch.setattr(eng, "_run_to_buffer", _boom)
    with pytest.raises(ProviderError):  # producer backstops on any ProviderError
        await eng.synthesize("hello")


# --- hardware smoke (excluded from the CI floor) --------------------------------


@pytest.mark.hardware
async def test_espeak_speaks_for_real() -> None:  # pragma: no cover
    eng = EspeakTTS(
        cfg=EspeakTTSConfig(backend="espeak", voice="en", speed=1.0, pitch=50),
        provider=EspeakProviderConfig(binary=None),
        sample_rate=DEFAULT_SAMPLE_RATE,
    )
    buf = await eng.synthesize("Hello from PiRate Radio.")
    assert isinstance(buf, AudioBuffer)
    assert buf.sample_rate == DEFAULT_SAMPLE_RATE
    assert buf.frames > 0
