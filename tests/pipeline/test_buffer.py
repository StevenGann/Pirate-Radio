"""RED tests for ``pirate_radio.pipeline.{segment,buffer}`` — the look-ahead queue.

Tests first. ``RenderedSegment`` pairs the source ScheduleItem with its rendered audio.
``LookAheadBuffer`` is a bounded queue (depth 1-2, §5.3): the producer blocks on a full
queue (back-pressure → a slow render stalls REFILL, never playback), the player pulls
non-blocking and decides the R11 backstop itself. All waiting in tests is a yield
(``asyncio.sleep(0)``), never wall-clock (R21).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pirate_radio.audio.buffer import AudioBuffer
from pirate_radio.catalog.models import Track
from pirate_radio.pipeline.buffer import LookAheadBuffer
from pirate_radio.pipeline.segment import RenderedSegment
from pirate_radio.schedule.models import TrackItem

_TZ = ZoneInfo("America/New_York")


def _seg(seconds: float) -> RenderedSegment:
    item = TrackItem(
        planned_start=datetime(2026, 6, 10, 0, 0, tzinfo=_TZ),
        duration=seconds,
        block_name="blk",
        track=Track(path=Path(f"/lib/x/{seconds}.flac"), group="x", duration=seconds),
    )
    return RenderedSegment(item=item, audio=AudioBuffer.silence(seconds=seconds))


def test_rendered_segment_is_frozen_pair() -> None:
    import dataclasses

    s = _seg(1.0)
    assert dataclasses.is_dataclass(s)
    assert isinstance(s.item, TrackItem)
    assert isinstance(s.audio, AudioBuffer)
    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        s.audio = AudioBuffer.silence(seconds=2.0)  # type: ignore[misc]


async def test_put_then_get_nowait_returns_segment() -> None:
    buf = LookAheadBuffer(maxsize=2)
    s = _seg(1.0)
    await buf.put(s)
    assert buf.depth == 1
    assert buf.get_nowait() is s
    assert buf.depth == 0


async def test_get_nowait_on_empty_returns_none() -> None:
    buf = LookAheadBuffer(maxsize=2)
    assert buf.get_nowait() is None


async def test_maxsize_is_exposed() -> None:
    assert LookAheadBuffer(maxsize=2).maxsize == 2


async def test_full_queue_applies_backpressure() -> None:
    # A full queue blocks the producer's put until the player frees a slot — proven with
    # yields only (asyncio.sleep(0)), no wall-clock (R21).
    buf = LookAheadBuffer(maxsize=2)
    s0, s1, s2 = _seg(1.0), _seg(2.0), _seg(3.0)
    await buf.put(s0)
    await buf.put(s1)
    assert buf.depth == 2

    pending = asyncio.create_task(buf.put(s2))  # must block: queue full
    for _ in range(3):
        await asyncio.sleep(0)
    assert not pending.done()
    assert buf.depth == 2

    assert buf.get_nowait() is s0  # free a slot
    for _ in range(3):
        await asyncio.sleep(0)
    assert pending.done()  # producer unblocked
    assert buf.depth == 2  # s1, s2 now queued
    await pending
