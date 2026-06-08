"""``SoundDeviceSink`` — the real AudioSink (R20: the only new Phase-4 hardware).

Gapless playback (§10) via a **persistent** ``sd.OutputStream`` opened once per station and
written to per buffer; ``play`` awaits the write so it returns only when the buffer is fully
consumed. The blocking PortAudio write is hopped onto a **dedicated single-thread executor** (one
per sink), isolated from the shared decode/normalize ``to_thread`` pool so playback can't starve
compute (RPi/DA-M1). A PortAudio glitch/xrun (``PortAudioError``) is a **logged glitch** the stream
recovers from (the buffer is dropped, the next write lands) — NOT a crash; any other error
propagates to the supervisor. The stream and the executor are torn down in ``finally`` (async
context manager) so a crash-loop can't leak streams or threads.

R20: ONLY the lazy ``import sounddevice`` + ``sd.OutputStream`` construction is hardware
(``pragma: no cover``); the whole orchestration is unit-tested against an injected stream factory.
R21: ``sounddevice`` is never imported at module scope.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np

from pirate_radio.audio.buffer import AudioBuffer

logger = logging.getLogger(__name__)

# Explicit device latency (§G: ~80–150 ms headroom so a contended Pi doesn't xrun). blocksize 0
# lets PortAudio pick an optimal frame count for that latency. These reach only the real
# sd.OutputStream (hardware, pragma'd).
_DEFAULT_LATENCY_SECONDS = 0.1
_DEFAULT_BLOCKSIZE = 0


class SoundDeviceSink:
    """AudioSink over a persistent ``sd.OutputStream``. Use as an ``async with`` block."""

    def __init__(
        self,
        *,
        sample_rate: int,
        channels: int,
        device: str | int,  # PortAudio device: an index (preferred, from the resolver) or a name
        blocksize: int = _DEFAULT_BLOCKSIZE,
        latency: float = _DEFAULT_LATENCY_SECONDS,
        stream_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._sample_rate = sample_rate
        self._channels = channels
        self._device = device
        self._blocksize = blocksize
        self._latency = latency
        self._stream_factory = stream_factory or self._default_stream_factory
        self._stream: Any | None = None
        self._executor: ThreadPoolExecutor | None = None

    def _default_stream_factory(self) -> Any:
        import sounddevice as sd  # pragma: no cover  (R21: lazy; only on real hardware)

        return sd.OutputStream(  # pragma: no cover  (R20: the ONLY hardware construction)
            samplerate=self._sample_rate,
            channels=self._channels,
            dtype="float32",
            blocksize=self._blocksize,
            latency=self._latency,
            device=self._device,
        )

    async def __aenter__(self) -> SoundDeviceSink:
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=f"sink-{self._device}"
        )
        self._stream = self._stream_factory()
        self._stream.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
        finally:
            if self._executor is not None:
                self._executor.shutdown(wait=True)  # join the dedicated worker — no thread leak

    async def play(self, buf: AudioBuffer) -> None:
        if self._stream is None or self._executor is None:
            raise RuntimeError("SoundDeviceSink.play before the stream is started (use async with)")
        if buf.frames == 0:
            return  # empty buffer -> nothing to consume (defensive; producer guards 0-frame)
        if buf.channels != self._channels:
            raise ValueError(
                f"sink channel mismatch: buffer has {buf.channels}, sink is {self._channels}"
            )
        if buf.sample_rate != self._sample_rate:
            raise ValueError(
                f"sink sample rate mismatch: buffer {buf.sample_rate}, sink {self._sample_rate}"
            )
        samples = np.ascontiguousarray(
            buf.samples, dtype=np.float32
        )  # real PortAudio needs C-order
        loop = asyncio.get_running_loop()
        try:
            # await: play returns ONLY when the write is fully consumed (§10 gapless contract).
            await loop.run_in_executor(self._executor, self._stream.write, samples)
        except Exception as exc:  # noqa: BLE001 — classify glitch-vs-real below
            if type(exc).__name__ == "PortAudioError":
                # an xrun/underflow is a degraded glitch, not dead air and not a crash: drop this
                # buffer, log, and keep the stream — the next write recovers (§G xrun policy).
                logger.warning(
                    "audio xrun/underflow glitch on %s (%s) -> buffer dropped, stream recovered",
                    self._device,
                    exc,
                )
                return
            raise  # a real stream error propagates to the supervisor (advance-past-poison)
