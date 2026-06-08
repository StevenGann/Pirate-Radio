"""config.json models, loader, and fail-fast validation (§12, R16, R10, A1-A4).

Discriminated unions keyed on ``backend`` (R16) make a typo'd provider param fail at
load, not mid-broadcast. All §12 checks run at load: unique station names, audio
devices that resolve to distinct stable PortIds (R10/A2), exactly one of
dj_personality/_file, every LLM ``api_key_env`` present AND non-empty (A1; TTS
credential preflight is a Phase-2 carry-forward), schedule_dir/content_dir
exist with >= 1 valid grid / >= 1 non-empty group, and known tts_providers backend
keys (A3). The weekday for grid resolution comes from an injected ``Clock`` (A4), so
``clock.py`` stays the only ``datetime.now()`` site.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pirate_radio.audio_devices import AudioDeviceResolver, PortId
from pirate_radio.catalog.scanner import scan_catalog
from pirate_radio.clock import Clock
from pirate_radio.errors import ConfigError
from pirate_radio.schedule.grid import (
    load_grid,
    resolve_grid_path,
    validate_grid_against_catalog,
)

logger = logging.getLogger(__name__)

_FROZEN = ConfigDict(frozen=True, extra="forbid")  # extra="forbid": typos are errors
_KNOWN_TTS_BACKENDS = frozenset({"piper", "espeak", "elevenlabs"})


# ---- TTS provider configs (R16: discriminated union on `backend`) ---------------
class PiperTTSConfig(BaseModel):
    model_config = _FROZEN
    backend: Literal["piper"]
    voice: str
    speed: float = 1.0


class EspeakTTSConfig(BaseModel):
    model_config = _FROZEN
    backend: Literal["espeak"]
    voice: str
    speed: float = 1.0
    pitch: int = 50


class ElevenLabsTTSConfig(BaseModel):
    model_config = _FROZEN
    backend: Literal["elevenlabs"]
    voice_id: str
    stability: float = 0.5
    similarity_boost: float = 0.75


TTSConfig = Annotated[
    PiperTTSConfig | EspeakTTSConfig | ElevenLabsTTSConfig,
    Field(discriminator="backend"),
]


# ---- LLM provider configs (R16: discriminated union on `backend`, D2) -----------
class ClaudeLLMConfig(BaseModel):
    model_config = _FROZEN
    backend: Literal["claude"]
    model: str
    api_key_env: str


class DeepSeekLLMConfig(BaseModel):
    model_config = _FROZEN
    backend: Literal["deepseek"]
    model: str
    api_key_env: str


class OllamaLLMConfig(BaseModel):
    model_config = _FROZEN
    backend: Literal["ollama"]
    model: str
    endpoint: str  # self-hosted LAN server (D2), not on-Pi inference


LLMProviderConfig = Annotated[
    ClaudeLLMConfig | DeepSeekLLMConfig | OllamaLLMConfig,
    Field(discriminator="backend"),
]


class LLMConfig(BaseModel):
    model_config = _FROZEN
    providers: tuple[LLMProviderConfig, ...] = Field(min_length=1)
    max_requests_per_minute: int = Field(default=20, gt=0)


class StationConfig(BaseModel):
    """Per-station settings (§13). Filesystem fields are checked by validate_config;
    Pydantic only validates shape here."""

    model_config = _FROZEN
    name: str = Field(min_length=1)
    tagline: str | None = None
    description: str | None = None
    schedule_dir: Path
    content_dir: Path
    dj_personality: str | None = None
    dj_personality_file: Path | None = None
    tts: tuple[TTSConfig, ...] = Field(min_length=1)
    audio_device: str = Field(min_length=1)
    llm: LLMConfig | None = None  # optional per-station override (§12)
    transition_silence_seconds: float = Field(default=2.0, ge=0)
    # EBU R128 target; LUFS is <= 0 by definition (le=0), ge=-40 catches typo'd values
    # like -160 (would otherwise hit the loudness gain clamp silently). Phase-2 carry-forward
    # from 0010 resolved.
    loudness_target_lufs: float = Field(default=-16.0, ge=-40.0, le=0.0)
    repeat_window_minutes: int = Field(default=120, ge=0)

    @model_validator(mode="after")
    def _exactly_one_persona(self) -> StationConfig:
        has_inline = self.dj_personality is not None
        has_file = self.dj_personality_file is not None
        if has_inline == has_file:  # both or neither
            raise ConfigError(
                f"station '{self.name}': set exactly one of dj_personality / dj_personality_file"
            )
        return self


class DaemonConfig(BaseModel):
    model_config = _FROZEN
    llm: LLMConfig
    tts_providers: dict[str, dict[str, object]] = Field(default_factory=dict)
    state_dir: Path  # A6: mutable-state root (schedules, future resume/cache) off the boot SD
    stations: tuple[StationConfig, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _known_tts_provider_backends(self) -> DaemonConfig:
        # A3: tts_providers holds shared credentials keyed by backend name. Inner
        # credential keys are validated in Phase 2 when an engine reads them, but a
        # typo'd *backend* key (e.g. "elevenlabss") is a real boot-catchable error.
        unknown = sorted(set(self.tts_providers) - _KNOWN_TTS_BACKENDS)
        if unknown:
            raise ConfigError(
                f"unknown tts_providers backend key(s): {unknown}; "
                f"known: {sorted(_KNOWN_TTS_BACKENDS)}"
            )
        return self


def load_config(path: Path, *, resolver: AudioDeviceResolver, clock: Clock) -> DaemonConfig:
    """Load + fully validate config.json (§12). ``resolver`` injects R10 PortIds;
    ``clock`` (A4) supplies the weekday for the grid-existence check (so clock.py is
    the only ``datetime.now()`` site)."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc

    try:
        config = DaemonConfig.model_validate(raw)
    except ConfigError:
        raise
    except Exception as exc:  # pydantic ValidationError
        raise ConfigError(f"{path}: invalid config: {exc}") from exc

    _validate_config(config, resolver=resolver, weekday=clock.now().weekday())
    return config


