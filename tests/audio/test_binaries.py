"""RED tests for ``pirate_radio.audio.binaries`` — Phase 2 plan §4.5 (H15/H16/H20).

Tests first. ``resolve_binary`` + ``preflight_binaries`` fail FAST AT BOOT when a binary a
configured station actually uses is missing — but in a SEPARATE function the daemon
entrypoint calls, NOT inside ``_validate_config`` (H20: the config test suite validates
piper-station configs without real binaries). Pinned:
  - explicit path: must exist AND be executable; errors NAME the remedy (H13/H19);
  - PATH lookup for ffmpeg/espeak; piper has NO PATH fallback (H16: Debian `piper` is a
    mouse tool) — an unset piper binary is a ConfigError pointing at the piper-TTS release;
  - per-station ``voices_dir/{voice}.onnx`` existence;
  - espeak with no ``tts_providers.espeak`` block defaults to a PATH lookup, never KeyError (H15).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pirate_radio.audio.binaries import preflight_binaries, resolve_binary
from pirate_radio.config import DaemonConfig
from pirate_radio.errors import ConfigError


def _config(
    *, stations_tts: list[dict], tts_providers: dict, ffmpeg_binary: str | None = None
) -> DaemonConfig:
    raw: dict = {
        "llm": {"providers": [{"backend": "claude", "model": "x", "api_key_env": "K"}]},
        "tts_providers": tts_providers,
        "state_dir": "/state",
        "stations": [
            {
                "name": "S1",
                "schedule_dir": "/s",
                "content_dir": "/c",
                "audio_device": "hw:0",
                "dj_personality": "calm",
                "tts": stations_tts,
            }
        ],
    }
    if ffmpeg_binary is not None:
        raw["ffmpeg_binary"] = ffmpeg_binary
    return DaemonConfig.model_validate(raw)


def _all_present(monkeypatch) -> None:
    # Pretend ffmpeg / espeak-ng / espeak are all on PATH.
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")


# --- resolve_binary -------------------------------------------------------------


def test_resolve_explicit_executable_path(tmp_path: Path) -> None:
    f = tmp_path / "ffmpeg"
    f.write_text("#!/bin/sh\n")
    f.chmod(0o755)
    assert resolve_binary(f, "ffmpeg", remedy="x") == f


def test_resolve_explicit_missing_raises_with_remedy(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="install ffmpeg"):
        resolve_binary(tmp_path / "nope", "ffmpeg", remedy="Please install ffmpeg")


def test_resolve_explicit_non_executable_raises(tmp_path: Path) -> None:
    if __import__("os").geteuid() == 0:
        pytest.skip("root bypasses the execute bit")
    f = tmp_path / "ffmpeg"
    f.write_text("not exec")
    f.chmod(0o644)
    with pytest.raises(ConfigError, match="not executable"):
        resolve_binary(f, "ffmpeg", remedy="x")


def test_resolve_path_lookup_found(monkeypatch) -> None:
    monkeypatch.setattr(
        shutil, "which", lambda name: "/usr/bin/espeak-ng" if name == "espeak-ng" else None
    )
    assert resolve_binary(None, "espeak-ng", "espeak", remedy="x") == Path("/usr/bin/espeak-ng")


def test_resolve_path_lookup_missing_raises_with_remedy(monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(ConfigError, match="apt install espeak-ng"):
        resolve_binary(None, "espeak-ng", "espeak", remedy="apt install espeak-ng")


# --- preflight_binaries ---------------------------------------------------------


def test_preflight_ok_for_espeak_station(monkeypatch) -> None:
    _all_present(monkeypatch)
    cfg = _config(stations_tts=[{"backend": "espeak", "voice": "en"}], tts_providers={})
    preflight_binaries(cfg)  # must not raise (espeak defaults to PATH lookup, H15)


def test_preflight_piper_without_binary_is_fatal_with_mouse_warning(monkeypatch) -> None:
    _all_present(monkeypatch)
    cfg = _config(
        stations_tts=[{"backend": "piper", "voice": "en_US-ryan-high"}],
        tts_providers={"piper": {"voices_dir": "/opt/voices"}},  # binary unset
    )
    # match="mouse" pins the H16 operator-actionable warning, not just any piper-mentioning error.
    with pytest.raises(ConfigError, match="mouse"):
        preflight_binaries(cfg)


def test_preflight_piper_missing_voice_model_is_fatal(monkeypatch, tmp_path: Path) -> None:
    _all_present(monkeypatch)
    piper = tmp_path / "piper"
    piper.write_text("#!/bin/sh\n")
    piper.chmod(0o755)
    voices = tmp_path / "voices"
    voices.mkdir()  # exists but the {voice}.onnx is absent
    cfg = _config(
        stations_tts=[{"backend": "piper", "voice": "en_US-ryan-high"}],
        tts_providers={"piper": {"binary": str(piper), "voices_dir": str(voices)}},
    )
    with pytest.raises(ConfigError, match="voice model not found"):
        preflight_binaries(cfg)


def test_preflight_piper_all_present_ok_and_logs(monkeypatch, tmp_path: Path, caplog) -> None:
    import logging

    _all_present(monkeypatch)
    piper = tmp_path / "piper"
    piper.write_text("#!/bin/sh\n")
    piper.chmod(0o755)
    voices = tmp_path / "voices"
    voices.mkdir()
    (voices / "en_US-ryan-high.onnx").write_bytes(b"onnx")
    cfg = _config(
        stations_tts=[{"backend": "piper", "voice": "en_US-ryan-high"}],
        tts_providers={"piper": {"binary": str(piper), "voices_dir": str(voices)}},
    )
    with caplog.at_level(logging.INFO, logger="pirate_radio.audio.binaries"):
        preflight_binaries(cfg)  # must not raise
    assert "preflight ok" in caplog.text  # operator's boot confirmation


def test_preflight_missing_ffmpeg_names_install_remedy(monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)  # nothing on PATH
    cfg = _config(stations_tts=[{"backend": "espeak", "voice": "en"}], tts_providers={})
    # match the PRODUCTION remedy (not an echoed test string) — pins the operator-facing fix.
    with pytest.raises(ConfigError, match="apt install ffmpeg"):
        preflight_binaries(cfg)


def test_preflight_explicit_ffmpeg_binary_missing_is_fatal(monkeypatch, tmp_path: Path) -> None:
    # The explicit ffmpeg_binary path branch (not PATH lookup) must also be checked.
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    cfg = _config(
        stations_tts=[{"backend": "espeak", "voice": "en"}],
        tts_providers={},
        ffmpeg_binary=str(tmp_path / "nope_ffmpeg"),
    )
    with pytest.raises(ConfigError, match="ffmpeg"):
        preflight_binaries(cfg)


def test_preflight_missing_espeak_names_install_remedy(monkeypatch) -> None:
    # ffmpeg present, espeak absent -> the espeak remedy is surfaced.
    monkeypatch.setattr(
        shutil, "which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None
    )
    cfg = _config(stations_tts=[{"backend": "espeak", "voice": "en"}], tts_providers={})
    with pytest.raises(ConfigError, match="apt install espeak-ng"):
        preflight_binaries(cfg)
