"""The daily-slice driver (Phase 4 §B) — the seam ``run_once``'s docstring names.

``slice_from_now`` (PURE) turns an ``AnchoredSchedule`` + ``now`` into the items to air "today from
now" + the seek offset into the first item + the leading gap silence (R11). ``play_day`` plays the
R11 gap (at the station format), seeks into the first item by decode+trim (with an
offset-past-decoded-frames → skip guard — VBR/truncated files, DA H2), then delegates the remainder
to the FROZEN ``run_once`` (Q1: trim here, don't churn ``run_once``).
"""

from __future__ import annotations

import asyncio
import bisect
from datetime import datetime
from typing import cast

import numpy as np

from pirate_radio.audio.buffer import DEFAULT_SAMPLE_RATE, AudioBuffer
from pirate_radio.audio.decode import Decoder
from pirate_radio.audio.loudness import normalize_to
from pirate_radio.dj.protocols import AudioSink
from pirate_radio.schedule.models import ScheduleItem, TrackItem
from pirate_radio.schedule.resume import AnchoredSchedule


def slice_from_now(
    anchored: AnchoredSchedule, now: datetime
) -> tuple[list[ScheduleItem], float, float]:
    """PURE: ``(remaining items, seek offset into the first, leading gap seconds)``. Mirrors
    ``find_now``'s bisect but returns the index-derived slice (not item identity). Cases: airing
    (offset>0, gap=0), in a gap / before first (gap>0, offset=0), past end-of-day (empty)."""
    starts, ends, items = anchored.starts, anchored.ends, anchored.items
    idx = bisect.bisect_right(starts, now) - 1
    if idx >= 0 and now < ends[idx]:  # airing now -> seek into items[idx]
        return list(items[idx:]), (now - starts[idx]).total_seconds(), 0.0
    nxt = bisect.bisect_right(starts, now)  # first item starting after now
    if nxt < len(items):  # in a gap / before the first item (R11 leading silence)
        return list(items[nxt:]), 0.0, (starts[nxt] - now).total_seconds()
    return [], 0.0, 0.0  # past end-of-day -> caller regenerates


async def play_day(*, anchored: AnchoredSchedule, now: datetime, **run_once_kwargs: object) -> None:
    """Play the slice for ``now`` to end-of-day: R11 leading gap, then the (possibly seek-trimmed)
    remaining items via ``run_once``. ``run_once_kwargs`` are the full ``run_once`` keyword args
    EXCEPT ``items`` (which this computes): ``sink``, ``decoder``, ``tts``, ``backstop``,
    ``sleeper``, ``refill_budget_seconds``, ``sample_rate``/``channels``, the DJ args, etc."""
    from pirate_radio.pipeline import run_once  # local: avoid any package import-order surprise

    sink = cast(AudioSink, run_once_kwargs["sink"])
    decoder = cast(Decoder, run_once_kwargs["decoder"])
    sample_rate = cast(int, run_once_kwargs.get("sample_rate", DEFAULT_SAMPLE_RATE))
    channels = cast(int, run_once_kwargs.get("channels", 1))
    loudness = cast(float, run_once_kwargs.get("loudness_target_lufs", -16.0))

    items, offset, gap = slice_from_now(anchored, now)
    if gap > 0:
        # R11 leading gap silence, at the station format (the player's C4 guard checks the rest).
        await sink.play(
            AudioBuffer.silence(seconds=gap, sample_rate=sample_rate, channels=channels)
        )
    if not items:
        return

    first = items[0]
    if offset > 0 and isinstance(first, TrackItem):
        buf = await decoder.decode(first.track)
        offset_frames = round(offset * buf.sample_rate)
        if offset_frames < buf.frames:  # seek into the partial first track
            trimmed = AudioBuffer(
                np.ascontiguousarray(buf.samples[offset_frames:]), buf.sample_rate, buf.channels
            )
            normalized = await asyncio.to_thread(
                normalize_to, trimmed, target_lufs=loudness, track_label=str(first.track.path)
            )
            await sink.play(normalized)
        # else (offset >= decoded frames: VBR/truncated/metadata-lying) -> skip, never an empty buf
        items = items[1:]

    await run_once(items=items, **run_once_kwargs)  # type: ignore[arg-type]
