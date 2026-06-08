"""Look-ahead playback pipeline (§5.3): producer renders ahead, player drains to the sink.

``run_once`` is the Phase-1 harness wiring a Producer and Player over a pre-selected list
of schedule items (concurrent, back-pressured, R11-backstopped). Selecting those items
from a ``DailySchedule`` via ``find_now`` — the full daily vertical slice — is the
coordinator's job (Phase 4); this package owns only the render→buffer→play mechanics.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from pirate_radio.audio.buffer import AudioBuffer
from pirate_radio.audio.decode import Decoder
from pirate_radio.dj.protocols import AudioSink, TTSEngine
from pirate_radio.pipeline.buffer import LookAheadBuffer
from pirate_radio.pipeline.player import Player
from pirate_radio.pipeline.producer import Producer
from pirate_radio.pipeline.segment import RenderedSegment
from pirate_radio.pipeline.timing import RealSleeper, Sleeper, VirtualSleeper
from pirate_radio.schedule.models import ScheduleItem

__all__ = [
    "LookAheadBuffer",
    "Player",
    "Producer",
    "RealSleeper",
    "RenderedSegment",
    "Sleeper",
    "VirtualSleeper",
    "run_once",
]


async def run_once(
    *,
    items: Sequence[ScheduleItem],
    tts: TTSEngine,
    decoder: Decoder,
    sink: AudioSink,
    backstop: AudioBuffer,
    sleeper: Sleeper,
    refill_budget_seconds: float,
    transition_silence: float = 0.0,
    maxsize: int = 2,
) -> None:
    """Render and play ``items`` once, producer and player running concurrently.

    Returns when every item has aired. Nothing is dropped (P1); a slow/failed render is
    covered by the producer substitution and the player backstop, never dead air (R11).
    """
    buffer = LookAheadBuffer(maxsize=maxsize)
    producer = Producer(items=items, tts=tts, decoder=decoder, buffer=buffer, backstop=backstop)
    player = Player(
        buffer=buffer,
        sink=sink,
        sleeper=sleeper,
        backstop=backstop,
        refill_budget_seconds=refill_budget_seconds,
        transition_silence=transition_silence,
    )
    await asyncio.gather(producer.run(), player.run(count=len(items)))
