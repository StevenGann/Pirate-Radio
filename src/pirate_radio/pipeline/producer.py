"""Producer: render each schedule item just ahead of the playhead (§5.3).

A ``track`` is rendered by the decoder, patter (station_id / block_transition /
block_reminder) by the TTS engine. P1 (no-drop): every item produces exactly one segment,
in order. R11/R15: a backend ``ProviderError`` does NOT crash or drop the item — the
producer substitutes the canned backstop (and logs) so the player always has audio. (The
retryable-vs-terminal failover wrapper is Phase 3; Phase 1 backstops any ProviderError.)
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from pirate_radio.audio.buffer import AudioBuffer
from pirate_radio.audio.decode import Decoder
from pirate_radio.dj.protocols import TTSEngine
from pirate_radio.errors import ProviderError
from pirate_radio.pipeline.buffer import LookAheadBuffer
from pirate_radio.pipeline.segment import RenderedSegment
from pirate_radio.schedule.models import (
    BlockReminderItem,
    BlockTransitionItem,
    ScheduleItem,
    StationIdItem,
    TrackItem,
)

logger = logging.getLogger(__name__)

_STATION = "PiRate Radio"


def announcement_text(item: ScheduleItem) -> str:
    """The words the TTS engine speaks for a patter item (Phase-1 template, no LLM).

    A ``track`` never goes through TTS, so it has no announcement text.
    """
    if isinstance(item, StationIdItem):
        return f"You're listening to {item.block_name} on {_STATION}."
    if isinstance(item, BlockReminderItem):
        return f"You're still tuned to {item.block_name} here on {_STATION}."
    if isinstance(item, BlockTransitionItem):
        return f"Coming up next: {item.next_block_name}."
    raise ValueError(f"no announcement text for item kind {item.kind!r}")  # TrackItem


class Producer:
    def __init__(
        self,
        *,
        items: Sequence[ScheduleItem],
        tts: TTSEngine,
        decoder: Decoder,
        buffer: LookAheadBuffer,
        backstop: AudioBuffer,
    ) -> None:
        self._items = items
        self._tts = tts
        self._decoder = decoder
        self._buffer = buffer
        self._backstop = backstop

    async def run(self) -> None:
        for item in self._items:
            try:
                audio = await self._render(item)
            except ProviderError as exc:
                logger.warning(
                    "render failed for %s item (%s) -> backstop (R11/R15)", item.kind, exc
                )
                audio = self._backstop
            await self._buffer.put(RenderedSegment(item=item, audio=audio))

    async def _render(self, item: ScheduleItem) -> AudioBuffer:
        if isinstance(item, TrackItem):
            return await self._decoder.decode(item.track)
        return await self._tts.synthesize(announcement_text(item))
