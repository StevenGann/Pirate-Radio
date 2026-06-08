"""RED tests for ``pirate_radio.pipeline.player`` — drain to sink + R11 backstop.

Tests first. The player pulls rendered segments and plays them gaplessly, inserting the
inter-element transition silence (§10). When a refill misses its budget (the buffer is
still empty after waiting one budget), it plays the canned backstop INSTEAD of dead air
(R11). The wait goes through the injected ``Sleeper`` so the deadline is exercised in
virtual time — zero wall-clock (R21).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pirate_radio.audio.buffer import AudioBuffer
from pirate_radio.catalog.models import Track
from pirate_radio.dj.fakes import FakeAudioSink
from pirate_radio.pipeline.buffer import LookAheadBuffer
from pirate_radio.pipeline.player import Player
from pirate_radio.pipeline.segment import RenderedSegment
from pirate_radio.pipeline.timing import VirtualSleeper
from pirate_radio.schedule.models import TrackItem

_TZ = ZoneInfo("America/New_York")
_BACKSTOP = AudioBuffer.silence(seconds=3.0)


def _seg(seconds: float) -> RenderedSegment:
    item = TrackItem(
        planned_start=datetime(2026, 6, 10, 0, 0, tzinfo=_TZ),
        duration=seconds,
        block_name="blk",
        track=Track(path=Path(f"/lib/x/{seconds}.flac"), group="x", duration=seconds),
    )
    return RenderedSegment(item=item, audio=AudioBuffer.silence(seconds=seconds))


def _player(buf: LookAheadBuffer, sink: FakeAudioSink, sleeper: VirtualSleeper, *, silence: float):
    return Player(
        buffer=buf,
        sink=sink,
        sleeper=sleeper,
        backstop=_BACKSTOP,
        refill_budget_seconds=5.0,
        transition_silence=silence,
    )


async def test_plays_segments_in_order_gaplessly() -> None:
    buf = LookAheadBuffer(maxsize=4)
    s0, s1 = _seg(10.0), _seg(20.0)
    await buf.put(s0)
    await buf.put(s1)
    sink, sleeper = FakeAudioSink(), VirtualSleeper()
    await _player(buf, sink, sleeper, silence=0.0).run(count=2)
    # NB: `is`, not `==`. AudioBuffer is a frozen dataclass over a numpy array, so `buf ==
    # buf` returns an ambiguous array (ValueError on truth-test). Identity is also the
    # correct contract: the sink must receive the exact rendered buffers.
    assert len(sink.played) == 2
    assert sink.played[0] is s0.audio
    assert sink.played[1] is s1.audio
    assert sleeper.slept == []  # buffer never ran dry -> never had to wait


async def test_inserts_transition_silence_between_elements() -> None:
    buf = LookAheadBuffer(maxsize=4)
    await buf.put(_seg(10.0))
    await buf.put(_seg(20.0))
    sink, sleeper = FakeAudioSink(), VirtualSleeper()
    await _player(buf, sink, sleeper, silence=2.0).run(count=2)
    # Each element is followed by the transition-silence gap (§10). Trailing silence after
    # the LAST element is intentional: the generator's cursor budgets duration+silence for
    # every item, so the player mirrors that (the next block absorbs it).
    durs = [b.duration_seconds for b in sink.played]
    assert durs == [10.0, 2.0, 20.0, 2.0]


async def test_backstop_gap_fills_then_late_item_still_plays(caplog) -> None:
    # P1 must-fix: a backstop is GAP-FILL, NOT a replacement. When a refill is late the
    # player airs the backstop to avoid dead air, then STILL plays the real item, in order
    # — the slow item is never dropped (played-real-count == item-count).
    buf = LookAheadBuffer(maxsize=4)
    sink = FakeAudioSink()
    real = _seg(10.0)

    class _LateSleeper(VirtualSleeper):
        async def sleep(self, seconds: float) -> None:
            await super().sleep(seconds)
            if len(self.slept) == 2:  # arrives only on the 2nd wait, after one backstop
                await buf.put(real)

    sleeper = _LateSleeper()
    with caplog.at_level(logging.WARNING):
        await _player(buf, sink, sleeper, silence=0.0).run(count=1)
    assert len(sink.played) == 2
    assert sink.played[0] is _BACKSTOP  # gap-fill while waiting (R11: no dead air)
    assert sink.played[1] is real.audio  # the real item STILL aired (P1: not dropped)
    assert sleeper.slept == [5.0, 5.0]  # one budget wait, one backstop+budget wait
    assert any(r.levelno == logging.WARNING for r in caplog.records)


async def test_segment_arriving_within_first_budget_skips_the_backstop() -> None:
    # If the refill lands within the first budget wait, the player plays it directly — no
    # backstop, exactly one budget recorded. (The fast path that distinguishes a momentary
    # miss from a real underrun.)
    buf = LookAheadBuffer(maxsize=4)
    sink = FakeAudioSink()
    late = _seg(7.0)

    class _DeliveringSleeper(VirtualSleeper):
        async def sleep(self, seconds: float) -> None:
            await super().sleep(seconds)
            await buf.put(late)  # delivered during the FIRST wait

    sleeper = _DeliveringSleeper()
    await _player(buf, sink, sleeper, silence=0.0).run(count=1)
    assert len(sink.played) == 1
    assert sink.played[0] is late.audio  # the real segment, no backstop
    assert sleeper.slept == [5.0]
