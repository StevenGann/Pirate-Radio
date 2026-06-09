"""RED tests for ``pirate_radio.dj.build`` — Phase 3 plan §4.5 / §6 (P3-7).

Tests first (strict spec-driven TDD): the boot seam that constructs the ranked Text/TTS chains
from config. Reads secrets by env-var NAME at construction (H22, never logged); appends the
NullDJ floor last (D2); ``build_tts_engine`` is TOTAL (exhaustive isinstance + explicit
``raise ConfigError`` + empty-chain guard, no ``assert``); honors the per-station ``llm``
override; threads config-sourced timeouts into each backend; NO network in any ``__init__``.
"""

from __future__ import annotations

import builtins
from pathlib import Path
from typing import Any

import pytest

from pirate_radio.config import (
    ClaudeLLMConfig,
    DaemonConfig,
    DeepSeekLLMConfig,
    ElevenLabsTTSConfig,
    EspeakTTSConfig,
    LLMConfig,
    OllamaLLMConfig,
    PiperTTSConfig,
    StationConfig,
)
from pirate_radio.dj.build import (
    _secret,
    build_text_generator,
    build_tts_engine,
    resolve_persona,
    resolve_station_llm,
)
from pirate_radio.dj.failover import RankedTextGenerator, RankedTTSEngine
from pirate_radio.dj.fakes import NullDJ
from pirate_radio.dj.protocols import TextGenerator, TTSEngine
from pirate_radio.dj.text import ClaudeDJ, DeepSeekDJ, OllamaDJ
from pirate_radio.dj.tts import ElevenLabsTTS, EspeakTTS, PiperTTS
from pirate_radio.errors import ConfigError


def _llm(providers: tuple[Any, ...], *, timeout: float = 20.0) -> LLMConfig:
    return LLMConfig(providers=providers, request_timeout_seconds=timeout)


def _station(
    *, tts: tuple[Any, ...], llm: LLMConfig | None = None, persona: str = "calm"
) -> StationConfig:
    return StationConfig(
        name="PiRate One",
        schedule_dir=Path("/sched"),
        content_dir=Path("/content"),
        dj_personality=persona,
        tts=tts,
        audio_device="usb-1",
        llm=llm,
    )


def _config(
    station: StationConfig, *, tts_providers: dict, tts_timeout: float = 30.0
) -> DaemonConfig:
    return DaemonConfig(
        llm=_llm((ClaudeLLMConfig(backend="claude", model="m", api_key_env="ANTHROPIC_API_KEY"),)),
        tts_providers=tts_providers,
        tts_timeout_seconds=tts_timeout,
        state_dir=Path("/state"),
        stations=(station,),
    )


# ---- _secret (H22: read by name, raise naming the var not the value) ----------------------
def test_secret_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_KEY", "abc123")
    assert _secret("MY_KEY") == "abc123"


def test_secret_missing_raises_naming_var_not_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MY_KEY", raising=False)
    with pytest.raises(ConfigError, match="MY_KEY"):
        _secret("MY_KEY")


def test_secret_blank_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_KEY", "   ")  # A1: blank counts as unset
    with pytest.raises(ConfigError):
        _secret("MY_KEY")


