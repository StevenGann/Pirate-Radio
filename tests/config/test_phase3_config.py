"""RED tests for Phase-3 config additions — plan §4.7 / §6 (P3-6).

Tests first (strict spec-driven TDD): the cloud-TTS credential preflight (the cloud half of
0010, deferred from Phase 2) — a station using the ``elevenlabs`` backend must have its
``api_key_env`` set AND non-empty at boot (mirrors the LLM A1 check) — and a minimal Ollama
``endpoint`` shape check (``http://``/``https://`` prefix) so a typo fails at boot, not at first
patter. preflight=False (no real binaries needed for shape/env validation).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pirate_radio.audio_devices import StaticAudioDeviceResolver
from pirate_radio.config import load_config
from pirate_radio.errors import ConfigError


@pytest.fixture
def resolver() -> StaticAudioDeviceResolver:
    return StaticAudioDeviceResolver({"usb-port-1": "phys-A"})


def _cfg(content_tree: Path, schedule_dir: Path) -> dict:
    return {
        "llm": {
            "providers": [{"backend": "claude", "model": "x", "api_key_env": "ANTHROPIC_API_KEY"}]
        },
        "tts_providers": {},
        "state_dir": str(Path(schedule_dir).parent),
        "stations": [
            {
                "name": "PiRate One",
                "schedule_dir": str(schedule_dir),
                "content_dir": str(content_tree),
                "dj_personality": "calm",
                "tts": [{"backend": "piper", "voice": "en_US-ryan-high"}],
                "audio_device": "usb-port-1",
            }
        ],
    }


def _load(tmp_path: Path, data: dict, resolver: StaticAudioDeviceResolver, clock: object):
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return load_config(p, resolver=resolver, clock=clock, preflight=False)  # type: ignore[arg-type]


# ---- ElevenLabs cloud-credential preflight (0010 cloud half) ------------------------------
def test_elevenlabs_station_missing_api_key_env_rejected(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock, monkeypatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    data = _cfg(content_tree, grid_yaml)
    data["tts_providers"]["elevenlabs"] = {"api_key_env": "ELEVENLABS_API_KEY"}
    data["stations"][0]["tts"] = [{"backend": "elevenlabs", "voice_id": "V"}]
    with pytest.raises(ConfigError, match="TTS environment"):
        _load(tmp_path, data, resolver, fixed_clock)


def test_elevenlabs_station_blank_api_key_env_rejected(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock, monkeypatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "   ")  # A1: blank counts as missing
    data = _cfg(content_tree, grid_yaml)
    data["tts_providers"]["elevenlabs"] = {"api_key_env": "ELEVENLABS_API_KEY"}
    data["stations"][0]["tts"] = [{"backend": "elevenlabs", "voice_id": "V"}]
    with pytest.raises(ConfigError, match="TTS environment"):
        _load(tmp_path, data, resolver, fixed_clock)


def test_elevenlabs_station_with_api_key_env_loads(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock, monkeypatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "secret")
    data = _cfg(content_tree, grid_yaml)
    data["tts_providers"]["elevenlabs"] = {"api_key_env": "ELEVENLABS_API_KEY"}
    data["stations"][0]["tts"] = [{"backend": "elevenlabs", "voice_id": "V"}]
    cfg = _load(tmp_path, data, resolver, fixed_clock)
    assert cfg.stations[0].tts[0].backend == "elevenlabs"


def test_elevenlabs_station_without_provider_block_is_clean_error(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock, monkeypatch
) -> None:
    # DA: a station declaring elevenlabs but with NO tts_providers.elevenlabs block must be a
    # clean ConfigError at boot (not a crash, not a die-at-first-synth false floor).
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    data = _cfg(content_tree, grid_yaml)
    data["stations"][0]["tts"] = [{"backend": "elevenlabs", "voice_id": "V"}]
    # note: NO data["tts_providers"]["elevenlabs"]
    with pytest.raises(ConfigError):
        _load(tmp_path, data, resolver, fixed_clock)


def test_piper_station_needs_no_tts_env(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock, monkeypatch
) -> None:
    # a non-cloud station must NOT require any TTS credential (no false positive)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    cfg = _load(tmp_path, _cfg(content_tree, grid_yaml), resolver, fixed_clock)
    assert cfg.stations[0].tts[0].backend == "piper"


# ---- Ollama endpoint shape ----------------------------------------------------------------
def test_ollama_endpoint_bad_scheme_rejected(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock
) -> None:
    data = _cfg(content_tree, grid_yaml)
    data["llm"]["providers"] = [
        {"backend": "ollama", "model": "llama3", "endpoint": "localhost:11434"}
    ]
    with pytest.raises(ConfigError, match="endpoint"):
        _load(tmp_path, data, resolver, fixed_clock)


def test_ollama_endpoint_hostless_scheme_rejected(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock
) -> None:
    # DA: "http://" alone (scheme, no host) must be rejected — a startswith-only check that
    # accepts scheme-only garbage would build "http:///api/chat" and die at first patter.
    data = _cfg(content_tree, grid_yaml)
    data["llm"]["providers"] = [{"backend": "ollama", "model": "llama3", "endpoint": "http://"}]
    with pytest.raises(ConfigError, match="endpoint"):
        _load(tmp_path, data, resolver, fixed_clock)


def test_ollama_endpoint_https_scheme_loads(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock
) -> None:
    # DA: https must be accepted too (a startswith("http://")-only impl would reject all https)
    data = _cfg(content_tree, grid_yaml)
    data["llm"]["providers"] = [
        {"backend": "ollama", "model": "llama3", "endpoint": "https://lan:11434"}
    ]
    cfg = _load(tmp_path, data, resolver, fixed_clock)
    assert cfg.llm.providers[0].backend == "ollama"


def test_ollama_endpoint_valid_scheme_loads(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock
) -> None:
    data = _cfg(content_tree, grid_yaml)
    data["llm"]["providers"] = [
        {"backend": "ollama", "model": "llama3", "endpoint": "http://lan:11434"}
    ]
    cfg = _load(tmp_path, data, resolver, fixed_clock)  # ollama needs no api_key_env
    assert cfg.llm.providers[0].backend == "ollama"