def _validate_config(config: DaemonConfig, *, resolver: AudioDeviceResolver, weekday: int) -> None:
    """All §12 fail-fast cross-field/filesystem/env checks."""
    _check_unique_station_names(config)
    _check_audio_devices(config, resolver)
    _check_env_vars_present(config)
    _check_state_dir(config)
    for station in config.stations:
        _check_station_dirs(station, weekday)


def _check_state_dir(config: DaemonConfig) -> None:
    """A6: state_dir must exist AND be writable (it's where schedules/cache are written).

    Only state_dir is writability-checked; content_dir/schedule_dir are read-only by
    nature (curated library + hand-authored grids, possibly a read-only mount) and only
    need to be readable — the narrowed A6 reading ratified 7/7 in 0009 §Q1.
    """
    sd = config.state_dir
    if not sd.is_dir():
        raise ConfigError(f"state_dir missing or not a directory: {sd}")
    if not os.access(sd, os.W_OK):
        raise ConfigError(f"state_dir is not writable: {sd}")
    logger.info("state_dir resolved to %s", sd)  # A6: log where mutable writes land


def _check_unique_station_names(config: DaemonConfig) -> None:
    names = [s.name for s in config.stations]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ConfigError(f"duplicate station names: {dupes}")


def _check_audio_devices(config: DaemonConfig, resolver: AudioDeviceResolver) -> None:
    """R10/A2: each audio_device resolves to a stable PortId, and no two stations
    resolve to the *same* physical port (catches distinct names aliasing one port)."""
    seen: dict[PortId, str] = {}
    for station in config.stations:
        pid = resolver.resolve(station.audio_device)
        if pid is None:
            raise ConfigError(
                f"station '{station.name}': audio_device {station.audio_device!r} does not "
                f"resolve to a stable device name (R10)"
            )
        if pid in seen:
            raise ConfigError(
                f"stations '{seen[pid]}' and '{station.name}' resolve to the same physical "
                f"audio device (R10): {pid!r}"
            )
        seen[pid] = station.name


def _check_env_vars_present(config: DaemonConfig) -> None:
    """Validate LLM provider ``api_key_env`` vars are present AND non-empty (§12, A1:
    a blank value is a failed EnvironmentFile/SOPS, not a valid secret).

    Scope note: this currently covers **LLM** credentials only. ``tts_providers``
    credentials are NOT checked here yet — a station using a cloud TTS backend boots
    clean and would only fail at first synth. The TTS-credential preflight lands in
    Phase 2 when a TTS engine actually reads those vars (carry-forward, 0010)."""
    needed: set[str] = set()
    chains = [config.llm.providers]
    chains += [s.llm.providers for s in config.stations if s.llm is not None]
    for providers in chains:
        for prov in providers:
            env_name = getattr(prov, "api_key_env", None)
            if env_name:
                needed.add(env_name)
    missing = sorted(n for n in needed if not os.environ.get(n, "").strip())
    if missing:
        raise ConfigError(f"required environment variables not set or empty: {missing}")


def _check_station_dirs(station: StationConfig, weekday: int) -> None:
    """schedule_dir/content_dir exist; >= 1 resolvable+valid grid; >= 1 non-empty group."""
    if not station.schedule_dir.is_dir():
        raise ConfigError(f"station '{station.name}': schedule_dir missing: {station.schedule_dir}")
    if not station.content_dir.is_dir():
        raise ConfigError(f"station '{station.name}': content_dir missing: {station.content_dir}")
    if station.dj_personality_file is not None:
        persona_path = station.schedule_dir / station.dj_personality_file
        if not persona_path.is_file():
            raise ConfigError(
                f"station '{station.name}': dj_personality_file not found: {persona_path}"
            )

    catalog = scan_catalog(station.content_dir)  # raises CatalogError if no non-empty group
    non_empty = frozenset(g for g in catalog.group_names() if catalog.is_group_non_empty(g))

    grid_path = resolve_grid_path(station.schedule_dir, weekday)  # raises if none
    grid = load_grid(grid_path)
    validate_grid_against_catalog(grid, non_empty, grid_path)
