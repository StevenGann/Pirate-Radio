"""Player: drain the look-ahead buffer to the sink, gaplessly, with the R11 backstop.

For each of ``count`` items the player pulls the next rendered segment. If the buffer is
momentarily empty it waits one refill budget (via the Sleeper seam); if it is STILL empty
it airs the canned backstop to avoid dead air and waits again — repeating until the real
segment arrives. The backstop is **gap-fill only**: it never advances the item cursor, so
the slow item still plays, in order, and is never dropped (plan must-fix P1). The
inter-element transition silence (§10) follows each played element.
"""

from __future__ import annotations

import asyncio
import logging

from pirate_radio.audio.buffer import AudioBuffer
from pirate_radio.dj.protocols import AudioSink
from pirate_radio.pipeline.buffer import LookAheadBuffer
from pirate_radio.pipeline.timing import Sleeper

logger = logging.getLogger(__name__)


class Player:
    def __init__(
        self,
        *,
        buffer: LookAheadBuffer,
        sink: AudioSink,
        sleeper: Sleeper,
        backstop: AudioBuffer,
        refill_budget_seconds: float,
        transition_silence: float = 0.0,
        skip: asyncio.Event | None = None,
    ) -> None:
        self._buffer = buffer
        self._sink = sink
        self._sleeper = sleeper
        self._backstop = backstop
        self._budget = refill_budget_seconds
        self._silence = transition_silence
        self._skip = (
            skip  # control-API skip-at-next-boundary (P6-3): drops the next item, then clears
        )

    async def run(self, *, count: int) -> None:
        for _ in range(count):
            backstops = 0  # consecutive gap-fill backstops before this item aired
            seg = self._buffer.get_nowait()
            if seg is None:  # momentary miss: give the producer one budget to deliver
                await self._sleeper.sleep(self._budget)
                seg = self._buffer.get_nowait()
            while seg is None:  # real underrun: gap-fill with backstop, keep waiting (R11)
                logger.warning(
                    "refill missed %.2fs budget -> backstop gap-fill (R11)", self._budget
                )
                await self._sink.play(self._backstop)
                backstops += 1
                await self._sleeper.sleep(self._budget)
                seg = self._buffer.get_nowait()
            if backstops:  # operator visibility (H14): normal audio recovered after an underrun
                logger.info("normal audio resumed after %d backstop gap-fill(s)", backstops)
            if self._skip is not None and self._skip.is_set():  # P6-3: skip-at-next-boundary
                self._skip.clear()  # one-shot: this single item is dropped, not the rest
                logger.info("skip: dropping %s and advancing to the next item", seg.item.kind)
                continue  # consumed but not played -> the next iteration airs the following item
            await self._sink.play(seg.audio)  # the real item always airs (P1: never dropped)
            if self._silence > 0:  # §10 inter-element transition silence
                await self._sink.play(
                    AudioBuffer.silence(
                        seconds=self._silence,
                        sample_rate=self._backstop.sample_rate,
                        channels=self._backstop.channels,
                    )
                )
