"""RED tests for ``pirate_radio.control.logs`` — Phase-6 P6-1 (the bounded log ring, R8' deviation).

A bounded in-memory ring (``deque(maxlen=N)``) capturing recent records — locked emit/snapshot (the
deque is appended by logging threads, read by the async handler), with ``scrub_secrets`` applied in
emit so a token never reaches ``/logs``. ``query_logs`` is a PURE filter (station/level/since/limit,
newest-first). Records are clock-stamped at capture via an INJECTED clock (no wall-time, R18/R21).
"""

from __future__ import annotations

import logging
import threading
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


def test_emit_swallows_a_malformed_record_and_ring_stays_usable() -> None:
    # cycle-3 isolation: emit() runs scrub + a pydantic LogEntry build in the CALLER's thread (the
    # sink-write executor, uvicorn). If that ever raises it must NOT escape into the logging caller:
    # it is routed through Handler.handleError instead, and the ring keeps working for good records.
    boom = {"n": 0}

    def _exploding_scrub(_msg: str) -> str:
        boom["n"] += 1
        if boom["n"] == 1:
            raise ValueError("scrub blew up on this record")
        return _msg

    h = RingLogHandler(maxsize=10, clock=_Clock(), scrub=_exploding_scrub)
    # the first record fails entry construction; emit MUST NOT raise out into the caller
    h.emit(_rec("pirate_radio.x", logging.ERROR, "first (will fail)"))
    assert h.snapshot() == []  # the bad record was dropped, not stored
    # the ring is still usable — a subsequent good record lands normally
    h.emit(_rec("pirate_radio.x", logging.INFO, "second (ok)"))
    assert [e.message for e in h.snapshot()] == ["second (ok)"]


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


# ---- thread-safety under concurrent emit/snapshot (P6-6 / QA C1) ---------------------------
class _TrackingLock:
    """A lock wrapper that counts acquisitions while delegating to a real lock — so a test can
    assert emit/snapshot actually take the lock (CPython's GIL makes a no-lock deque test pass
    regardless, so the smoke test below can't discriminate; THIS pins the mechanism)."""

    def __init__(self) -> None:
        self._real = threading.Lock()
        self.acquired = 0

    def __enter__(self) -> bool:
        self.acquired += 1
        return self._real.__enter__()

    def __exit__(self, *exc: object) -> None:
        self._real.__exit__(*exc)


def test_emit_and_snapshot_acquire_the_lock() -> None:
    # mutation-sensitive: remove either `with self._lock:` in logs.py and this fails. The lock is
    # the stated thread-safety mechanism (records appended by logging threads, read by the async
    # route); it must be genuinely taken — not merely relied on under the GIL (P6-6 / QA C1).
    h = RingLogHandler(maxsize=10, clock=_Clock())
    h._lock = _TrackingLock()  # type: ignore[assignment]
    h.emit(_rec("pirate_radio.x", logging.INFO, "one"))
    assert h._lock.acquired == 1  # type: ignore[attr-defined]  # emit took the lock
    h.snapshot()
    assert h._lock.acquired == 2  # type: ignore[attr-defined]  # snapshot took it too


def test_ring_is_thread_safe_under_concurrent_emit_and_snapshot() -> None:
    # the lock's whole reason for existing: records are appended by logging threads (sink executor,
    # uvicorn) WHILE the async /logs route reads. Hammer emit from N threads while the main thread
    # spins snapshot(); assert no torn read / exception and the bound holds (R8' deviation).
    h = RingLogHandler(maxsize=500, clock=_Clock())
    writers, per_writer = 8, 200
    errors: list[BaseException] = []
    stop = threading.Event()

    def _write(wid: int) -> None:
        try:
            for i in range(per_writer):
                h.emit(_rec("pirate_radio.x", logging.INFO, f"w{wid}-{i}"))
        except BaseException as exc:  # noqa: BLE001 - record any concurrency failure for the assert
            errors.append(exc)

    def _read() -> None:
        while not stop.is_set():
            snap = h.snapshot()  # must never raise mid-mutation, never exceed the bound
            assert len(snap) <= 500

    reader = threading.Thread(target=_read)
    reader.start()
    threads = [threading.Thread(target=_write, args=(w,)) for w in range(writers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stop.set()
    reader.join()

    assert errors == []  # no exception in any writer
    final = h.snapshot()
    assert len(final) == 500  # deque(maxlen) held the bound exactly under contention
