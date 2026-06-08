"""The daemon's logging setup (R8′, Phase-4 §H): one stdout handler for journald.

``configure_logging`` is called FIRST in ``__main__`` — before config load — so a config error is
itself logged through the operator stream. The format is journald-friendly (``levelname name:
message``; journald stamps the time + unit). Idempotent: a re-call (restart, a test) replaces the
prior pirate-radio handler instead of stacking a duplicate that would double every line.

The operator log *vocabulary* (station starting / on air / crashed / restart N/ceiling / backoff /
escalating / midnight regen done|FAILED / backstop fired) is emitted by the live components
(``station`` / ``supervisor`` / ``midnight`` / ``producer``), each station-tagged and asserted in
those modules' suites — this module owns only the handler/format/level wiring.
"""

from __future__ import annotations

import logging
import sys

_HANDLER_MARK = "_pirate_radio"  # tags our handler so re-calls replace (not stack) it
_FORMAT = "%(levelname)s %(name)s: %(message)s"  # journald adds the timestamp + unit


def _coerce_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    resolved = logging.getLevelName(level.upper())  # name -> int ("INFO" -> 20)
    if not isinstance(resolved, int):  # unknown name -> getLevelName returns "Level <x>"
        raise ValueError(f"unknown log level {level!r}")
    return resolved


def configure_logging(level: str | int = "INFO") -> None:
    """Install (or replace) the single pirate-radio stdout handler and set the root level."""
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, _HANDLER_MARK, False)]:
        root.removeHandler(handler)  # idempotent: drop our prior handler before re-adding
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT))
    setattr(handler, _HANDLER_MARK, True)
    root.addHandler(handler)
    root.setLevel(_coerce_level(level))
