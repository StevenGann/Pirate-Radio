"""RED tests for ``pirate_radio.control.logs`` — Phase-6 P6-1 (the bounded log ring, R8' deviation).

A bounded in-memory ring (``deque(maxlen=N)``) capturing recent records — locked emit/snapshot (the
deque is appended by logging threads, read by the async handler), with ``scrub_secrets`` applied in
emit so a token never reaches ``/logs``. ``query_logs`` is a PURE filter (station/level/since/limit,
newest-first). Records are clock-stamped at capture via an INJECTED clock (no wall-time, R18/R21).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from pirate_radio.control.logs import LogEntry, RingLogHandler, query_logs


class _Clock:
    def __init__(self) -> None:
        self.t = datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.t


def _rec(name: str, level: int, msg: str) -> logging.LogRecord:
    return logging.LogRecord(name, level, __file__, 1, msg, None, None)


def test_ring_is_bounded_oldest_dropped() -> None:
    h = RingLogHandler(maxsize=3, clock=_Clock())
    for i in range(5):
        h.emit(_rec("pirate_radio.x", logging.INFO, f"msg{i}"))
    msgs = [e.message for e in h.snapshot()]
    assert msgs == ["msg2", "msg3", "msg4"]  # only the last 3 retained


def test_emit_scrubs_secrets() -> None:
    h = RingLogHandler(maxsize=10, clock=_Clock())
    h.emit(_rec("pirate_radio.x", logging.WARNING, "auth Bearer sk-LEAKED123 failed"))
    assert "sk-LEAKED123" not in h.snapshot()[0].message  # H22: scrubbed before storage


def test_emit_stamps_with_the_injected_clock() -> None:
    clock = _Clock()
    h = RingLogHandler(maxsize=10, clock=clock)
    h.emit(_rec("pirate_radio.x", logging.INFO, "hi"))
    assert h.snapshot()[0].timestamp == clock.t  # not wall-time


def _entries() -> list[LogEntry]:
    base = datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC)
    return [
        LogEntry(timestamp=base, level="INFO", logger="a", message="station Pi0 on air"),
        LogEntry(timestamp=base, level="WARNING", logger="b", message="station Pi1 backstop fired"),
        LogEntry(timestamp=base, level="CRITICAL", logger="c", message="station Pi0 crashed"),
    ]


def test_query_filters_by_station_substring() -> None:
    out = query_logs(_entries(), station="Pi0")
    assert {e.message for e in out} == {"station Pi0 on air", "station Pi0 crashed"}


def test_query_filters_by_minimum_level() -> None:
    out = query_logs(_entries(), level="WARNING")
    assert all(e.level in ("WARNING", "CRITICAL") for e in out) and len(out) == 2


def test_query_filters_by_since() -> None:
    base = datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC)
    older = LogEntry(
        timestamp=datetime(2026, 6, 10, 11, 0, tzinfo=UTC), level="INFO", logger="x", message="old"
    )
    out = query_logs([older, *_entries()], since=base)
    assert "old" not in {e.message for e in out}  # before `since` excluded


def test_query_newest_first_and_limited() -> None:
    base = datetime(2026, 6, 10, 12, 0, 0, tzinfo=UTC)
    entries = [
        LogEntry(timestamp=base.replace(second=s), level="INFO", logger="x", message=f"m{s}")
        for s in range(5)
    ]
    out = query_logs(entries, limit=2)
    assert [e.message for e in out] == ["m4", "m3"]  # newest first, capped
