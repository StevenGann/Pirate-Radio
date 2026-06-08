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

import logging
import os
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

#: Operator override for the broadcast zone (Q5). An IANA name, e.g. "America/New_York".
_TZ_ENV = "PIRATE_RADIO_TZ"
#: System zone sources, read in order. Module constants so tests can redirect the seam.
_ETC_TIMEZONE = Path("/etc/timezone")
_ETC_LOCALTIME = Path("/etc/localtime")
#: Marker dividing the zoneinfo database root from the IANA name in a localtime symlink.
_ZONEINFO_MARKER = "zoneinfo/"


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


def _system_zone_name() -> str | None:
    """Resolve the system's IANA zone *name* (e.g. ``"America/New_York"``), or None.

    Reads ``/etc/timezone`` first (Debian/Raspberry Pi OS write the plain name
    there); otherwise inspects the ``/etc/localtime`` symlink and extracts the name
    after the ``zoneinfo/`` segment of its target. Returns ``None`` when neither
    yields a usable name — the caller then degrades to a fixed offset.
    """
    try:
        if _ETC_TIMEZONE.is_file():
            name = _ETC_TIMEZONE.read_text(encoding="utf-8").strip()
            if name:
                return name
    except OSError:  # pragma: no cover - unreadable /etc/timezone is rare
        pass
    try:
        if _ETC_LOCALTIME.is_symlink():
            target = str(_ETC_LOCALTIME.resolve())
            if _ZONEINFO_MARKER in target:
                return target.split(_ZONEINFO_MARKER, 1)[1]
    except OSError:  # pragma: no cover - broken symlink / unreadable
        pass
    return None


def _resolve_local_zone() -> tzinfo:
    """Resolve a DST-aware local zone (R9/D6), honoring the ``PIRATE_RADIO_TZ`` override.

    Order: the ``PIRATE_RADIO_TZ`` env override (Q5), then the system IANA zone name
    (``/etc/timezone`` / ``/etc/localtime``) loaded as a ``ZoneInfo`` so ``zoneinfo``
    owns DST. A fixed-offset ``tzinfo`` is only a last resort (logged) — captured
    once, it cannot follow DST, so the warning makes that degradation visible rather
    than letting a long-lived clock silently drift an hour across a transition.
    """
    env = os.environ.get(_TZ_ENV)
    if env:
        try:
            return ZoneInfo(env)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            logger.warning(
                "%s=%r is not a loadable IANA zone; ignoring it and resolving the "
                "system zone instead.",
                _TZ_ENV,
                env,
            )

    name = _system_zone_name()
    if name is not None:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            logger.warning(
                "System zone name %r could not be loaded as a ZoneInfo; falling back "
                "to a fixed offset.",
                name,
            )

    fixed = datetime.now().astimezone().tzinfo
    logger.warning(
        "No IANA timezone could be resolved; using fixed offset %s. DST transitions "
        "will NOT be tracked — set %s to an IANA zone name to fix this.",
        fixed,
        _TZ_ENV,
    )
    if fixed is None:  # pragma: no cover - astimezone always attaches a zone
        return UTC
    return fixed
