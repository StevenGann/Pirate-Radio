"""RED tests for ``pirate_radio.audio.sink`` — Phase 4 plan §G / P4-1.

Tests first (strict spec-driven TDD): the real ``SoundDeviceSink`` (the AudioSink Protocol).
Gapless persistent ``sd.OutputStream`` opened once; ``play`` returns only when the write is fully
consumed (§10); the write is hopped onto a DEDICATED single-thread executor (isolated from the
shared decode/normalize pool — RPi/DA-M1); a PortAudio glitch (xrun) is a LOGGED GLITCH the
stream recovers from, NOT a crash; the stream + its executor are torn down in ``finally`` so a
crash-loop can't leak streams/threads. R20: only the literal ``sounddevice`` import + stream
construct/write is hardware — everything here is tested against an injected fake; R21:
``sounddevice`` is never imported at module scope.
"""

from __future__ import annotations

import ast
import asyncio
import logging
import threading
from pathlib import Path

import numpy as np
import pytest

from pirate_radio.audio.buffer import DEFAULT_SAMPLE_RATE, AudioBuffer
from pirate_radio.audio.sink import SoundDeviceSink
from pirate_radio.dj.protocols import AudioSink

_SRC = Path(__file__).resolve().parents[2] / "src" / "pirate_radio"


class PortAudioError(Exception):
    """Stand-in for ``sounddevice.PortAudioError`` — the REAL class sounddevice raises (matched
    by name, no sd import). A glitch/xrun surfaces as this; the sink logs + recovers."""


class _FakeOutputStream:
    """Mirrors the sd.OutputStream surface the sink uses: start/write/stop/close."""

    def __init__(self, *, glitch_on: int | None = None, error_on: int | None = None) -> None:
        self.written: list = []
        self.started = False
        self.stopped = False
        self.closed = False
        self.write_threads: list[int] = []
        self._glitch_on = glitch_on  # raise a PortAudioError (xrun) on the Nth write (1-based)
        self._error_on = error_on  # raise a non-PortAudio error on the Nth write
        self._n = 0

    def start(self) -> None:
        self.started = True

    def write(self, data) -> None:  # noqa: ANN001
        self._n += 1
        self.write_threads.append(threading.get_ident())
        if self._glitch_on == self._n:
            raise PortAudioError("output underflow")
        if self._error_on == self._n:
            raise RuntimeError("a real, non-recoverable stream error")
        self.written.append(data)

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


def _sink(stream: _FakeOutputStream, **kw) -> SoundDeviceSink:
    return SoundDeviceSink(
        sample_rate=DEFAULT_SAMPLE_RATE,
        channels=1,
        device="hw:CARD=usb1",
        stream_factory=lambda: stream,  # inject the fake; the real default builds sd.OutputStream
        **kw,
    )


def _buf(seconds: float = 0.1) -> AudioBuffer:
    return AudioBuffer.silence(seconds=seconds, sample_rate=DEFAULT_SAMPLE_RATE, channels=1)


# ---- Protocol + basic play -----------------------------------------------------------------
def test_sink_satisfies_audiosink_protocol() -> None:
    assert isinstance(_sink(_FakeOutputStream()), AudioSink)


async def test_play_writes_buffer_to_the_stream() -> None:
    fake = _FakeOutputStream()
    async with _sink(fake) as sink:
        await sink.play(_buf(0.1))
    assert len(fake.written) == 1
    written = fake.written[0]
    assert written.dtype.name == "float32" and written.shape[1] == 1


# ---- gapless: ONE persistent stream, opened once -------------------------------------------
async def test_stream_opened_once_across_many_plays() -> None:
    fake = _FakeOutputStream()
    async with _sink(fake) as sink:
        await sink.play(_buf(0.1))
        await sink.play(_buf(0.1))
        await sink.play(_buf(0.1))
    assert fake.started is True
    assert len(fake.written) == 3  # all three to the SAME stream (persistent, §10 gapless)


# ---- §10: play returns ONLY after the write is fully consumed (no fire-and-forget) ---------
async def test_play_blocks_until_write_completes() -> None:
    release = threading.Event()
    entered = threading.Event()

    class _BlockingStream(_FakeOutputStream):
        def write(self, data) -> None:  # noqa: ANN001
            self.write_threads.append(threading.get_ident())
            entered.set()
            assert release.wait(2.0)  # block until the test releases
            self.written.append(data)

    fake = _BlockingStream()
    async with _sink(fake) as sink:
        task = asyncio.create_task(sink.play(_buf(0.1)))
        await asyncio.to_thread(entered.wait, 2.0)  # the write has begun (off the loop)
        assert not task.done()  # play has NOT returned — it awaits full consumption (§10)
        release.set()
        await task
    assert len(fake.written) == 1


