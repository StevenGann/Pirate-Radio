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


async def test_run_once_plays_every_item_in_order_no_drop(caplog, monkeypatch) -> None:
    import asyncio
    import logging

    # This test pins no-drop / ordering, NOT loudness. Two patches keep it deterministic under
    # virtual time: normalize_to -> instant identity (no real R128 CPU work), and to_thread ->
    # inline (its real-time worker-thread hop would otherwise let the player, on the instant
    # VirtualSleeper, race ahead and spuriously backstop). The real loudness normalization and
    # the to_thread offload are each verified by the dedicated P2-6 tests above.
    monkeypatch.setattr("pirate_radio.pipeline.producer.normalize_to", lambda buf, **kw: buf)

    async def _inline(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", _inline)
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


# --- P2-6: loudness wiring (§10) + run_once threading (C3) + format-desync (C4) ----

import threading  # noqa: E402

import pytest  # noqa: E402

from pirate_radio.pipeline.buffer import LookAheadBuffer  # noqa: E402
from pirate_radio.pipeline.producer import Producer  # noqa: E402

_SPY = "pirate_radio.pipeline.producer.normalize_to"


def _drain(buf: LookAheadBuffer) -> list:
    out = []
    while (seg := buf.get_nowait()) is not None:
        out.append(seg)
    return out


async def test_producer_enqueues_the_normalized_result(monkeypatch) -> None:
    # §10: every rendered element (track AND patter) is normalized to the station target, AND
    # the NORMALIZED result is what gets enqueued. The spy returns a DISTINCT marker buffer so
    # an impl that calls normalize_to but enqueues the raw render (discarding the result) fails.
    marker = AudioBuffer.silence(seconds=1.0)
    calls: list = []

    def _spy(buf, *, target_lufs, track_label="<unknown>"):
        calls.append((target_lufs, track_label))
        return marker

    monkeypatch.setattr(_SPY, _spy)
    buf = LookAheadBuffer(maxsize=10)
    items = [_track_item(10.0), _track_item(20.0)]
    await Producer(
        items=items,
        tts=StubTTS(),
        decoder=FakeDecoder(),
        buffer=buf,
        backstop=_BACKSTOP,
        loudness_target_lufs=-18.0,
    ).run()
    segs = _drain(buf)
    assert len(segs) == 2
    assert all(s.audio is marker for s in segs)  # the normalize_to RESULT is enqueued, not raw
    assert [c[0] for c in calls] == [-18.0, -18.0]  # normalized to the target, once per item


async def test_producer_backstop_path_is_not_normalized(monkeypatch) -> None:
    # The backstop is pre-normalized once at construction; the producer must NOT re-normalize
    # it on the ProviderError path.
    calls: list = []
    monkeypatch.setattr(_SPY, lambda buf, **kw: (calls.append(kw), buf)[1])
    buf = LookAheadBuffer(maxsize=10)
    await Producer(
        items=[_track_item(10.0)],
        tts=StubTTS(),
        decoder=FailingDecoder(),
        buffer=buf,
        backstop=_BACKSTOP,
        loudness_target_lufs=-16.0,
    ).run()
    segs = _drain(buf)
    assert segs[0].audio is _BACKSTOP
    assert calls == []  # normalize_to never called on the backstop path


async def test_producer_normalize_runs_off_the_event_loop(monkeypatch) -> None:
    # Q9/R23: R128 normalization is CPU work -> must run via asyncio.to_thread, off the loop.
    seen: list = []

    def _spy(buf, *, target_lufs, track_label="<unknown>"):
        seen.append(threading.get_ident())
        return buf

    monkeypatch.setattr(_SPY, _spy)
    buf = LookAheadBuffer(maxsize=10)
    await Producer(
        items=[_track_item(10.0)],
        tts=StubTTS(),
        decoder=FakeDecoder(),
        buffer=buf,
        backstop=_BACKSTOP,
        loudness_target_lufs=-16.0,
    ).run()
    assert seen and all(tid != threading.get_ident() for tid in seen)


async def test_run_once_threads_loudness_target_to_producer(monkeypatch) -> None:
    # C3: run_once must forward loudness_target_lufs all the way to normalize_to.
    received: list = []

    def _spy(buf, *, target_lufs, track_label="<unknown>"):
        received.append(target_lufs)
        return buf

    monkeypatch.setattr(_SPY, _spy)
    await run_once(
        items=[_track_item(10.0)],
        tts=StubTTS(),
        decoder=FakeDecoder(),
        sink=FakeAudioSink(),
        backstop=_BACKSTOP,
        sleeper=VirtualSleeper(),
        refill_budget_seconds=5.0,
        loudness_target_lufs=-9.0,
        sample_rate=48_000,
        channels=1,
        maxsize=2,
    )
    assert received == [-9.0]


async def test_run_once_rejects_station_format_desync() -> None:
    # C4: a backstop whose (rate, channels) differs from the declared station format is a
    # desync -> raise at construction, BEFORE anything airs. (Catches a backstop/declared
    # mismatch; verifying the decoder/TTS actually emit the declared rate is a Phase-4
    # coordinator job — run_once only sees the declared ints. See 0022.)
    mismatched_backstop = AudioBuffer.silence(seconds=3.0, sample_rate=22_050)
    sink = FakeAudioSink()
    with pytest.raises(ValueError, match="desync"):
        await run_once(
            items=[_track_item(10.0)],
            tts=StubTTS(),
            decoder=FakeDecoder(),
            sink=sink,
            backstop=mismatched_backstop,
            sleeper=VirtualSleeper(),
            refill_budget_seconds=5.0,
            loudness_target_lufs=-16.0,
            sample_rate=48_000,
            channels=1,
        )
    assert sink.played == []  # raised at construction — nothing aired
