"""Resolve + preflight the system binaries Phase 2 spawns (ffmpeg, piper, espeak).

Fail FAST AT BOOT (§12 spirit) — but in a SEPARATE function the daemon entrypoint calls
(via ``load_config(preflight=True)``), NOT inside ``_validate_config`` (H20): the config
test suite validates piper-station configs WITHOUT real binaries, so binary checks must stay
out of the shape/filesystem validation path. Resolution: an explicit configured path (must
exist + be executable) else the first found PATH candidate — piper has NO PATH fallback
(H16: Debian's ``piper`` package is an unrelated mouse-button tool). Every ``ConfigError``
names the operator-facing remedy (H13/H19).
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from pirate_radio.config import DaemonConfig, EspeakProviderConfig, PiperProviderConfig
from pirate_radio.errors import ConfigError

logger = logging.getLogger(__name__)

_PIPER_TTS_URL = "https://github.com/rhasspy/piper/releases"


def resolve_binary(explicit: Path | None, *candidates: str, remedy: str) -> Path:
    """An explicit path (must exist + be executable), else the first found PATH candidate.

    ``remedy`` is appended to every ``ConfigError`` so the operator knows the fix.
    """
    if explicit is not None:
        if not explicit.is_file():
            raise ConfigError(f"configured binary not found: {explicit}. {remedy}")
        if not os.access(explicit, os.X_OK):
            raise ConfigError(f"configured binary not executable: {explicit}. {remedy}")
        return explicit
    for name in candidates:
        found = shutil.which(name)
        if found:
            return Path(found)
    raise ConfigError(f"required binary not found on PATH (tried {list(candidates)}). {remedy}")


def preflight_binaries(config: DaemonConfig) -> None:
    """Boot-time check: every binary a configured station actually USES is present.

    Called by the daemon boot path (``load_config(preflight=True)``) — NEVER from
    ``_validate_config`` (H20).
    """
    resolve_binary(
        config.ffmpeg_binary,
        "ffmpeg",
        remedy="Install ffmpeg (e.g. `apt install ffmpeg`) or set ffmpeg_binary in config.json.",
    )
    backends_in_use = {tts.backend for s in config.stations for tts in s.tts}

    if "piper" in backends_in_use:
        prov = config.provider("piper")
        if not isinstance(prov, PiperProviderConfig):  # pragma: no cover - mypy narrowing guard
            raise ConfigError("internal: expected a PiperProviderConfig for 'piper'")
        if prov.binary is None:  # H16: no PATH fallback
            raise ConfigError(
                "piper is configured but tts_providers.piper.binary is unset. Debian's `piper`"
                " package is an unrelated mouse-button tool; download piper-TTS from "
                f"{_PIPER_TTS_URL} and set tts_providers.piper.binary to its path."
            )
        resolve_binary(prov.binary, remedy=f"Download piper-TTS from {_PIPER_TTS_URL}.")
        for s in config.stations:
            for tts in s.tts:
                if tts.backend == "piper":
                    onnx = prov.voices_dir / f"{tts.voice}.onnx"
                    if not onnx.is_file():
                        raise ConfigError(
                            f"station '{s.name}': piper voice model not found: {onnx}. Download "
                            f"the voice and place {tts.voice}.onnx in {prov.voices_dir} "
                            "(keep voices_dir on FAST storage, not the boot SD — H15)."
                        )

    if "espeak" in backends_in_use:
        prov = config.provider("espeak")
        if not isinstance(prov, EspeakProviderConfig):  # pragma: no cover - mypy narrowing guard
            raise ConfigError("internal: expected an EspeakProviderConfig for 'espeak'")
        resolve_binary(
            prov.binary,
            "espeak-ng",
            "espeak",
            remedy="Install espeak-ng (e.g. `apt install espeak-ng`).",
        )

    logger.info("binary preflight ok: %s", sorted(backends_in_use | {"ffmpeg"}))
