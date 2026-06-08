"""RED tests for ``pirate_radio.schedule.models`` — Phase 1 plan §4.3 (R17).

Tests first: the ScheduleItem discriminated union on ``kind`` (invalid states
unrepresentable) and DailySchedule (persisted via the schema_version envelope). The
load-bearing test is the JSON round-trip that proves the discriminator routes each
variant back to its concrete type — that is what makes persistence (resume) safe.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import TypeAdapter, ValidationError

from pirate_radio.catalog.models import Track
from pirate_radio.schedule.models import (
    SCHEDULE_SCHEMA_VERSION,
    BlockReminderItem,
    BlockTransitionItem,
    DailySchedule,
    ScheduleItem,
    StationIdItem,
    TrackItem,
)

_TZ = ZoneInfo("America/New_York")
_START = datetime(2026, 6, 10, 9, 0, tzinfo=_TZ)
_TRACK = Track(path=Path("/lib/classical/x.flac"), group="classical", duration=180.0)

_ADAPTER: TypeAdapter[ScheduleItem] = TypeAdapter(ScheduleItem)


def test_schema_version_is_int() -> None:
    assert isinstance(SCHEDULE_SCHEMA_VERSION, int)


def test_track_item_carries_track() -> None:
    item = TrackItem(planned_start=_START, duration=180.0, block_name="AM", track=_TRACK)
    assert item.kind == "track"
    assert item.track.group == "classical"
    assert item.intro is False and item.outro is False


def test_station_id_item_minimal() -> None:
    item = StationIdItem(planned_start=_START, duration=5.0, block_name="AM")
    assert item.kind == "station_id"


def test_block_transition_carries_next_block() -> None:
    item = BlockTransitionItem(
        planned_start=_START,
        duration=8.0,
        block_name="AM",
        next_block_name="Lunch",
        next_block_starts_at=_START,
    )
    assert item.kind == "block_transition"
    assert item.next_block_name == "Lunch"


def test_block_reminder_item_minimal() -> None:
    item = BlockReminderItem(planned_start=_START, duration=8.0, block_name="AM")
    assert item.kind == "block_reminder"


# --- R17: invalid states are unrepresentable ------------------------------------


def test_discriminator_routes_track_dict_to_track_item() -> None:
    raw = {
        "kind": "track",
        "planned_start": _START.isoformat(),
        "duration": 180.0,
        "block_name": "AM",
        "track": _TRACK.model_dump(mode="json"),
    }
    item = _ADAPTER.validate_python(raw)
    assert isinstance(item, TrackItem)


def test_track_kind_without_track_rejected() -> None:
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python(
            {
                "kind": "track",
                "planned_start": _START.isoformat(),
                "duration": 1.0,
                "block_name": "AM",
            }
        )


def test_station_id_with_track_field_rejected() -> None:
    # extra="forbid": a station_id must not carry a track.
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python(
            {
                "kind": "station_id",
                "planned_start": _START.isoformat(),
                "duration": 5.0,
                "block_name": "AM",
                "track": _TRACK.model_dump(mode="json"),
            }
        )


def test_unknown_kind_rejected() -> None:
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python(
            {
                "kind": "advert",
                "planned_start": _START.isoformat(),
                "duration": 1.0,
                "block_name": "AM",
            }
        )


# --- shared field validation -----------------------------------------------------


def test_planned_start_must_be_tz_aware() -> None:
    with pytest.raises(ValidationError):
        StationIdItem(planned_start=datetime(2026, 6, 10, 9, 0), duration=5.0, block_name="AM")


def test_duration_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        StationIdItem(planned_start=_START, duration=0.0, block_name="AM")


def test_block_name_required() -> None:
    with pytest.raises(ValidationError):
        StationIdItem(planned_start=_START, duration=5.0, block_name="")


# --- DailySchedule + persistence round-trip --------------------------------------


def _sample_schedule() -> DailySchedule:
    return DailySchedule(
        date=date(2026, 6, 10),
        station="PiRate One",
        seed=12345,
        items=(
            StationIdItem(planned_start=_START, duration=5.0, block_name="AM"),
            TrackItem(planned_start=_START, duration=180.0, block_name="AM", track=_TRACK),
            BlockTransitionItem(
                planned_start=_START,
                duration=8.0,
                block_name="AM",
                next_block_name="Lunch",
                next_block_starts_at=_START,
            ),
            BlockReminderItem(planned_start=_START, duration=8.0, block_name="Lunch"),
        ),
    )


def test_daily_schedule_requires_items() -> None:
    with pytest.raises(ValidationError):
        DailySchedule(date=date(2026, 6, 10), station="S", seed=1, items=())


def test_daily_schedule_is_frozen() -> None:
    sched = _sample_schedule()
    with pytest.raises(ValidationError):
        sched.station = "Other"  # type: ignore[misc]


def test_json_round_trip_preserves_each_variant() -> None:
    # The load-bearing R17 test: dump to JSON, reload, and every item is routed back
    # to its concrete variant type (so resume reconstructs the schedule exactly).
    sched = _sample_schedule()
    reloaded = DailySchedule.model_validate_json(sched.model_dump_json())
    assert reloaded == sched
    assert [type(i) for i in reloaded.items] == [
        StationIdItem,
        TrackItem,
        BlockTransitionItem,
        BlockReminderItem,
    ]
    assert isinstance(reloaded.items[1], TrackItem)
    assert reloaded.items[1].track == _TRACK


# --- hardening folded in from the P1-1 review (QA, Senior Dev, Devil's Advocate) ---

_VARIANTS = [
    StationIdItem(planned_start=_START, duration=5.0, block_name="AM"),
    TrackItem(planned_start=_START, duration=180.0, block_name="AM", track=_TRACK),
    BlockTransitionItem(
        planned_start=_START,
        duration=8.0,
        block_name="AM",
        next_block_name="Lunch",
        next_block_starts_at=_START,
    ),
    BlockReminderItem(planned_start=_START, duration=8.0, block_name="AM"),
]


@pytest.mark.parametrize("item", _VARIANTS)
def test_schedule_item_variants_are_frozen(item: ScheduleItem) -> None:
    with pytest.raises(ValidationError):
        item.duration = 999.0  # type: ignore[misc]


def test_block_transition_next_start_must_be_tz_aware() -> None:
    with pytest.raises(ValidationError):
        BlockTransitionItem(
            planned_start=_START,
            duration=8.0,
            block_name="AM",
            next_block_name="Lunch",
            next_block_starts_at=datetime(2026, 6, 10, 12, 0),  # naive
        )


def test_block_transition_missing_next_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python(
            {
                "kind": "block_transition",
                "planned_start": _START.isoformat(),
                "duration": 8.0,
                "block_name": "AM",
            }
        )


def test_track_item_rejects_stray_transition_field() -> None:
    # extra="forbid" on the most-confusable variant: a track must not carry
    # block_transition fields (Devil's Advocate).
    with pytest.raises(ValidationError):
        _ADAPTER.validate_python(
            {
                "kind": "track",
                "planned_start": _START.isoformat(),
                "duration": 180.0,
                "block_name": "AM",
                "track": _TRACK.model_dump(mode="json"),
                "next_block_name": "Lunch",
            }
        )
