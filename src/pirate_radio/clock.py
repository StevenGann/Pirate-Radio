"""Injectable clock (R18) using the system local timezone (D6).

Every time-dependent unit takes a ``Clock``; production wires ``SystemClock``,
tests wire ``FixedClock``. No module anywhere else may call ``datetime.now()``
directly — this is the single source of "now" in the codebase (enforced by review).

D6: the OS clock is trusted (no RTC/NTP-step defensive logic) and datetimes are
always timezone-aware so ``zoneinfo`` owns DST. ``tz()`` exists so Phase-1 code
(``find_now``, grid time -> datetime binding, midnight regen) can construct
datetimes in the same zone the clock reports.
"""

from __future__ import annotations

from datetime import datetime, tzinfo
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo


@runtime_checkable
class Clock(Protocol):
    """A source of the current tz-aware wall-clock time.

    Implementations MUST return timezone-aware datetimes (D6 keeps zoneinfo in
    charge of DST). Returning a naive datetime is a contract violation.
    """

    def now(self) -> datetime:
        """Return the current instant as a tz-aware datetime."""
        ...

    def tz(self) -> tzinfo:
        """Return the timezone this clock reports in."""
        ...


class SystemClock:
    """Clock backed by the OS clock and the system local timezone (D6).

    Trusts the OS clock; no RTC/NTP-step defensive logic (D6). The zone is resolved
    once at construction. Pass an explicit ``zone`` for reproducible tests or
    multi-tz deployments; otherwise the process local zone is used. A fixed-offset
    ``tzinfo`` (no IANA zone) is accepted — DST math degrades, which D6 tolerates.
    """

    def __init__(self, zone: tzinfo | None = None) -> None:
        self._tz: tzinfo = zone if zone is not None else _resolve_local_zone()

    def now(self) -> datetime:
        return datetime.now(tz=self._tz)

    def tz(self) -> tzinfo:
        return self._tz


class FixedClock:
    """Deterministic ``Clock`` for tests. Advances only when told.

    The provided instant MUST be tz-aware; a naive datetime raises ``ValueError`` so
    a test can never accidentally assert against a naive time.
    """

    def __init__(self, instant: datetime) -> None:
        if instant.tzinfo is None:
            raise ValueError("FixedClock requires a tz-aware datetime")
        self._instant = instant
        # tzinfo is non-None here (guard above); store it so tz() needs no runtime
        # assert that `-O` would strip (R10 amendment A10).
        self._tz: tzinfo = instant.tzinfo

    def now(self) -> datetime:
        return self._instant

    def tz(self) -> tzinfo:
        return self._tz

    def set(self, instant: datetime) -> FixedClock:
        """Return a new ``FixedClock`` at ``instant`` (immutable update)."""
        return FixedClock(instant)


def _resolve_local_zone() -> tzinfo:
    """Resolve the system local zone, falling back to UTC.

    ``datetime.now().astimezone()`` attaches the OS-configured local zone; we
    extract a concrete ``tzinfo`` from it so ``SystemClock.tz()`` is stable for the
    process.
    """
    local = datetime.now().astimezone().tzinfo
    if local is None:  # pragma: no cover - astimezone always attaches a zone
        return ZoneInfo("UTC")
    return local
