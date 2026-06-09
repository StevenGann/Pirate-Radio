"""Resolve + preflight the externals Phase 2 spawns (ffmpeg + espeak binaries; piper as a module).

Fail FAST AT BOOT (§12 spirit) — but in a SEPARATE function the daemon entrypoint calls
(via ``load_config(preflight=True)``), NOT inside ``_validate_config`` (H20): the config
test suite validates piper-station configs WITHOUT the real externals, so these checks must stay
out of the shape/filesystem validation path. ffmpeg/espeak resolve to an explicit configured path
(must exist + be executable) else the first found PATH candidate. **piper** is the piper1-gpl fork
run as ``python -m piper`` (no console script): preflight verifies the ``piper`` module imports
under the configured interpreter (default the daemon's own ``sys.executable``). Every
``ConfigError`` names the operator-facing remedy (H13/H19).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from pirate_radio.config import DaemonConfig, EspeakProviderConfig, PiperProviderConfig
from pirate_radio.errors import ConfigError

logger = logging.getLogger(__name__)

# rhasspy/piper is ARCHIVED; the maintained fork is OHF-Voice/piper1-gpl (`pip install piper-tts`).
_PIPER_TTS_URL = "https://github.com/OHF-Voice/piper1-gpl"
_PIPER_REMEDY = (
    f"`pip install piper-tts` into the daemon venv (maintained fork {_PIPER_TTS_URL}; "
    "rhasspy/piper is archived)."
)


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


def _preflight_piper_module(python: str) -> None:
    """Verify the piper1-gpl module is importable by ``python`` (it runs as ``python -m piper``).

    A subprocess `import piper` is the boot-time equivalent of the ffmpeg/espeak binary check —
    fail loud now, not at 3am. (Kept out of ``_validate_config`` per H20; the config tests stub it.)
    """
    try:
        proc = subprocess.run(
            [python, "-c", "import piper"], capture_output=True, timeout=30, check=False
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise ConfigError(f"piper: cannot run {python!r} ({exc}). {_PIPER_REMEDY}") from exc
    if proc.returncode != 0:
        raise ConfigError(f"piper: `piper-tts` is not importable by {python!r}. {_PIPER_REMEDY}")


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
        python = str(prov.python) if prov.python else sys.executable
        _preflight_piper_module(python)
        for s in config.stations:
            for tts in s.tts:
                if tts.backend == "piper":
                    onnx = prov.voices_dir / f"{tts.voice}.onnx"
                    # piper loads BOTH the .onnx AND its companion .onnx.json (auto-discovered next
                    # to the model). Check both at boot: a missing .json otherwise surfaces only at
                    # the first synth as a non-fatal-looking error that failover keeps retrying
                    # (panel DA) — fail loud now, not at 3am.
                    for needed in (onnx, onnx.with_suffix(".onnx.json")):
                        if not needed.is_file():
                            raise ConfigError(
                                f"station '{s.name}': piper voice file not found: {needed}. "
                                f"Fetch it (`python -m piper.download_voices {tts.voice}`) so "
                                f"both {tts.voice}.onnx and {tts.voice}.onnx.json are in "
                                f"{prov.voices_dir} (keep voices_dir on FAST storage — H15)."
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
