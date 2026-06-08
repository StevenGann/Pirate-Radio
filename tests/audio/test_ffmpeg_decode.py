"""RED tests for ``pirate_radio.audio.decode.FfmpegDecoder`` — Phase 2 plan §4.3 (R22).

Tests first. The real decoder shells out to ffmpeg, but ALL logic is pure and CI-covered:
argv construction, the f32le PCM parser (with frame-alignment guards), the stderr→error
map, and the subprocess-exception map. The async ``decode`` orchestration is exercised by
monkeypatching the thin ``_run`` shell — no real ffmpeg in the CI floor. A real-binary
smoke test is ``@pytest.mark.hardware`` (excluded from CI).

Pinned: argv has -ar/-ac/-f f32le/-; golden f32le bytes → correct AudioBuffer (endian);
empty / non-4-multiple / non-frame-aligned PCM → ProviderFatal (NOT a bare ValueError that
would escape the producer and dead-air); missing binary → ProviderFatal; timeout →
ProviderUnavailable; nonzero exit → Fatal (bad file) vs Unavailable (default); H12: a
corrupt file maps to ProviderError so the producer backstops, never crashes.
"""

from __future__ import annotations

import struct
import subprocess
from pathlib import Path

import numpy as np
import pytest

from pirate_radio.audio.buffer import DEFAULT_SAMPLE_RATE, AudioBuffer
from pirate_radio.audio.decode import (
    Decoder,
    FfmpegDecoder,
    build_ffmpeg_argv,
    map_ffmpeg_error,
    map_subprocess_exception,
    parse_pcm_f32le,
)
from pirate_radio.catalog.models import Track
from pirate_radio.errors import ProviderError, ProviderFatal, ProviderUnavailable

_TRACK = Track(path=Path("/lib/classical/x.flac"), group="classical", duration=12.5)


def _cp(returncode: int, stdout: bytes = b"", stderr: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["ffmpeg"], returncode=returncode, stdout=stdout, stderr=stderr
    )


# --- build_ffmpeg_argv (pure) ----------------------------------------------------


def test_argv_requests_f32le_at_station_rate_and_channels() -> None:
    argv = build_ffmpeg_argv("ffmpeg", "/lib/x.flac", sample_rate=48_000, channels=1)
    assert argv[0] == "ffmpeg"
    assert "-i" in argv and "/lib/x.flac" in argv
    assert argv[argv.index("-ar") + 1] == "48000"  # H5: ffmpeg-side resample
    assert argv[argv.index("-ac") + 1] == "1"  # Q6: mono v1
    assert argv[argv.index("-f") + 1] == "f32le"  # Q1: raw float32 LE
    assert argv[-1] == "-"  # stdout


# --- parse_pcm_f32le (pure) — golden + alignment guards --------------------------


def test_parse_golden_single_sample_endianness() -> None:
    raw = struct.pack("<f", 0.5)  # one mono f32le sample
    buf = parse_pcm_f32le(raw, sample_rate=48_000, channels=1)
    assert buf.samples.shape == (1, 1)
    assert abs(float(buf.samples[0, 0]) - 0.5) < 1e-7


def test_parse_multi_frame_stereo_interleaving() -> None:
    raw = struct.pack("<4f", 0.1, -0.2, 0.3, -0.4)  # 2 frames, 2 channels interleaved
    buf = parse_pcm_f32le(raw, sample_rate=48_000, channels=2)
    assert buf.samples.shape == (2, 2)
    assert np.allclose(buf.samples, [[0.1, -0.2], [0.3, -0.4]], atol=1e-7)
    assert buf.samples.dtype == np.float32


def test_parse_empty_pcm_is_fatal() -> None:
    with pytest.raises(ProviderFatal):
        parse_pcm_f32le(b"", sample_rate=48_000, channels=1)


def test_parse_non_multiple_of_4_is_fatal() -> None:
    # 3 bytes: not even a whole float32 — would be a bare ValueError in np.frombuffer.
    with pytest.raises(ProviderFatal):
        parse_pcm_f32le(b"\x00\x00\x00", sample_rate=48_000, channels=1)


def test_parse_whole_samples_but_not_whole_frames_is_fatal() -> None:
    # 4 bytes = one float32 sample, but channels=2 needs 8-byte frames.
    with pytest.raises(ProviderFatal):
        parse_pcm_f32le(struct.pack("<f", 0.5), sample_rate=48_000, channels=2)