# ---- dedicated, ISOLATED executor (not the shared default to_thread pool) ------------------
async def test_writes_run_on_one_dedicated_worker_thread() -> None:
    fake = _FakeOutputStream()
    main = threading.get_ident()
    default_pool_ident = await asyncio.to_thread(threading.get_ident)  # a default-pool worker
    async with _sink(fake) as sink:
        await sink.play(_buf(0.1))
        await sink.play(_buf(0.1))
        await sink.play(_buf(0.1))
    assert len(set(fake.write_threads)) == 1  # ONE dedicated worker for all writes
    assert fake.write_threads[0] != main  # off the event loop (R23)
    assert fake.write_threads[0] != default_pool_ident  # NOT the shared default pool (RPi/DA-M1)


async def test_dedicated_executor_thread_joined_on_exit() -> None:
    fake = _FakeOutputStream()
    async with _sink(fake) as sink:
        await sink.play(_buf(0.1))
    worker = fake.write_threads[0]
    assert worker not in {t.ident for t in threading.enumerate()}  # shutdown(wait=True), no leak


# ---- lifecycle: stream closed in finally, even on error -----------------------------------
async def test_stream_closed_on_context_exit() -> None:
    fake = _FakeOutputStream()
    async with _sink(fake) as sink:
        await sink.play(_buf(0.1))
    assert fake.closed is True


async def test_stream_closed_even_when_play_raises() -> None:
    fake = _FakeOutputStream(error_on=1)
    with pytest.raises(RuntimeError):
        async with _sink(fake) as sink:
            await sink.play(_buf(0.1))
    assert fake.closed is True  # finally-close: a crash can't leak the stream/thread


# ---- xrun: a PortAudioError is a logged glitch, recovered in-stream ------------------------
async def test_portaudio_glitch_is_logged_and_recovered(caplog) -> None:
    fake = _FakeOutputStream(glitch_on=1)
    with caplog.at_level(logging.WARNING):
        async with _sink(fake) as sink:
            await sink.play(_buf(0.1))  # glitches — must NOT raise
            await sink.play(_buf(0.1))  # stream recovers; this write lands
    assert any(
        "underflow" in r.message.lower()
        or "xrun" in r.message.lower()
        or "glitch" in r.message.lower()
        for r in caplog.records
    )
    assert len(fake.written) == 1  # the glitched buffer dropped, the next one written (recovery)


async def test_non_portaudio_error_propagates() -> None:
    # a real (non-PortAudio) error is NOT swallowed -> the supervisor sees it (advance-past-poison)
    fake = _FakeOutputStream(error_on=1)
    with pytest.raises(RuntimeError):
        async with _sink(fake) as sink:
            await sink.play(_buf(0.1))


# ---- format: coercion + desync guards -----------------------------------------------------
async def test_noncontiguous_buffer_coerced_to_contiguous() -> None:
    # a sliced view (e.g. from the §B seek-trim) is non-C-contiguous; real PortAudio needs
    # contiguous memory, so the sink must coerce before write.
    view = np.zeros((20, 2), dtype=np.float32)[:, 0:1]  # shape (20,1), NOT C-contiguous
    assert not view.flags["C_CONTIGUOUS"]
    buf = AudioBuffer(view, DEFAULT_SAMPLE_RATE, 1)
    fake = _FakeOutputStream()
    async with _sink(fake) as sink:
        await sink.play(buf)
    assert fake.written[0].flags["C_CONTIGUOUS"]


async def test_channel_mismatch_is_rejected() -> None:
    fake = _FakeOutputStream()
    stereo = AudioBuffer.silence(seconds=0.1, sample_rate=DEFAULT_SAMPLE_RATE, channels=2)
    with pytest.raises(ValueError, match="channel"):
        async with _sink(fake) as sink:
            await sink.play(stereo)


async def test_sample_rate_mismatch_is_rejected() -> None:
    fake = _FakeOutputStream()
    wrong = AudioBuffer.silence(seconds=0.1, sample_rate=22_050, channels=1)
    with pytest.raises(ValueError, match="rate"):
        async with _sink(fake) as sink:
            await sink.play(wrong)


async def test_zero_frame_buffer_is_a_noop() -> None:
    fake = _FakeOutputStream()
    async with _sink(fake) as sink:
        await sink.play(
            AudioBuffer.silence(seconds=0.0, sample_rate=DEFAULT_SAMPLE_RATE, channels=1)
        )
    assert fake.written == []  # empty buffer -> nothing written, no error


async def test_play_before_start_raises() -> None:
    # defensive: play() before entering the async-with (stream not opened) is a loud error
    sink = _sink(_FakeOutputStream())
    with pytest.raises(RuntimeError, match="started"):
        await sink.play(_buf(0.1))


# ---- R21: no module-scope sounddevice import ----------------------------------------------
def test_no_module_scope_sounddevice_import() -> None:
    tree = ast.parse((_SRC / "audio" / "sink.py").read_text())
    for node in tree.body:
        roots: list[str] = []
        if isinstance(node, ast.Import):
            roots = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            roots = [(node.module or "").split(".")[0]]
        assert "sounddevice" not in roots, "sounddevice must be imported lazily (R21)"
