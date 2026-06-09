"""The daily-slice driver (Phase 4 §B) — the seam ``run_once``'s docstring names.

``slice_from_now`` (PURE) turns an ``AnchoredSchedule`` + ``now`` into the items to air "today from
now" + the seek offset into the first item + the leading gap silence (R11). ``play_day`` plays the
R11 gap (at the station format), seeks into the first item by decode+trim (with an
offset-past-decoded-frames → skip guard — VBR/truncated files, DA H2), then delegates the remainder
to the FROZEN ``run_once`` (Q1: trim here, don't churn ``run_once``).
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import numpy as np

from pirate_radio.audio.buffer import DEFAULT_SAMPLE_RATE, AudioBuffer
from pirate_radio.audio.decode import Decoder
from pirate_radio.audio.loudness import normalize_to
from pirate_radio.dj.protocols import AudioSink, TextGenerator, TTSEngine
from pirate_radio.pipeline.timing import Sleeper
from pirate_radio.schedule.models import ScheduleItem, TrackItem
from pirate_radio.schedule.resume import AnchoredSchedule


def slice_from_now(
    anchored: AnchoredSchedule, now: datetime
) -> tuple[list[ScheduleItem], float, float]:
    """PURE: ``(remaining items, seek offset into the first, leading gap seconds)`` for ``now`` to
    end-of-day. Delegates to ``AnchoredSchedule.slice_from`` so the airing/gap/past-end bisect lives
    in ONE place (shared with ``find_now``) and the two views can never diverge (code-cycle)."""
    return anchored.slice_from(now)


async def play_day(
    *,
    anchored: AnchoredSchedule,
    now: datetime,
    tts: TTSEngine,
    decoder: Decoder,
    sink: AudioSink,
    backstop: AudioBuffer,
    sleeper: Sleeper,
    refill_budget_seconds: float,
    text_generator: TextGenerator | None = None,
    persona: str | None = None,
    station_name: str | None = None,
    station_tagline: str | None = None,
    loudness_target_lufs: float = -16.0,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    channels: int = 1,
    transition_silence: float = 0.0,
    maxsize: int = 2,
    skip: asyncio.Event | None = None,
) -> None:
    """Play the slice for ``now`` to end-of-day: the R11 leading gap, then the (possibly
    seek-trimmed) remaining items via the FROZEN ``run_once``. Takes ``run_once``'s keyword surface
    explicitly (minus ``items``, which this computes) and forwards it by name — so the R11 gap
    silence is built at the SAME ``sample_rate``/``channels`` ``run_once`` receives (no desync, no
    untyped ``**kwargs`` / casts — code-cycle)."""
    from pirate_radio.pipeline import run_once  # local: avoid any package import-order surprise

    items, offset, gap = slice_from_now(anchored, now)
    if gap > 0:
        # R11 leading gap silence, at the station format (the player's C4 guard checks the rest).
        await sink.play(
            AudioBuffer.silence(seconds=gap, sample_rate=sample_rate, channels=channels)
        )
    if not items:
        return

    first = items[0]
    if offset > 0:
        # The first item is partially aired (a resume landed inside it). For a track, air the
        # seek-trimmed remainder; for patter, drop it — re-airing a half-spoken intro/id from
        # second 0 is worse than skipping it (code-cycle). Either way the partial item is consumed
        # here, not replayed by run_once.
        if isinstance(first, TrackItem):
            buf = await decoder.decode(first.track)
            offset_frames = round(offset * buf.sample_rate)
            if offset_frames < buf.frames:  # seek into the partial first track
                trimmed = AudioBuffer(
                    np.ascontiguousarray(buf.samples[offset_frames:]), buf.sample_rate, buf.channels
                )
                normalized = await asyncio.to_thread(
                    normalize_to,
                    trimmed,
                    target_lufs=loudness_target_lufs,
                    track_label=str(first.track.path),
                )
                await sink.play(normalized)
            # else (offset >= decoded frames: VBR/truncated/metadata-lying) -> skip, never empty buf
        items = items[1:]

    await run_once(
        items=items,
        tts=tts,
        decoder=decoder,
        sink=sink,
        backstop=backstop,
        sleeper=sleeper,
        refill_budget_seconds=refill_budget_seconds,
        text_generator=text_generator,
        persona=persona,
        station_name=station_name,
        station_tagline=station_tagline,
        loudness_target_lufs=loudness_target_lufs,
        sample_rate=sample_rate,
        channels=channels,
        transition_silence=transition_silence,
        maxsize=maxsize,
        skip=skip,
    )
