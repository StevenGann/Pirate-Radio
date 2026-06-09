"""Look-ahead playback pipeline (§5.3): producer renders ahead, player drains to the sink.

``run_once`` is the Phase-1 harness wiring a Producer and Player over a pre-selected list
of schedule items (concurrent, back-pressured, R11-backstopped). Selecting those items
from a ``DailySchedule`` via ``find_now`` — the full daily vertical slice — is the
coordinator's job (Phase 4); this package owns only the render→buffer→play mechanics.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from pirate_radio.audio.buffer import DEFAULT_SAMPLE_RATE, AudioBuffer
from pirate_radio.audio.decode import Decoder
from pirate_radio.dj.protocols import AudioSink, TextGenerator, TTSEngine
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


def _assert_station_format(*, backstop: AudioBuffer, sample_rate: int, channels: int) -> None:
    """C4/H5: the backstop, every segment, and the transition silence must share ONE station
    (sample_rate, channels). The decoder/TTS are wired to (sample_rate, channels) by the caller;
    here we verify the backstop matches the declared format so the sink never sees two formats."""
    if backstop.sample_rate != sample_rate or backstop.channels != channels:
        raise ValueError(
            f"station format desync: backstop is ({backstop.sample_rate}, {backstop.channels}) "
            f"but segments are ({sample_rate}, {channels}) -- H5: one station-level format"
        )


async def run_once(
    *,
    items: Sequence[ScheduleItem],
    tts: TTSEngine,
    decoder: Decoder,
    sink: AudioSink,
    backstop: AudioBuffer,
    sleeper: Sleeper,
    refill_budget_seconds: float,
    text_generator: TextGenerator | None = None,  # P3-8: ranked DJ chain (None -> NullDJ floor)
    persona: str | None = None,  # P3-8: grounding; None -> the Producer's default sentinel
    station_name: str | None = None,
    station_tagline: str | None = None,
    loudness_target_lufs: float = -16.0,  # C3: threaded to the producer
    sample_rate: int = DEFAULT_SAMPLE_RATE,  # C4: declared station format
    channels: int = 1,
    transition_silence: float = 0.0,
    maxsize: int = 2,
    skip: asyncio.Event | None = None,  # P6-3 control-API skip-at-next-boundary (None -> no skip)
) -> None:
    """Render and play ``items`` once, producer and player running concurrently.

    Returns when every item has aired. Every segment is loudness-normalized to
    ``loudness_target_lufs`` (§10); nothing is dropped (P1); a slow/failed render is covered by
    the producer substitution and the player backstop, never dead air (R11). Raises at
    construction on a backstop/station-format desync (C4) — before anything airs.
    """
    _assert_station_format(backstop=backstop, sample_rate=sample_rate, channels=channels)  # C4
    buffer = LookAheadBuffer(maxsize=maxsize)
    producer = Producer(
        items=items,
        tts=tts,
        decoder=decoder,
        buffer=buffer,
        backstop=backstop,
        text_generator=text_generator,  # P3-8 (None -> NullDJ floor)
        persona=persona,
        station_name=station_name,
        station_tagline=station_tagline,
        loudness_target_lufs=loudness_target_lufs,  # C3
    )
    player = Player(
        buffer=buffer,
        sink=sink,
        sleeper=sleeper,
        backstop=backstop,
        refill_budget_seconds=refill_budget_seconds,
        transition_silence=transition_silence,
        skip=skip,
    )
    await asyncio.gather(producer.run(), player.run(count=len(items)))
