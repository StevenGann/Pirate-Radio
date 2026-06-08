"""ScheduleItem discriminated union (R17) + DailySchedule (persisted, schema_version).

R17: a discriminated union on ``kind`` so invalid states are unrepresentable — a
``track`` item must carry a ``Track``; a ``block_transition`` must not, and (via the
inherited ``extra="forbid"``) no variant may carry another variant's fields. All
variants share ``planned_start`` (tz-aware, D6) + ``duration`` + ``block_name``.

``duration`` is the *content* duration only; the inter-element
``transition_silence_seconds`` is timing the generator applies between items (§8.4)
and is NOT folded in, so ``find_now``'s exact-track re-anchor (R12) stays exact.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pirate_radio.catalog.models import Track

SCHEDULE_SCHEMA_VERSION = 1  # R17 envelope version for persistence.py

_FROZEN = ConfigDict(frozen=True, extra="forbid")


def _require_tz_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must be tz-aware (D6)")
    return value


class _ItemBase(BaseModel):
    model_config = _FROZEN

    planned_start: datetime  # tz-aware estimate (R12: estimate for patter)
    duration: float = Field(gt=0.0)  # seconds; transition silence is separate (§8.4)
    block_name: str = Field(min_length=1)

    @field_validator("planned_start")
    @classmethod
    def _planned_start_tz_aware(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)


class TrackItem(_ItemBase):
    kind: Literal["track"] = "track"
    track: Track  # required -> R17: a track item without a Track is unrepresentable
    intro: bool = False
    outro: bool = False


class StationIdItem(_ItemBase):
    kind: Literal["station_id"] = "station_id"


class BlockTransitionItem(_ItemBase):
    kind: Literal["block_transition"] = "block_transition"
    next_block_name: str = Field(min_length=1)
    next_block_starts_at: datetime

    @field_validator("next_block_starts_at")
    @classmethod
    def _next_start_tz_aware(cls, v: datetime) -> datetime:
        return _require_tz_aware(v)


class BlockReminderItem(_ItemBase):
    kind: Literal["block_reminder"] = "block_reminder"


ScheduleItem = Annotated[
    TrackItem | StationIdItem | BlockTransitionItem | BlockReminderItem,
    Field(discriminator="kind"),
]


class DailySchedule(BaseModel):
    """The realized, persisted schedule for one station-day (§8.1)."""

    model_config = _FROZEN

    date: date
    station: str = Field(min_length=1)
    seed: int  # the RNG seed used (R19 reproducibility record)
    items: tuple[ScheduleItem, ...] = Field(min_length=1)
