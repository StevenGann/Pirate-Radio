"""Construct the ranked TextGenerator / TTSEngine chains from config (§12) — the boot seam.

Reads the ordered ``llm.providers`` (or a station's ``llm`` override) and a station's ordered
``tts`` list, constructs each concrete backend, appends the floor (``NullDJ`` for text), and wraps
in the RankedProvider drop-in. Secrets are read from the environment HERE, by name
(``api_key_env``), at construction time (H22) — never stored in config, never logged. This is the
ONLY module that knows the backend->class mapping; failover/text/tts stay backend-agnostic. No
``__init__`` touches the network (R21) — the SDK/httpx imports are lazy, inside the call methods.
"""

from __future__ import annotations

import os

from pirate_radio.config import (
    ClaudeLLMConfig,
    DaemonConfig,
    DeepSeekLLMConfig,
    LLMConfig,
    OllamaLLMConfig,
    StationConfig,
)
from pirate_radio.dj.failover import RankedTextGenerator, RankedTTSEngine
from pirate_radio.dj.fakes import NullDJ
from pirate_radio.dj.text import ClaudeDJ, DeepSeekDJ, OllamaDJ
from pirate_radio.errors import ConfigError


def _secret(env_name: str) -> str:
    """Read a credential from the environment by NAME at call time (H22). Blank == unset (A1).
    The error names the env var, NEVER the value (security rule)."""
    val = os.environ.get(env_name, "").strip()
    if not val:  # belt-and-suspenders; config preflight (A1) already checked this at boot
        raise ConfigError(f"environment variable {env_name} is not set or empty")
    return val


def resolve_station_llm(station: StationConfig, config: DaemonConfig) -> LLMConfig:
    """The §12/R-D2 per-station override: a station's own ``llm`` wins, else the daemon global."""
    return station.llm or config.llm


def resolve_persona(station: StationConfig) -> str:
    """The DJ persona text (§9.2 layer 1): inline ``dj_personality`` or the contents of
    ``dj_personality_file`` (resolved relative to ``schedule_dir``, matching the boot check).
    Exactly one is set (validated at load). Read here at boot; the producer threads it into each
    ``DjContext`` (persona is per-context, not per-provider)."""
    if station.dj_personality is not None:
        return station.dj_personality
    if station.dj_personality_file is None:  # _exactly_one_persona should guarantee this
        raise ConfigError(f"station {station.name!r}: no DJ persona configured (inline or file)")
    path = station.schedule_dir / station.dj_personality_file
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:  # typed boundary error, names the path
        raise ConfigError(
            f"station {station.name!r}: cannot read persona file {path}: {exc}"
        ) from exc


def build_text_generator(llm: LLMConfig) -> RankedTextGenerator:
    """Build the ranked text chain (Claude->DeepSeek->Ollama->NullDJ floor). The config
    ``request_timeout_seconds`` is threaded UNIFORMLY into every backend (H23)."""
    timeout = llm.request_timeout_seconds
    chain: list[object] = []
    for prov in llm.providers:
        if isinstance(prov, ClaudeLLMConfig):
            chain.append(
                ClaudeDJ(
                    model=prov.model, api_key=_secret(prov.api_key_env), timeout_seconds=timeout
                )
            )
        elif isinstance(prov, DeepSeekLLMConfig):
            chain.append(
                DeepSeekDJ(
                    model=prov.model, api_key=_secret(prov.api_key_env), timeout_seconds=timeout
                )
            )
        elif isinstance(prov, OllamaLLMConfig):
            chain.append(
                OllamaDJ(model=prov.model, endpoint=prov.endpoint, timeout_seconds=timeout)
            )
        else:  # pragma: no cover - the discriminated union is exhaustive
            raise ConfigError(f"unknown LLM backend: {prov!r}")
    chain.append(NullDJ())  # D2: the ultimate DJ-brain floor, always last
    return RankedTextGenerator(chain)


def build_tts_engine(
    station: StationConfig, config: DaemonConfig, *, sample_rate: int, channels: int
) -> RankedTTSEngine:
    """Build the station's ranked TTS chain (Piper/Espeak from Phase 2 + ElevenLabsTTS). The TTS
    classes import numpy/audio, so they are imported lazily to keep this module light; the config
    ``tts_timeout_seconds`` is threaded into each backend (H23). TOTAL: an unknown backend or an
    empty chain is a loud ConfigError, never a silently-exhausting RankedTTSEngine([])."""
    from pirate_radio.config import (
        ElevenLabsProviderConfig,
        ElevenLabsTTSConfig,
        EspeakTTSConfig,
        PiperTTSConfig,
    )
    from pirate_radio.dj.tts import ElevenLabsTTS, EspeakTTS, PiperTTS

    timeout = config.tts_timeout_seconds
    chain: list[object] = []
    for tts in station.tts:
        if isinstance(tts, PiperTTSConfig):
            chain.append(
                PiperTTS(
                    cfg=tts,
                    provider=config.provider("piper"),  # type: ignore[arg-type]
                    sample_rate=sample_rate,
                    timeout_seconds=timeout,
                )
            )
        elif isinstance(tts, EspeakTTSConfig):
            chain.append(
                EspeakTTS(
                    cfg=tts,
                    provider=config.provider("espeak"),  # type: ignore[arg-type]
                    sample_rate=sample_rate,
                    timeout_seconds=timeout,
                )
            )
        elif isinstance(tts, ElevenLabsTTSConfig):
            prov = config.provider("elevenlabs")
            if not isinstance(prov, ElevenLabsProviderConfig):  # explicit raise, not assert
                raise ConfigError(
                    f"station {station.name!r}: tts backend 'elevenlabs' needs an "
                    f"ElevenLabsProviderConfig, got {type(prov).__name__}"
                )
            chain.append(
                ElevenLabsTTS(
                    cfg=tts,
                    provider=prov,
                    api_key=_secret(prov.api_key_env),
                    sample_rate=sample_rate,
                    timeout_seconds=timeout,
                )
            )
        else:  # unknown backend (forced past the discriminated union) — fail loud
            raise ConfigError(f"station {station.name!r}: unknown TTS backend {tts!r}")
    if not chain:  # empty-chain guard: a RankedTTSEngine([]) would always exhaust -> dead air
        raise ConfigError(f"station {station.name!r}: at least one TTS backend is required")
    return RankedTTSEngine(chain)
