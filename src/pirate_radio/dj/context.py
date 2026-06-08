"""The typed, grounded DJ context (R16, §9.2). Frozen; no bare dicts.

Built by the producer from a ``ScheduleItem`` + its ``Track`` + the ``StationConfig`` and
handed to ``TextGenerator.patter``. Every field here is GROUNDING the prompt layer
(``dj/prompts.py``) turns into an "invent nothing" instruction — the model speaks only from
what is here. Missing tags / grid fields stay ``None`` (§9.3 best-effort), never fabricated.

R16: replaces the §9.2/§13 bare ``dict``. All three models are frozen + ``extra="forbid"``
(the stricter ``schedule/models.py`` idiom, not the looser ``Track`` one), so a typo'd or
dropped field is a loud construction error, not silent grounding drift.

``boundary_at`` is intentionally NOT tz-validated (unlike the D6 scheduling boundaries in
``schedule/models.py``): it is grounding-only, formatted ``%H:%M`` for the prompt, and the
producer always sources it from an already-D6-validated schedule datetime.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class TrackMeta(BaseModel):
    """A track's grounding facts (§9.2 layer 3). All optional — a sparsely-tagged track is
    best-effort, never skipped (§9.3). ``year`` is bounded to match ``Track.year``/A10 so a
    nonsense value can't ground a spoken intro."""

    model_config = _FROZEN

    title: str | None = None
    artist: str | None = None
    album: str | None = None
    year: int | None = Field(default=None, ge=1, le=9999)

    @property
    def is_sparse(self) -> bool:
        """True when title AND artist are both absent (a truthy test — ``""`` counts as absent,
        matching ``prompts.py``'s ``if t.title:`` guard). Drives the best-effort prompt branch."""
        return not self.title and not self.artist


class BlockContext(BaseModel):
    """A programming block's grounding (§9.2 layer 2). ``name`` is always known (the schedule
    item carries ``block_name``); ``tagline``/``description`` are grid-only and may be ``None``
    in Phase 3. ``boundary_at`` = ends_at for the current block, starts_at for the next."""

    model_config = _FROZEN

    name: str = Field(min_length=1)
    tagline: str | None = None
    description: str | None = None
    boundary_at: datetime | None = None


class DjContext(BaseModel):
    """The whole grounded context handed to ``TextGenerator.patter`` (R16). ``kind`` is the
    patter type (§9.1, validated against ``PATTER_KINDS`` downstream in ``dj/prompts.py``, not
    here); ``persona`` is the constant voice (§9.2 layer 1)."""

    model_config = _FROZEN

    kind: str = Field(min_length=1)
    persona: str = Field(min_length=1)
    station_name: str = Field(min_length=1)
    station_tagline: str | None = None
    current_block: BlockContext
    next_block: BlockContext | None = None  # transitions/reminders only
    track: TrackMeta | None = None  # intro/outro/factoid only
    recent_tracks: tuple[TrackMeta, ...] = ()  # best-effort; empty until Phase-4 history (§7-Q4)
