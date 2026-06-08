"""RED tests for the Phase-3 producer wiring — plan §4.6 / §6 (P3-8, the capstone).

Tests first (strict spec-driven TDD): the producer builds a typed ``DjContext`` and routes the
three pure-patter items (station_id / block_transition / block_reminder) through the ranked
TextGenerator then the ranked TTSEngine, keeping the floors: EVERY ``TrackItem`` is decoded (the
song never becomes patter — DA CRITICAL); empty patter -> the Phase-1 template + a WARNING; a
whole-chain exhaustion -> the R11 backstop (no crash, no dead air). The new ``Producer`` /
``run_once`` DJ args are DEFAULTED so the existing Phase-1/2 call sites stay valid (C3 redux).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pirate_radio.audio.buffer import DEFAULT_SAMPLE_RATE, AudioBuffer
from pirate_radio.audio.decode import FakeDecoder
from pirate_radio.catalog.models import Track
from pirate_radio.dj.context import DjContext
from pirate_radio.dj.failover import RankedTextGenerator, RankedTTSEngine
from pirate_radio.dj.fakes import FailingTTS, FakeAudioSink, NullDJ, ScriptedDJ, StubTTS
from pirate_radio.errors import ProviderUnavailable
from pirate_radio.pipeline import run_once
from pirate_radio.pipeline.buffer import LookAheadBuffer
from pirate_radio.pipeline.producer import Producer, announcement_text, build_dj_context
from pirate_radio.pipeline.timing import VirtualSleeper
from pirate_radio.schedule.models import (
    BlockReminderItem,
    BlockTransitionItem,
    StationIdItem,
    TrackItem,
)

_TZ = ZoneInfo("America/New_York")
_T0 = datetime(2026, 6, 10, 0, 0, tzinfo=_TZ)
_BACKSTOP = AudioBuffer.silence(seconds=3.0)


def _track_item(
    dur: float = 10.0, *, intro: bool = False, outro: bool = False, tagged: bool = True
):
    track = (
        Track(path=Path("/lib/x/s.flac"), group="x", duration=dur, title="Song", artist="Band")
        if tagged
        else Track(path=Path("/lib/x/s.flac"), group="x", duration=dur)
    )
    return TrackItem(
        planned_start=_T0, duration=dur, block_name="Morning", track=track, intro=intro, outro=outro
    )


def _id_item() -> StationIdItem:
    return StationIdItem(planned_start=_T0, duration=5.0, block_name="Morning")


def _reminder_item() -> BlockReminderItem:
    return BlockReminderItem(planned_start=_T0, duration=8.0, block_name="Morning")


def _transition_item() -> BlockTransitionItem:
    return BlockTransitionItem(
        planned_start=_T0,
        duration=10.0,
        block_name="Morning",
        next_block_name="Lunchtime Theater",
        next_block_starts_at=_T0,
    )


def _drain(buf: LookAheadBuffer) -> list:
    out: list = []
    while (seg := buf.get_nowait()) is not None:
        out.append(seg)
    return out


class _RecordingTTS:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    async def synthesize(self, text: str) -> AudioBuffer:
        self.spoken.append(text)
        return AudioBuffer.silence(seconds=1.0)


class _NeverCallDJ:
    def __init__(self) -> None:
        self.calls = 0

    async def patter(self, item_kind: str, context: DjContext | None) -> str:
        self.calls += 1
        return "SHOULD NOT BE CALLED"


def _producer(items, *, tts, text_generator=None, decoder=None, buf=None) -> Producer:
    return Producer(
        items=items,
        tts=tts,
        decoder=decoder or FakeDecoder(),
        buffer=buf or LookAheadBuffer(maxsize=10),
        backstop=_BACKSTOP,
        text_generator=text_generator,
        persona="A warm host",
        station_name="PiRate One",
        station_tagline="all night",
    )


# ---- build_dj_context per kind (forward-compat + sparse) -----------------------------------
def test_build_context_trackitem_kinds() -> None:
    assert (
        build_dj_context(
            _track_item(intro=True), persona="P", station_name="S", station_tagline=None
        ).kind
        == "intro"
    )
    assert (
        build_dj_context(
            _track_item(outro=True), persona="P", station_name="S", station_tagline=None
        ).kind
        == "outro"
    )
    assert (
        build_dj_context(_track_item(), persona="P", station_name="S", station_tagline=None).kind
        == "factoid"
    )


def test_build_context_patter_kinds() -> None:
    assert (
        build_dj_context(_id_item(), persona="P", station_name="S", station_tagline=None).kind
        == "station_id"
    )
    assert (
        build_dj_context(_reminder_item(), persona="P", station_name="S", station_tagline=None).kind
        == "block_reminder"
    )
    ctx = build_dj_context(_transition_item(), persona="P", station_name="S", station_tagline=None)
    assert ctx.kind == "block_transition"
    assert ctx.next_block is not None and ctx.next_block.name == "Lunchtime Theater"


def test_build_context_track_meta_and_sparse() -> None:
    ctx = build_dj_context(
        _track_item(tagged=True), persona="P", station_name="S", station_tagline=None
    )
    assert ctx.track is not None and ctx.track.title == "Song"
    sparse = build_dj_context(
        _track_item(tagged=False), persona="P", station_name="S", station_tagline=None
    )
    assert sparse.track is not None and sparse.track.is_sparse  # §9.3: never a skip


def test_build_context_carries_persona_and_station() -> None:
    ctx = build_dj_context(_id_item(), persona="warm", station_name="PiRate", station_tagline="tag")
    assert ctx.persona == "warm" and ctx.station_name == "PiRate" and ctx.station_tagline == "tag"


# ---- DA CRITICAL: every TrackItem decodes; the DJ is NEVER called for a track --------------
async def test_intro_trackitem_decodes_song_dj_never_called() -> None:
    dj = _NeverCallDJ()
    buf = LookAheadBuffer(maxsize=10)
    await _producer(
        [_track_item(33.0, intro=True)], tts=StubTTS(), text_generator=dj, buf=buf
    ).run()
    segs = _drain(buf)
    assert len(segs) == 1  # DA: EXACTLY one segment — no decode-AND-patter double-segment bug
    assert segs[0].audio.duration_seconds == 33.0  # the SONG was decoded, not patter
    assert dj.calls == 0  # intro/outro flags do NOT trigger standalone patter in Phase 3


async def test_outro_trackitem_decodes_song_dj_never_called() -> None:
    dj = _NeverCallDJ()
    buf = LookAheadBuffer(maxsize=10)
    await _producer(
        [_track_item(12.0, outro=True)], tts=StubTTS(), text_generator=dj, buf=buf
    ).run()
    segs = _drain(buf)
    assert len(segs) == 1 and segs[0].audio.duration_seconds == 12.0 and dj.calls == 0


async def test_plain_track_decodes_dj_never_called() -> None:
    dj = _NeverCallDJ()
    buf = LookAheadBuffer(maxsize=10)
    await _producer([_track_item(20.0)], tts=StubTTS(), text_generator=dj, buf=buf).run()
    assert _drain(buf)[0].audio.duration_seconds == 20.0 and dj.calls == 0


# ---- pure-patter: DJ -> TTS wiring ---------------------------------------------------------
async def test_pure_patter_routes_dj_text_to_tts(caplog) -> None:
    tts = _RecordingTTS()
    buf = LookAheadBuffer(maxsize=10)
    chain = RankedTextGenerator([ScriptedDJ(text="Here's a great tune")])
    with caplog.at_level(logging.WARNING):
        await _producer([_id_item()], tts=tts, text_generator=chain, buf=buf).run()
    assert tts.spoken == ["Here's a great tune"]  # the LLM line was synthesized
    # DA: a SUCCESSFUL patter must NOT log the degrade warning (fallback can't be always-on)
    assert not any("template fallback" in r.message for r in caplog.records)


async def test_block_transition_context_threaded_to_dj() -> None:
    # DA: the richest, most-droppable context (next_block + boundary_at) must survive THROUGH the
    # wired producer path, not just at the build_dj_context unit. Capture it via ScriptedDJ.calls.
    spy = ScriptedDJ(text="up next!")
    buf = LookAheadBuffer(maxsize=10)
    await _producer([_transition_item()], tts=_RecordingTTS(), text_generator=spy, buf=buf).run()
    assert len(spy.calls) == 1
    kind, ctx = spy.calls[0]
    assert kind == "block_transition"
    assert ctx is not None and ctx.next_block is not None
    assert ctx.next_block.name == "Lunchtime Theater"
    assert ctx.next_block.boundary_at == _T0  # next_block_starts_at threaded, not dropped


async def test_empty_patter_falls_back_to_template_with_warning(caplog) -> None:
    tts = _RecordingTTS()
    buf = LookAheadBuffer(maxsize=10)
    chain = RankedTextGenerator([NullDJ()])  # NullDJ floor -> ""
    with caplog.at_level(logging.WARNING):
        await _producer([_id_item()], tts=tts, text_generator=chain, buf=buf).run()
    assert tts.spoken == [announcement_text(_id_item())]  # Phase-1 template fallback
    assert any("template fallback" in r.message for r in caplog.records)  # Field-Op visibility


async def test_default_text_generator_is_nulldj_floor() -> None:
    # Producer with no text_generator -> a NullDJ-only ranked floor -> empty patter -> template
    tts = _RecordingTTS()
    buf = LookAheadBuffer(maxsize=10)
    await Producer(
        items=[_id_item()], tts=tts, decoder=FakeDecoder(), buffer=buf, backstop=_BACKSTOP
    ).run()
    assert tts.spoken == [announcement_text(_id_item())]


# ---- whole-chain exhaustion -> R11 backstop (no crash, no dead air) ------------------------
async def test_dj_and_tts_all_fail_then_backstop() -> None:
    buf = LookAheadBuffer(maxsize=10)
    text_chain = RankedTextGenerator([ScriptedDJ(error=ProviderUnavailable("llm down"))])
    tts_chain = RankedTTSEngine([FailingTTS(error=ProviderUnavailable("tts down"))])
    await _producer([_id_item()], tts=tts_chain, text_generator=text_chain, buf=buf).run()
    segs = _drain(buf)
    assert len(segs) == 1
    assert segs[0].audio is _BACKSTOP  # R11: backstop substituted, no crash, no dead air


# ---- C3 redux + capstone integration through run_once -------------------------------------
# Under the instant VirtualSleeper, the real to_thread(normalize_to) worker hop would let the
# player race ahead and spuriously backstop (the P2-6 virtual-time/real-time issue). These
# integration tests patch normalize_to->identity + to_thread->inline + maxsize==len(items) so the
# wiring is deterministic; real loudness/offload are covered by the dedicated P2-6 tests.
def _deterministic(monkeypatch) -> None:
    import asyncio

    monkeypatch.setattr("pirate_radio.pipeline.producer.normalize_to", lambda buf, **kw: buf)

    async def _inline(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", _inline)


def _backstop():
    return AudioBuffer.silence(seconds=1.0, sample_rate=DEFAULT_SAMPLE_RATE, channels=1)


async def test_run_once_old_signature_still_works(monkeypatch) -> None:
    _deterministic(monkeypatch)
    sink = FakeAudioSink()
    items = [_track_item(2.0), _id_item()]
    # the Phase-1/2 keyword set — NO text_generator/persona/station — must still run (no TypeError)
    await run_once(
        items=items,
        tts=StubTTS(),
        decoder=FakeDecoder(),
        sink=sink,
        backstop=_backstop(),
        sleeper=VirtualSleeper(),
        refill_budget_seconds=5.0,
        maxsize=len(items),
    )
    assert len(sink.played) == 2  # both items aired


async def test_run_once_threads_text_generator(monkeypatch) -> None:
    _deterministic(monkeypatch)
    sink = FakeAudioSink()
    tts = _RecordingTTS()
    await run_once(
        items=[_id_item()],
        tts=tts,
        decoder=FakeDecoder(),
        sink=sink,
        backstop=_backstop(),
        sleeper=VirtualSleeper(),
        refill_budget_seconds=5.0,
        text_generator=RankedTextGenerator([ScriptedDJ(text="threaded line")]),
        persona="P",
        station_name="S",
        station_tagline=None,
        maxsize=1,
    )
    assert tts.spoken == ["threaded line"]  # the DJ chain threaded through run_once was used


async def test_run_once_track_decodes_patter_uses_dj_both_air(monkeypatch) -> None:
    # capstone integration: a track + a patter item through run_once with a real ranked DJ chain —
    # the track decodes (DJ untouched), the patter uses the DJ, BOTH reach the sink.
    _deterministic(monkeypatch)
    sink = FakeAudioSink()
    tts = _RecordingTTS()
    dj = ScriptedDJ(text="and that was a banger")
    items = [_track_item(2.0), _id_item()]
    await run_once(
        items=items,
        tts=tts,
        decoder=FakeDecoder(),
        sink=sink,
        backstop=_backstop(),
        sleeper=VirtualSleeper(),
        refill_budget_seconds=5.0,
        text_generator=RankedTextGenerator([dj]),
        persona="P",
        station_name="S",
        station_tagline=None,
        maxsize=len(items),
    )
    assert len(sink.played) == 2  # both items aired
    assert tts.spoken == ["and that was a banger"]  # DJ used for patter only (track decoded)
    assert [k for k, _ in dj.calls] == ["station_id"]  # DJ NOT called for the track