def test_parse_zero_channels_is_fatal() -> None:
    with pytest.raises(ProviderFatal):
        parse_pcm_f32le(struct.pack("<f", 0.5), sample_rate=48_000, channels=0)


# --- map_ffmpeg_error (pure) -----------------------------------------------------


@pytest.mark.parametrize(
    "stderr", ["No such file or directory", "Invalid data found", "does not contain"]
)
def test_decode_errors_map_to_fatal(stderr: str) -> None:
    assert isinstance(map_ffmpeg_error(1, stderr), ProviderFatal)


def test_unknown_stderr_maps_to_unavailable() -> None:
    assert isinstance(map_ffmpeg_error(69, "Connection reset by peer"), ProviderUnavailable)


def test_empty_stderr_maps_to_unavailable_with_exit_code() -> None:
    err = map_ffmpeg_error(1, "")
    assert isinstance(err, ProviderUnavailable)
    assert "1" in str(err)  # falls back to the exit code


def test_multiline_stderr_classifies_on_last_line() -> None:
    err = map_ffmpeg_error(1, "ffmpeg version 6.1\nsome preamble\nNo such file or directory")
    assert isinstance(err, ProviderFatal)


def test_classification_uses_last_line_not_first() -> None:
    # First line matches a fatal pattern but the LAST line does not -> Unavailable. Pins
    # "last line wins" against a first-line-matching impl (which would wrongly say Fatal).
    err = map_ffmpeg_error(1, "No such file or directory\nbut actually: connection reset")
    assert isinstance(err, ProviderUnavailable)


# --- map_subprocess_exception (pure) ---------------------------------------------


def test_missing_binary_maps_to_fatal() -> None:
    assert isinstance(map_subprocess_exception("ffmpeg", FileNotFoundError()), ProviderFatal)


def test_timeout_maps_to_unavailable() -> None:
    exc = subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=120.0)
    assert isinstance(map_subprocess_exception("ffmpeg", exc), ProviderUnavailable)


def test_other_subprocess_exception_maps_to_unavailable() -> None:
    # An unexpected OSError (e.g. a transient I/O error spawning the process) is retryable.
    assert isinstance(
        map_subprocess_exception("ffmpeg", OSError("resource busy")), ProviderUnavailable
    )


# --- decode() orchestration (monkeypatched _run; no real ffmpeg) -----------------


def test_ffmpeg_decoder_satisfies_protocol() -> None:
    assert isinstance(FfmpegDecoder(), Decoder)


async def test_decode_success_returns_audiobuffer(monkeypatch) -> None:
    dec = FfmpegDecoder(sample_rate=48_000, channels=1)
    pcm = struct.pack("<3f", 0.1, 0.2, 0.3)  # 3 mono frames
    monkeypatch.setattr(dec, "_run", lambda argv: _cp(0, stdout=pcm))
    buf = await dec.decode(_TRACK)
    assert isinstance(buf, AudioBuffer)
    assert buf.sample_rate == 48_000 and buf.channels == 1
    assert buf.frames == 3


async def test_decode_nonzero_exit_raises_mapped_error(monkeypatch) -> None:
    dec = FfmpegDecoder()
    monkeypatch.setattr(dec, "_run", lambda argv: _cp(1, stderr=b"No such file or directory"))
    with pytest.raises(ProviderFatal):  # H12: corrupt/missing file -> producer backstops
        await dec.decode(_TRACK)


async def test_decode_missing_binary_raises_fatal(monkeypatch) -> None:
    dec = FfmpegDecoder(binary="nonexistent-ffmpeg")

    def _boom(argv):
        raise FileNotFoundError("nonexistent-ffmpeg")

    monkeypatch.setattr(dec, "_run", _boom)
    with pytest.raises(ProviderFatal):
        await dec.decode(_TRACK)


async def test_decode_timeout_raises_unavailable_discarding_partial_output(monkeypatch) -> None:
    # A real TimeoutExpired carries the partial bytes captured before the kill; decode must
    # map to ProviderUnavailable and NEVER feed that ragged partial PCM to the parser.
    dec = FfmpegDecoder(timeout_seconds=0.01)

    def _slow(argv):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=0.01, output=b"\x01\x02\x03")

    monkeypatch.setattr(dec, "_run", _slow)
    with pytest.raises(ProviderUnavailable):
        await dec.decode(_TRACK)


