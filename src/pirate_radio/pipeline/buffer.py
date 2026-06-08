"""LookAheadBuffer: a bounded queue between the producer and the player (§5.3).

Depth 1-2 is enough. The producer blocks on a full queue (back-pressure — a slow render
stalls REFILL, never playback). The player pulls non-blocking via ``get_nowait`` and
decides the R11 backstop itself (it owns the refill deadline through the Sleeper seam),
so the buffer carries no timeout policy.
"""

from __future__ import annotations

import asyncio

from pirate_radio.pipeline.segment import RenderedSegment


class LookAheadBuffer:
    def __init__(self, *, maxsize: int = 2) -> None:
        self._q: asyncio.Queue[RenderedSegment] = asyncio.Queue(maxsize=maxsize)

    async def put(self, seg: RenderedSegment) -> None:
        """Enqueue a segment, blocking while the queue is full (back-pressure)."""
        await self._q.put(seg)

    def get_nowait(self) -> RenderedSegment | None:
        """Pop the next segment, or ``None`` if the queue is currently empty."""
        try:
            return self._q.get_nowait()
        except asyncio.QueueEmpty:
            return None

    @property
    def depth(self) -> int:
        return self._q.qsize()

    @property
    def maxsize(self) -> int:
        return self._q.maxsize
