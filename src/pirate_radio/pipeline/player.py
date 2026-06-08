"""Player: drain the look-ahead buffer to the sink, gaplessly, with the R11 backstop.

For each of ``count`` items the player pulls the next rendered segment. If the buffer is
momentarily empty it waits one refill budget (via the Sleeper seam); if it is STILL empty
it airs the canned backstop to avoid dead air and waits again — repeating until the real
segment arrives. The backstop is **gap-fill only**: it never advances the item cursor, so
the slow item still plays, in order, and is never dropped (plan must-fix P1). The
inter-element transition silence (§10) follows each played element.
"""

from __future__ import annotations

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
    ) -> None:
        self._buffer = buffer
        self._sink = sink
        self._sleeper = sleeper
        self._backstop = backstop
        self._budget = refill_budget_seconds
        self._silence = transition_silence

    async def run(self, *, count: int) -> None:
        for _ in range(count):
            seg = self._buffer.get_nowait()
            if seg is None:  # momentary miss: give the producer one budget to deliver
                await self._sleeper.sleep(self._budget)
                seg = self._buffer.get_nowait()
            while seg is None:  # real underrun: gap-fill with backstop, keep waiting (R11)
                logger.warning(
                    "refill missed %.2fs budget -> backstop gap-fill (R11)", self._budget
                )
                await self._sink.play(self._backstop)
                await self._sleeper.sleep(self._budget)
                seg = self._buffer.get_nowait()
            await self._sink.play(seg.audio)  # the real item always airs (P1: never dropped)
            if self._silence > 0:  # §10 inter-element transition silence
                await self._sink.play(
                    AudioBuffer.silence(
                        seconds=self._silence,
                        sample_rate=self._backstop.sample_rate,
                        channels=self._backstop.channels,
                    )
                )
