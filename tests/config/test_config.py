"""RED tests for ``pirate_radio.config`` — from Phase 0 plan §4.9 / §6.7.

Tests first (strict spec-driven TDD): config.json modelling, loading, and §12
fail-fast validation, before config.py exists. Injects ``StaticAudioDeviceResolver``
(R10) and a ``FixedClock`` (A4 — load_config takes a Clock, not a raw weekday, so
``clock.py`` stays the only ``datetime.now()`` site) — no hardware, no system clock.

Amendments folded in: A1 (empty/blank env var rejected, not just absent),
A3 (unknown ``tts_providers`` backend key rejected). The R10 resolver fixture lives
here (not conftest) so the not-yet-existing ``audio_devices`` import only breaks
config collection during RED, not the whole suite.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pirate_radio.audio_devices import StaticAudioDeviceResolver
from pirate_radio.config import load_config
from pirate_radio.errors import ConfigError, PirateRadioError


@pytest.fixture
def resolver() -> StaticAudioDeviceResolver:
    # A2: resolver maps each device name to a stable physical PortId. Distinctness
    # is checked on the resolved port, not the raw config string.
    return StaticAudioDeviceResolver({"usb-port-1": "phys-A", "usb-port-2": "phys-B"})


def _valid_config(content_tree: Path, schedule_dir: Path) -> dict:
    return {
        "llm": {
            "providers": [{"backend": "claude", "model": "x", "api_key_env": "ANTHROPIC_API_KEY"}]
        },
        "tts_providers": {},
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


def _write_cfg(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _load(tmp_path, data, resolver, clock):
    return load_config(_write_cfg(tmp_path, data), resolver=resolver, clock=clock)


# --- happy path + discriminated unions (R16) ------------------------------------


def test_loads_valid_config(tmp_path, content_tree, grid_yaml, resolver, fixed_clock, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    cfg = _load(tmp_path, _valid_config(content_tree, grid_yaml), resolver, fixed_clock)
    assert cfg.stations[0].tts[0].backend == "piper"  # discriminated union resolved
    assert cfg.llm.providers[0].backend == "claude"


def test_typo_in_tts_param_rejected(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    data = _valid_config(content_tree, grid_yaml)
    data["stations"][0]["tts"][0]["speeed"] = 1.0  # typo -> extra="forbid"
    with pytest.raises(ConfigError):
        _load(tmp_path, data, resolver, fixed_clock)


def test_unknown_tts_backend_rejected(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    data = _valid_config(content_tree, grid_yaml)
    data["stations"][0]["tts"][0] = {"backend": "festival", "voice": "x"}
    with pytest.raises(ConfigError):
        _load(tmp_path, data, resolver, fixed_clock)


def test_unknown_llm_backend_rejected(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    data = _valid_config(content_tree, grid_yaml)
    data["llm"]["providers"][0] = {"backend": "gpt", "model": "x", "api_key_env": "K"}
    with pytest.raises(ConfigError):
        _load(tmp_path, data, resolver, fixed_clock)


# --- persona (exactly one) ------------------------------------------------------


def test_both_persona_fields_rejected(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    data = _valid_config(content_tree, grid_yaml)
    data["stations"][0]["dj_personality_file"] = "persona.md"  # now both set
    with pytest.raises(ConfigError, match="exactly one"):
        _load(tmp_path, data, resolver, fixed_clock)


def test_neither_persona_field_rejected(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    data = _valid_config(content_tree, grid_yaml)
    del data["stations"][0]["dj_personality"]  # now neither set
    with pytest.raises(ConfigError, match="exactly one"):
        _load(tmp_path, data, resolver, fixed_clock)


def test_persona_file_not_found_rejected(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    data = _valid_config(content_tree, grid_yaml)
    del data["stations"][0]["dj_personality"]
    data["stations"][0]["dj_personality_file"] = "missing.md"  # not present in schedule_dir
    with pytest.raises(ConfigError):
        _load(tmp_path, data, resolver, fixed_clock)


# --- env vars (§12, A1) ---------------------------------------------------------


def test_missing_env_var_rejected(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock, monkeypatch
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="environment"):
        _load(tmp_path, _valid_config(content_tree, grid_yaml), resolver, fixed_clock)


def test_empty_env_var_rejected(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock, monkeypatch
):
    # A1: a present-but-empty secret (failed EnvironmentFile/SOPS) must fail fast.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    with pytest.raises(ConfigError, match="environment"):
        _load(tmp_path, _valid_config(content_tree, grid_yaml), resolver, fixed_clock)


def test_whitespace_env_var_rejected(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
    with pytest.raises(ConfigError, match="environment"):
        _load(tmp_path, _valid_config(content_tree, grid_yaml), resolver, fixed_clock)


def test_per_station_llm_override_env_checked(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    data = _valid_config(content_tree, grid_yaml)
    data["stations"][0]["llm"] = {
        "providers": [{"backend": "deepseek", "model": "x", "api_key_env": "DEEPSEEK_API_KEY"}]
    }
    with pytest.raises(ConfigError, match="environment"):
        _load(tmp_path, data, resolver, fixed_clock)


# --- uniqueness + R10 device resolution -----------------------------------------


def test_duplicate_station_names_rejected(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    data = _valid_config(content_tree, grid_yaml)
    dup = dict(data["stations"][0])
    dup["audio_device"] = "usb-port-2"  # distinct device, same name
    data["stations"].append(dup)
    with pytest.raises(ConfigError, match="duplicate station"):
        _load(tmp_path, data, resolver, fixed_clock)


def test_same_audio_device_rejected(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    data = _valid_config(content_tree, grid_yaml)
    dup = dict(data["stations"][0])
    dup["name"] = "Two"  # distinct name, same audio_device string usb-port-1
    data["stations"].append(dup)
    with pytest.raises(ConfigError, match="R10"):
        _load(tmp_path, data, resolver, fixed_clock)


def test_distinct_names_resolving_to_same_port_rejected(
    tmp_path, content_tree, grid_yaml, fixed_clock, monkeypatch
):
    # A2 (the deepest R10 finding): two DIFFERENT audio_device names that resolve to
    # the SAME physical port must be rejected — the real "Station 2 on Station 4's
    # transmitter" failure that a raw-string distinctness check cannot catch.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    aliasing = StaticAudioDeviceResolver({"usb-port-1": "phys-A", "usb-port-2": "phys-A"})
    data = _valid_config(content_tree, grid_yaml)  # station 1 uses usb-port-1
    dup = dict(data["stations"][0])
    dup["name"] = "Two"
    dup["audio_device"] = "usb-port-2"  # different string, same physical port phys-A
    data["stations"].append(dup)
    with pytest.raises(ConfigError, match="R10"):
        _load(tmp_path, data, aliasing, fixed_clock)


def test_two_stations_distinct_ports_accepted(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    data = _valid_config(content_tree, grid_yaml)
    dup = dict(data["stations"][0])
    dup["name"] = "Two"
    dup["audio_device"] = "usb-port-2"  # resolves to a distinct port phys-B
    data["stations"].append(dup)
    cfg = _load(tmp_path, data, resolver, fixed_clock)
    assert len(cfg.stations) == 2


def test_unresolvable_device_rejected(tmp_path, content_tree, grid_yaml, fixed_clock, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    bad_resolver = StaticAudioDeviceResolver({"usb-port-9": "phys-Z"})  # config asks usb-port-1
    with pytest.raises(ConfigError, match="R10"):
        _load(tmp_path, _valid_config(content_tree, grid_yaml), bad_resolver, fixed_clock)


# --- filesystem / grid / catalog cross-checks -----------------------------------


def test_missing_content_dir_rejected(tmp_path, grid_yaml, resolver, fixed_clock, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    data = _valid_config(tmp_path / "nope", grid_yaml)
    with pytest.raises(ConfigError):
        _load(tmp_path, data, resolver, fixed_clock)


def test_missing_schedule_dir_rejected(tmp_path, content_tree, resolver, fixed_clock, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    data = _valid_config(content_tree, tmp_path / "no_schedule")
    with pytest.raises(ConfigError):
        _load(tmp_path, data, resolver, fixed_clock)


def test_broken_grid_in_station_fails_loud(
    tmp_path, content_tree, resolver, fixed_clock, monkeypatch
):
    # A station whose grid doesn't tile must fail loudly at config load (a typed
    # PirateRadioError), not silently mis-air.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    sched = tmp_path / "stations" / "broken"
    sched.mkdir(parents=True)
    (sched / "default.yaml").write_text(
        'slots:\n  - {start: "00:00", end: "06:00", group: classical, name: "x"}\n',  # ends 06:00
        encoding="utf-8",
    )
    with pytest.raises(PirateRadioError):
        _load(tmp_path, _valid_config(content_tree, sched), resolver, fixed_clock)


# --- A3: tts_providers backend-key validation -----------------------------------


def test_unknown_tts_provider_backend_rejected(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock, monkeypatch
):
    # A3: a typo'd shared-credential backend key (e.g. "elevenlabss") must fail at
    # load, not silently — even though tts_providers has no Phase-0 reader.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    data = _valid_config(content_tree, grid_yaml)
    data["tts_providers"] = {"elevenlabss": {"api_key_env": "ELEVENLABS_API_KEY"}}
    with pytest.raises(ConfigError):
        _load(tmp_path, data, resolver, fixed_clock)


def test_known_tts_provider_backend_accepted(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    data = _valid_config(content_tree, grid_yaml)
    data["tts_providers"] = {"elevenlabs": {"api_key_env": "ELEVENLABS_API_KEY"}}
    cfg = _load(tmp_path, data, resolver, fixed_clock)
    assert "elevenlabs" in cfg.tts_providers


# --- file-level + shape hardening (Field Op, Senior Dev, Old Man) ----------------


def test_absent_config_file_rejected(tmp_path, resolver, fixed_clock) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.json", resolver=resolver, clock=fixed_clock)


def test_malformed_config_json_rejected(tmp_path, resolver, fixed_clock) -> None:
    p = tmp_path / "config.json"
    p.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(p, resolver=resolver, clock=fixed_clock)


def test_empty_stations_rejected(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock, monkeypatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    data = _valid_config(content_tree, grid_yaml)
    data["stations"] = []  # min_length=1
    with pytest.raises(ConfigError):
        _load(tmp_path, data, resolver, fixed_clock)


def test_persona_file_present_loads(
    tmp_path, content_tree, grid_yaml, resolver, fixed_clock, monkeypatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    (grid_yaml / "persona.md").write_text("a calm late-night host", encoding="utf-8")
    data = _valid_config(content_tree, grid_yaml)
    del data["stations"][0]["dj_personality"]
    data["stations"][0]["dj_personality_file"] = "persona.md"  # present in schedule_dir
    cfg = _load(tmp_path, data, resolver, fixed_clock)
    assert cfg.stations[0].dj_personality_file is not None
