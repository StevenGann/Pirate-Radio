"""Producer: render each schedule item just ahead of the playhead (§5.3).

A ``track`` is rendered by the decoder, patter (station_id / block_transition /
block_reminder) by the TTS engine. P1 (no-drop): every item produces exactly one segment,
in order. R11/R15: a backend ``ProviderError`` does NOT crash or drop the item — the
producer substitutes the canned backstop (and logs) so the player always has audio. (The
retryable-vs-terminal failover wrapper is Phase 3; Phase 1 backstops any ProviderError.)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from pirate_radio.audio.buffer import AudioBuffer
from pirate_radio.audio.decode import Decoder
from pirate_radio.audio.loudness import normalize_to
from pirate_radio.dj.context import BlockContext, DjContext, TrackMeta
from pirate_radio.dj.failover import RankedTextGenerator
from pirate_radio.dj.fakes import NullDJ
from pirate_radio.dj.protocols import TextGenerator, TTSEngine
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
# default grounding for the bare (no-station-config) harness path; production threads real values.
_DEFAULT_PERSONA = "PiRate Radio DJ"


def build_dj_context(
    item: ScheduleItem, *, persona: str, station_name: str, station_tagline: str | None
) -> DjContext:
    """PURE: ScheduleItem (+ its Track) + station -> the grounded DjContext (R16, §9.2).

    Grid-only fields (block tagline/description) are None in Phase 3 (§7-Q4); track tags are
    best-effort (§9.3) — a sparse track still produces a context, never a skip. The producer
    only calls this for the three pure-patter items in Phase 3; the intro/outro/factoid kinds
    are wired for Phase-4 segment assembly (every TrackItem is decoded in Phase 3, §7-Q8)."""
    current = BlockContext(name=item.block_name)
    next_block: BlockContext | None = None
    track: TrackMeta | None = None
    if isinstance(item, TrackItem):
        t = item.track
        track = TrackMeta(title=t.title, artist=t.artist, album=t.album, year=t.year)
        kind = "intro" if item.intro else "outro" if item.outro else "factoid"
    elif isinstance(item, BlockTransitionItem):
        kind = "block_transition"
        next_block = BlockContext(name=item.next_block_name, boundary_at=item.next_block_starts_at)
    elif isinstance(item, BlockReminderItem):
        kind = "block_reminder"
    else:  # StationIdItem
        kind = "station_id"
    return DjContext(
        kind=kind,
        persona=persona,
        station_name=station_name,
        station_tagline=station_tagline,
        current_block=current,
        next_block=next_block,
        track=track,
    )


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


def _item_label(item: ScheduleItem) -> str:
    """A human label for the loudness clamp WARNING (H17)."""
    if isinstance(item, TrackItem):
        return str(item.track.path)
    return item.kind


class Producer:
    def __init__(
        self,
        *,
        items: Sequence[ScheduleItem],
        tts: TTSEngine,
        decoder: Decoder,
        buffer: LookAheadBuffer,
        backstop: AudioBuffer,
        # NEW (Phase 3) — ALL DEFAULTED so the existing Phase-1/2 call sites stay valid (C3 redux).
        # None -> a NullDJ-only ranked floor; None persona/station -> valid (non-empty) sentinels
        # so build_dj_context never violates DjContext's min_length=1 on the bare-harness path.
        text_generator: TextGenerator | None = None,
        persona: str | None = None,
        station_name: str | None = None,
        station_tagline: str | None = None,
        loudness_target_lufs: float = -16.0,
    ) -> None:
        self._items = items
        self._tts = tts
        self._decoder = decoder
        self._buffer = buffer
        self._backstop = backstop  # pre-normalized once by the caller; never re-normalized here
        self._dj: TextGenerator = (
            text_generator if text_generator is not None else RankedTextGenerator([NullDJ()])
        )
        self._persona = persona if persona else _DEFAULT_PERSONA
        self._station_name = station_name if station_name else _STATION
        self._station_tagline = station_tagline
        self._target_lufs = loudness_target_lufs

    async def run(self) -> None:
        for item in self._items:
            try:
                audio = await self._render(item)
                label = _item_label(item)
                audio = await asyncio.to_thread(  # Q9/R23: R128 is CPU work, off the loop
                    normalize_to, audio, target_lufs=self._target_lufs, track_label=label
                )
            except ProviderError as exc:
                logger.warning(
                    "render failed for %s item (%s) -> backstop (R11/R15)", item.kind, exc
                )
                audio = self._backstop  # already at the station target; not re-normalized
            await self._buffer.put(RenderedSegment(item=item, audio=audio))

    async def _render(self, item: ScheduleItem) -> AudioBuffer:
        # Phase 3 (§7-Q8): EVERY TrackItem is DECODED — the song always plays. intro/outro are
        # flags reserved for Phase-4 segment assembly, NOT standalone patter, so an intro/outro
        # TrackItem can never replace its song with talk (DA CRITICAL).
        if isinstance(item, TrackItem):
            return await self._decoder.decode(item.track)
        # Only the three §20-named pure-patter items reach the grounded DJ -> TTS path:
        ctx = build_dj_context(
            item,
            persona=self._persona,
            station_name=self._station_name,
            station_tagline=self._station_tagline,
        )
        text = await self._dj.patter(ctx.kind, ctx)  # ranked LLM chain; NullDJ floor -> ""
        if not text.strip():  # §9.3 floor: degrade to the Phase-1 template line
            logger.warning(  # Field-Op: operator visibility on the degrade
                "dj patter empty for %s item -> template fallback (NullDJ/empty-chain floor)",
                item.kind,
            )
            text = announcement_text(item)
        return await self._tts.synthesize(text)  # ranked TTS chain; any escape -> R11 backstop
