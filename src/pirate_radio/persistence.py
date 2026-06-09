"""Atomic, durable, recoverable JSON persistence for Pydantic models.

Implements R5 (temp -> fsync -> os.replace -> fsync parent dir, with a ``.bak``
last-known-good), R6 (validate -> fall back to ``.bak`` -> raise
``StateCorruptionError`` so the caller regenerates; never crash-loop), and R17 (a
``schema_version`` envelope).

Generic over a single Pydantic model type; no domain knowledge lives here. Every
file on disk is ``{"schema_version": int, "payload": <model json>}``.

NOTE (amendment A7): this primitive is for low-frequency state (catalog cache,
daily schedules, resume state) — NOT for hot/per-item paths. Each write performs
multiple fsyncs; on a consumer SD card those are expensive. Durability requires a
filesystem with atomic rename + working directory fsync (ext4/f2fs), not
vfat/overlay-on-SD for the state directory.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from pirate_radio.durability import atomic_replace
from pirate_radio.errors import StateCorruptionError

M = TypeVar("M", bound=BaseModel)

_ENVELOPE_KEY_VERSION = "schema_version"
_ENVELOPE_KEY_PAYLOAD = "payload"


def atomic_write_json(path: Path, model: BaseModel, *, schema_version: int) -> None:
    """Durably write ``model`` to ``path`` inside a versioned envelope (R5, R17).

    Sequence: rotate any existing file to ``<path>.bak``, write a temp file in the
    same directory, fsync it, ``os.replace()`` it into place (atomic on POSIX), then
    fsync the parent directory so the rename itself survives a power loss.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    envelope = {
        _ENVELOPE_KEY_VERSION: schema_version,
        _ENVELOPE_KEY_PAYLOAD: model.model_dump(mode="json"),
    }
    data = json.dumps(envelope, indent=2, sort_keys=True).encode("utf-8")

    # Keep a last-known-good copy before we touch the live file.
    if path.exists():
        _replace_keep_bak(path)

    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        atomic_replace(tmp, path, strict=True)  # atomic rename + durable dir-fsync (R5; A7 strict)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def load_with_recovery(path: Path, model_type: type[M], *, schema_version: int) -> M:
    """Load and validate ``path``; on failure fall back to ``<path>.bak`` (R6).

    Raises ``StateCorruptionError`` (carrying ``path``) when neither the live file
    nor the ``.bak`` validate — the caller treats that as "regenerate from source",
    never as a reason to crash-loop.
    """
    path = Path(path)
    last_error: Exception | None = None
    for candidate in (path, path.with_suffix(path.suffix + ".bak")):
        if not candidate.exists():
            continue
        try:
            return _load_one(candidate, model_type, schema_version)
        except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_error = exc
            continue
    raise StateCorruptionError(f"no valid state at {path} or its .bak: {last_error}", path=path)


def _load_one(path: Path, model_type: type[M], schema_version: int) -> M:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or _ENVELOPE_KEY_PAYLOAD not in raw:
        raise ValueError(f"{path} is not a versioned persistence envelope")
    found = raw.get(_ENVELOPE_KEY_VERSION)
    if found != schema_version:
        # Phase 0: refuse unknown versions. Migration hooks arrive when a v2 exists.
        raise ValueError(f"{path} schema_version {found!r} != expected {schema_version}")
    return model_type.model_validate(raw[_ENVELOPE_KEY_PAYLOAD])


def _replace_keep_bak(path: Path) -> None:
    """Copy the current live file to ``<path>.bak`` before it is overwritten.

    Copy-then-replace (rather than rename-old-to-bak) means a crash mid-new-write
    leaves a valid ``.bak`` *and* the original live file intact until the atomic
    replace succeeds.
    """
    bak = path.with_suffix(path.suffix + ".bak")
    data = path.read_bytes()
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.bak.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        atomic_replace(tmp, bak, strict=True)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
