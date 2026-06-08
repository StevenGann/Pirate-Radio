"""All Phase-0 value-object models must be frozen (immutability house rule).

Folded in at the grid review (Senior Dev): rather than a per-model frozen test, one
shared parametrized test closes the recurring gap across Track / Catalog / Slot /
Grid in a single place. A future change dropping ``frozen=True`` from any of them
fails here.
"""

from __future__ import annotations

from datetime import time
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from pirate_radio.catalog.models import Track
from pirate_radio.catalog.scanner import Catalog
from pirate_radio.config import PiperTTSConfig, StationConfig
from pirate_radio.schedule.grid import Grid, Slot

_TRACK = Track(path=Path("/lib/a.wav"), group="g", duration=1.0)
_SLOT = Slot(start=time(0, 0), end=time(0, 0), group="g", name="n")
_STATION = StationConfig(
    name="s",
    schedule_dir=Path("/sched"),
    content_dir=Path("/lib"),
    dj_personality="p",
    tts=({"backend": "piper", "voice": "v"},),
    audio_device="d",
)


@pytest.mark.parametrize(
    ("model", "attr", "value"),
    [
        (_TRACK, "duration", 2.0),
        (Catalog(content_dir=Path("/lib"), tracks=(_TRACK,)), "tracks", ()),
        (_SLOT, "name", "other"),
        (Grid(name="g", slots=(_SLOT,)), "name", "other"),
        (PiperTTSConfig(backend="piper", voice="v"), "speed", 2.0),
        (_STATION, "name", "other"),
    ],
)
def test_phase0_models_are_frozen(model: BaseModel, attr: str, value: object) -> None:
    with pytest.raises(ValidationError):
        setattr(model, attr, value)
