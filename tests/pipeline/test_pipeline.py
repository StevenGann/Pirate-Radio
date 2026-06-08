"""RED tests for ``pirate_radio.pipeline.run_once`` — producer+player wired (P1 no-drop, R21).

Tests first. ``run_once`` runs the producer and player concurrently over a list of items
and returns when every item has aired. P1: nothing is dropped, order is preserved. R21:
driven by ``VirtualSleeper`` so the whole pipeline runs in virtual time — zero wall-clock.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pirate_radio.audio.buffer import AudioBuffer
from pirate_radio.audio.decode import FailingDecoder, FakeDecoder
from pirate_radio.catalog.models import Track
from pirate_radio.dj.fakes import FakeAudioSink, StubTTS
from pirate_radio.pipeline import run_once
from pirate_radio.pipeline.timing import VirtualSleeper
from pirate_radio.schedule.models import TrackItem

_TZ = ZoneInfo("America/New_York")
_T0 = datetime(2026, 6, 10, 0, 0, tzinfo=_TZ)
_BACKSTOP = AudioBuffer.silence(seconds=3.0)


def _track_item(dur: float) -> TrackItem:
    return TrackItem(
        planned_start=_T0,
        duration=dur,
        block_name="blk",
        track=Track(path=Path(f"/lib/x/{dur}.flac"), group="x", duration=dur),
    )


async def test_run_once_plays_every_item_in_order_no_drop(caplog) -> None:
    import logging

    items = [_track_item(10.0), _track_item(20.0), _track_item(30.0)]
    sink = FakeAudioSink()
    caplog.set_level(logging.WARNING)
    await run_once(
        items=items,
        tts=StubTTS(),
        decoder=FakeDecoder(),
        sink=sink,
        backstop=_BACKSTOP,
        sleeper=VirtualSleeper(),
        refill_budget_seconds=5.0,
        transition_silence=0.0,
        # maxsize == len(items) is load-bearing test scaffolding: a queue big enough to
        # hold every item means the producer never blocks on back-pressure, so under
        # cooperative scheduling it fills the queue before the player drains it and no
        # spurious backstop can fire. (Back-pressure itself is covered in test_buffer.)
        maxsize=len(items),
    )
    # Every item aired, in order, at its exact (decoder) duration — no backstop interleaved.
    assert [b.duration_seconds for b in sink.played] == [10.0, 20.0, 30.0]
    # Defensive (QA): no backstop fired, regardless of cooperative scheduling order.
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


async def test_run_once_backstops_a_failed_render_but_still_finishes() -> None:
    # R11 *producer-substitution* path (Path A): a failing decoder makes every render fall
    # back to the backstop in the PRODUCER, which still enqueues one segment per item; the
    # player drains them and completes (never dead air, never a hang). (The player's own
    # missed-deadline backstop — Path B — is covered in test_player.)
    items = [_track_item(10.0), _track_item(20.0)]
    sink = FakeAudioSink()
    await run_once(
        items=items,
        tts=StubTTS(),
        decoder=FailingDecoder(),
        sink=sink,
        backstop=_BACKSTOP,
        sleeper=VirtualSleeper(),
        refill_budget_seconds=5.0,
        transition_silence=0.0,
        maxsize=len(items),
    )
    # `is`, not `==`: AudioBuffer == AudioBuffer is an ambiguous-array ValueError.
    assert len(sink.played) == 2
    assert all(b is _BACKSTOP for b in sink.played)  # one backstop per item, in order
