"""The bounded log ring for ``GET /logs`` (Phase 6, P6-1) — the **documented R8′ deviation**.

Design R8′ says ``/logs`` should be journald/SQLite-backed; we deliberately use a **bounded
in-memory ring** (``deque(maxlen=N)``) instead: it never reads the SD card (H26) and is R23-safe (no
disk I/O in the handler). Residual (runbook): **lossy across restarts and shallow** (last N) — the
operator falls back to ``journalctl`` for deep history. To be ratified by the P6-6 deep-dive.

``RingLogHandler`` is a ``logging.Handler`` whose ``emit``/``snapshot`` are LOCKED (records are
appended by logging threads — the sink executor, uvicorn — and read by the async ``/logs`` route),
and which runs ``scrub_secrets`` on every message before storing it (H22 — a token can never reach
``/logs``). Records are clock-stamped at capture via an INJECTED clock (R18/R21). ``query_logs`` is
a PURE filter (station substring / minimum level / since / limit, newest-first).
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from pirate_radio.supervisor import scrub_secrets

_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


class LogEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    timestamp: datetime
    level: str
    logger: str
    message: str


class RingLogHandler(logging.Handler):
    """A bounded, thread-safe, secret-scrubbing ring of recent log records (R8′ deviation)."""

    def __init__(
        self,
        maxsize: int,
        *,
        clock: Callable[[], datetime] | None = None,
        scrub: Callable[[str], str] = scrub_secrets,
    ) -> None:
        super().__init__()
        self._entries: deque[LogEntry] = deque(maxlen=maxsize)
        self._clock = clock
        self._scrub = scrub
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        when = self._clock() if self._clock else datetime.fromtimestamp(record.created, tz=UTC)
        entry = LogEntry(
            timestamp=when,
            level=record.levelname,
            logger=record.name,
            message=self._scrub(record.getMessage()),  # H22: scrub BEFORE storage
        )
        with self._lock:
            self._entries.append(entry)

    def snapshot(self) -> list[LogEntry]:
        """A locked point-in-time copy so ``query_logs`` never iterates a mutating deque."""
        with self._lock:
            return list(self._entries)


def query_logs(
    entries: list[LogEntry],
    *,
    station: str | None = None,
    level: str | None = None,
    since: datetime | None = None,
    limit: int | None = None,
) -> list[LogEntry]:
    """PURE: filter a snapshot by station / minimum level / ``since``, newest-first, then cap at
    ``limit``. ``station`` is a **message substring** match, NOT a structured field — records carry
    no station tag, so ``station="Pi0"`` matches any record whose text contains ``Pi0`` (documented
    as a convenience in the runbook; ``journalctl | grep`` is the precise tool). An unknown
    ``level`` name is treated as no floor (matches all)."""
    floor = _LEVELS.get(level.upper(), 0) if level else 0
    out = [
        e
        for e in entries
        if (station is None or station in e.message)
        and _LEVELS.get(e.level, 0) >= floor
        and (since is None or e.timestamp >= since)
    ]
    out.reverse()  # newest-first (entries are appended oldest→newest)
    return out[:limit] if limit is not None else out
