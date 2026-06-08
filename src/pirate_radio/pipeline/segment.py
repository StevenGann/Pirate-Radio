"""RenderedSegment: a rendered ``AudioBuffer`` paired with its source ScheduleItem.

The unit that flows through the look-ahead buffer from producer to player. Frozen — a
segment is produced once and consumed once, never mutated.
"""

from __future__ import annotations

from dataclasses import dataclass

from pirate_radio.audio.buffer import AudioBuffer
from pirate_radio.schedule.models import ScheduleItem


@dataclass(frozen=True)
class RenderedSegment:
    item: ScheduleItem
    audio: AudioBuffer