async def test_decode_non_utf8_stderr_is_replaced_not_crashed(monkeypatch) -> None:
    # ffmpeg stderr is not guaranteed UTF-8; decode must decode with errors="replace" so a
    # bad byte can't escape as a raw UnicodeDecodeError (which would crash the producer).
    dec = FfmpegDecoder()
    monkeypatch.setattr(dec, "_run", lambda argv: _cp(1, stderr=b"\xff\xfe No such file\xff"))
    with pytest.raises(ProviderFatal):
        await dec.decode(_TRACK)


async def test_decode_builds_argv_and_forwards_timeout_to_subprocess(monkeypatch) -> None:
    # Patch the REAL subprocess.run (exercising _run) to prove decode() builds the argv from
    # the station settings and forwards the timeout + flags — a hardcoded/wrong-argv impl fails.
    dec = FfmpegDecoder(binary="ff", sample_rate=44_100, channels=2, timeout_seconds=77.0)
    captured: dict = {}

    def _fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return _cp(0, stdout=struct.pack("<2f", 0.0, 0.0))  # one stereo frame

    monkeypatch.setattr(subprocess, "run", _fake_run)
    await dec.decode(_TRACK)
    argv = captured["argv"]
    assert argv[0] == "ff"
    assert str(_TRACK.path) in argv  # the path is a single argv element (list, not a shell string)
    assert argv[argv.index("-ar") + 1] == "44100"
    assert argv[argv.index("-ac") + 1] == "2"
    assert argv[argv.index("-f") + 1] == "f32le"
    assert captured["kwargs"].get("timeout") == 77.0  # H14: the configured timeout is forwarded
    assert captured["kwargs"].get("capture_output") is True
    assert captured["kwargs"].get("check") is False


async def test_decode_path_with_spaces_stays_one_argv_element(monkeypatch) -> None:
    dec = FfmpegDecoder()
    spaced = Track(path=Path("/lib/my album/track 01.flac"), group="g", duration=10.0)
    captured: dict = {}

    def _fake_run(argv, **kwargs):
        captured["argv"] = argv
        return _cp(0, stdout=struct.pack("<f", 0.0))

    monkeypatch.setattr(subprocess, "run", _fake_run)
    await dec.decode(spaced)
    assert "/lib/my album/track 01.flac" in captured["argv"]  # verbatim, not split on spaces


async def test_decode_offloads_subprocess_to_a_worker_thread(monkeypatch) -> None:
    # R21/R23: the blocking subprocess MUST run via asyncio.to_thread, off the event loop.
    # A sync-on-loop impl would run _run on the main thread -> dead-air risk on the Pi.
    import threading

    dec = FfmpegDecoder()
    seen: dict = {}

    def _run(argv):
        seen["tid"] = threading.get_ident()
        return _cp(0, stdout=struct.pack("<f", 0.0))

    monkeypatch.setattr(dec, "_run", _run)
    await dec.decode(_TRACK)
    assert seen["tid"] != threading.get_ident()  # ran in a worker thread, not the loop


async def test_decode_error_is_a_provider_error(monkeypatch) -> None:
    # Every decode failure is a ProviderError subclass — so the producer's `except
    # ProviderError` always catches it and fires the R11 backstop (never a raw crash).
    dec = FfmpegDecoder()
    monkeypatch.setattr(dec, "_run", lambda argv: _cp(1, stderr=b"Invalid data found"))
    with pytest.raises(ProviderError):
        await dec.decode(_TRACK)


# --- hardware smoke (excluded from the CI floor) ---------------------------------


@pytest.mark.hardware
async def test_ffmpeg_decodes_a_real_wav(tmp_path) -> None:  # pragma: no cover
    import wave

    p = tmp_path / "tone.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44_100)
        w.writeframes(b"\x00\x00" * 44_100)  # 1s silence
    buf = await FfmpegDecoder(sample_rate=DEFAULT_SAMPLE_RATE, channels=1).decode(
        Track(path=p, group="g", duration=1.0)
    )
    assert isinstance(buf, AudioBuffer)
    assert buf.sample_rate == DEFAULT_SAMPLE_RATE
    assert abs(buf.duration_seconds - 1.0) < 0.05