# ---- build_text_generator: backend->class mapping + NullDJ floor last ----------------------
def test_build_text_generator_maps_all_three_and_appends_nulldj(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    llm = _llm(
        (
            ClaudeLLMConfig(backend="claude", model="m", api_key_env="ANTHROPIC_API_KEY"),
            DeepSeekLLMConfig(backend="deepseek", model="m", api_key_env="DEEPSEEK_API_KEY"),
            OllamaLLMConfig(backend="ollama", model="m", endpoint="http://lan:11434"),
        )
    )
    gen = build_text_generator(llm)
    assert isinstance(gen, RankedTextGenerator) and isinstance(gen, TextGenerator)
    provs = gen._providers
    assert isinstance(provs[0], ClaudeDJ)
    assert isinstance(provs[1], DeepSeekDJ)
    assert isinstance(provs[2], OllamaDJ)
    assert isinstance(provs[-1], NullDJ)  # D2 floor, always last
    assert sum(isinstance(p, NullDJ) for p in provs) == 1  # exactly one floor, only at the end


def test_build_text_generator_empty_providers_yields_nulldj_floor() -> None:
    # defense-in-depth: even an empty provider list (forced past min_length) yields a usable
    # NullDJ-only chain, never an empty one — the text floor can never be absent (D2).
    llm = LLMConfig.model_construct(providers=())
    gen = build_text_generator(llm)
    assert len(gen._providers) == 1 and isinstance(gen._providers[0], NullDJ)


def test_build_text_generator_threads_timeout_to_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    # the config timeout is applied UNIFORMLY across all three backends (overriding per-backend
    # constructor defaults, incl. Ollama's 30s) — pin Ollama too so the threading isn't Claude-only.
    llm = _llm((OllamaLLMConfig(backend="ollama", model="m", endpoint="http://x:1"),), timeout=9.0)
    gen = build_text_generator(llm)
    assert gen._providers[0]._timeout == 9.0


def test_build_text_generator_threads_config_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    llm = _llm(
        (ClaudeLLMConfig(backend="claude", model="m", api_key_env="ANTHROPIC_API_KEY"),),
        timeout=7.5,
    )
    gen = build_text_generator(llm)
    assert gen._providers[0]._timeout == 7.5  # config-tunable timeout actually plumbed (H23)


def test_build_text_generator_missing_secret_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    llm = _llm((ClaudeLLMConfig(backend="claude", model="m", api_key_env="ANTHROPIC_API_KEY"),))
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        build_text_generator(llm)


# ---- build_tts_engine: mapping + totality (exhaustive + empty-chain guard) -----------------
def test_build_tts_engine_maps_all_three(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    station = _station(
        tts=(
            PiperTTSConfig(backend="piper", voice="en_US-ryan-high"),
            EspeakTTSConfig(backend="espeak", voice="en"),
            ElevenLabsTTSConfig(backend="elevenlabs", voice_id="V"),
        )
    )
    config = _config(
        station,
        tts_providers={
            "piper": {"voices_dir": "/voices"},  # piper1-gpl: python -m piper, no binary
            "espeak": {},
            "elevenlabs": {"api_key_env": "ELEVENLABS_API_KEY"},
        },
    )
    eng = build_tts_engine(station, config, sample_rate=48000, channels=1)
    assert isinstance(eng, RankedTTSEngine) and isinstance(eng, TTSEngine)
    assert isinstance(eng._providers[0], PiperTTS)
    assert isinstance(eng._providers[1], EspeakTTS)
    assert isinstance(eng._providers[2], ElevenLabsTTS)


def test_build_tts_engine_threads_config_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    station = _station(tts=(ElevenLabsTTSConfig(backend="elevenlabs", voice_id="V"),))
    config = _config(
        station,
        tts_providers={"elevenlabs": {"api_key_env": "ELEVENLABS_API_KEY"}},
        tts_timeout=12.0,
    )
    eng = build_tts_engine(station, config, sample_rate=48000, channels=1)
    assert eng._providers[0]._timeout == 12.0  # config tts_timeout_seconds plumbed


def test_build_tts_engine_empty_chain_raises() -> None:
    # defense-in-depth: a station with no constructible TTS must raise, never an always-exhausting
    # RankedTTSEngine([]) (StationConfig.tts has min_length=1, so force it via model_construct).
    station = StationConfig.model_construct(name="X", tts=())
    config = _config(
        _station(tts=(PiperTTSConfig(backend="piper", voice="v"),)),
        tts_providers={"piper": {"voices_dir": "/v"}},
    )
    with pytest.raises(ConfigError, match="at least one TTS"):
        build_tts_engine(station, config, sample_rate=48000, channels=1)


def test_build_tts_engine_unknown_backend_raises() -> None:
    # an unrecognised tts entry (forced past the discriminated union) is a loud ConfigError
    class _Bogus:
        pass

    station = StationConfig.model_construct(name="X", tts=(_Bogus(),))
    config = _config(
        _station(tts=(PiperTTSConfig(backend="piper", voice="v"),)),
        tts_providers={"piper": {"voices_dir": "/v"}},
    )
    with pytest.raises(ConfigError):
        build_tts_engine(station, config, sample_rate=48000, channels=1)


def test_build_tts_engine_elevenlabs_missing_api_key_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    station = _station(tts=(ElevenLabsTTSConfig(backend="elevenlabs", voice_id="V"),))
    config = _config(station, tts_providers={"elevenlabs": {"api_key_env": "ELEVENLABS_API_KEY"}})
    with pytest.raises(ConfigError, match="ELEVENLABS_API_KEY"):
        build_tts_engine(station, config, sample_rate=48000, channels=1)


# ---- per-station llm override + persona resolution -----------------------------------------
def test_resolve_station_llm_prefers_station_override() -> None:
    global_llm = _llm((ClaudeLLMConfig(backend="claude", model="g", api_key_env="A"),))
    station_llm = _llm((OllamaLLMConfig(backend="ollama", model="s", endpoint="http://x:1"),))
    config = DaemonConfig(
        llm=global_llm,
        tts_providers={},
        state_dir=Path("/s"),
        stations=(_station(tts=(PiperTTSConfig(backend="piper", voice="v"),), llm=station_llm),),
    )
    assert resolve_station_llm(config.stations[0], config) is station_llm


def test_resolve_station_llm_falls_back_to_global() -> None:
    station = _station(tts=(PiperTTSConfig(backend="piper", voice="v"),), llm=None)
    config = _config(station, tts_providers={"piper": {"voices_dir": "/v"}})
    assert resolve_station_llm(station, config) is config.llm


def test_resolve_persona_inline() -> None:
    station = _station(tts=(PiperTTSConfig(backend="piper", voice="v"),), persona="a warm host")
    assert resolve_persona(station) == "a warm host"


def test_resolve_persona_from_file(tmp_path: Path) -> None:
    p = tmp_path / "persona.md"
    p.write_text("from the file", encoding="utf-8")
    station = StationConfig(
        name="S",
        schedule_dir=Path("/s"),
        content_dir=Path("/c"),
        dj_personality_file=p,
        tts=(PiperTTSConfig(backend="piper", voice="v"),),
        audio_device="d",
    )
    assert resolve_persona(station) == "from the file"


def test_resolve_persona_unreadable_file_raises_configerror(tmp_path: Path) -> None:
    # Old Man: a missing/unreadable persona file must be a typed ConfigError naming the path,
    # not a raw OSError traceback at boot (consistent with the project's IO-boundary idiom).
    station = StationConfig(
        name="S",
        schedule_dir=tmp_path,
        content_dir=Path("/c"),
        dj_personality_file=Path("nope.md"),  # tmp_path/nope.md does not exist
        tts=(PiperTTSConfig(backend="piper", voice="v"),),
        audio_device="d",
    )
    with pytest.raises(ConfigError, match="persona"):
        resolve_persona(station)


# ---- H22: the secret VALUE never reaches a log record (the module's reason to exist) -------
async def test_no_secret_value_in_logs_after_failed_patter(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pirate_radio.dj.context import BlockContext, DjContext

    monkeypatch.setenv("ANTHROPIC_API_KEY", "SUPERSECRET")
    # the backend fails WITHOUT the key in its message; prove the key (stored on the provider)
    # never leaks into the failover WARNING or any other record.
    monkeypatch.setattr(
        ClaudeDJ,
        "_blocking_call",
        lambda self, s, u: (_ for _ in ()).throw(RuntimeError("upstream 503")),
    )
    gen = build_text_generator(
        _llm((ClaudeLLMConfig(backend="claude", model="m", api_key_env="ANTHROPIC_API_KEY"),))
    )
    ctx = DjContext(
        kind="station_id", persona="p", station_name="s", current_block=BlockContext(name="b")
    )
    with caplog.at_level("WARNING"):
        assert await gen.patter(ctx) == ""  # falls through Claude -> NullDJ floor
    assert all("SUPERSECRET" not in r.getMessage() for r in caplog.records)


# ---- no network touched in any __init__ (R21) ---------------------------------------------
def test_build_imports_no_network_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    real_import = builtins.__import__

    def guard(name: str, *a: object, **k: object) -> Any:
        if name.split(".")[0] in {"anthropic", "httpx"}:
            raise AssertionError(f"build seam imported {name!r} (R21: __init__ is network-free)")
        return real_import(name, *a, **k)

    llm = _llm(
        (
            ClaudeLLMConfig(backend="claude", model="m", api_key_env="ANTHROPIC_API_KEY"),
            DeepSeekLLMConfig(backend="deepseek", model="m", api_key_env="DEEPSEEK_API_KEY"),
            OllamaLLMConfig(backend="ollama", model="m", endpoint="http://x:1"),
        )
    )
    station = _station(tts=(ElevenLabsTTSConfig(backend="elevenlabs", voice_id="V"),))
    config = _config(station, tts_providers={"elevenlabs": {"api_key_env": "ELEVENLABS_API_KEY"}})
    monkeypatch.setattr(builtins, "__import__", guard)
    build_text_generator(llm)
    build_tts_engine(station, config, sample_rate=48000, channels=1)
