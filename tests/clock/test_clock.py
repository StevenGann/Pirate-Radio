"""RED tests for ``pirate_radio.clock`` — authored from Phase 0 plan §4.2 / §6.2.

Tests first (strict spec-driven TDD): the injectable ``Clock`` seam (R18) and the
tz-aware / system-local-time behavior (D6) are specified here *before* clock.py
exists. Uses real clocks (no mocks), per the plan.

Hardening folded in from the panel's tests-first review (adopted 7-0):
  - tz() must return a real tzinfo, not just be present (Devil's Advocate).
  - now()/tz() must AGREE on the default (production) path (Devil's Advocate, RPi).
  - an injected DST zone is exercised, not only UTC (QA Engineer).
  - a fixed-offset (no-IANA) zone still works — the headless-Pi case (RPi Expert).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

import pytest

from pirate_radio.clock import Clock, FixedClock, SystemClock


def test_clock_is_runtime_checkable_protocol() -> None:
    # Both concrete clocks must satisfy the runtime-checkable Clock protocol.
    # (Presence-only; behavioral guarantees are pinned by the tests below.)
    assert isinstance(SystemClock(), Clock)
    assert isinstance(FixedClock(datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC"))), Clock)


def test_systemclock_now_is_tz_aware() -> None:
    # D6: clocks must return tz-aware datetimes so zoneinfo owns DST.
    assert SystemClock().now().tzinfo is not None


def test_systemclock_tz_returns_a_real_tzinfo() -> None:
    # Protocol isinstance only checks presence; pin that tz() returns a tzinfo.
    assert isinstance(SystemClock().tz(), tzinfo)


def test_systemclock_now_zone_agrees_with_tz_on_default_path() -> None:
    # The production (no-injected-zone) path: now() must be reported in the SAME
    # zone tz() advertises — Phase-1 datetime construction depends on this.
    clk = SystemClock()
    assert clk.now().utcoffset() == datetime.now(clk.tz()).utcoffset()


def test_systemclock_honours_injected_zone() -> None:
    clk = SystemClock(zone=ZoneInfo("UTC"))
    assert clk.tz() == ZoneInfo("UTC")
    assert clk.now().utcoffset() == timedelta(0)


def test_systemclock_honours_injected_dst_zone() -> None:
    # Exercise a real DST zone (not just UTC): now() agrees with the zone and is
    # never UTC-offset-zero for New York.
    ny = ZoneInfo("America/New_York")
    clk = SystemClock(zone=ny)
    assert clk.tz() == ny
    assert clk.now().utcoffset() == datetime.now(ny).utcoffset()
    assert clk.now().utcoffset() != timedelta(0)


def test_systemclock_accepts_fixed_offset_zone() -> None:
    # Headless-Pi / no-IANA-zone case (D6): a fixed-offset tzinfo still yields a
    # tz-aware now() and a queryable tz(); DST math degrades, which D6 tolerates.
    offset = timezone(timedelta(hours=5))
    clk = SystemClock(zone=offset)
    assert clk.tz() is offset
    assert clk.now().tzinfo is not None
    assert clk.now().utcoffset() == timedelta(hours=5)


def test_fixedclock_rejects_naive() -> None:
    # A naive datetime must never enter a test via the clock seam.
    with pytest.raises(ValueError):
        FixedClock(datetime(2026, 1, 1))  # naive


def test_fixedclock_is_deterministic() -> None:
    t = datetime(2026, 6, 10, 9, 30, tzinfo=ZoneInfo("UTC"))
    clk = FixedClock(t)
    assert clk.now() == t
    assert clk.now() == clk.now()


def test_fixedclock_tz_matches_instant() -> None:
    t = datetime(2026, 6, 10, 9, 30, tzinfo=ZoneInfo("America/New_York"))
    clk = FixedClock(t)
    assert isinstance(clk.tz(), tzinfo)
    assert clk.tz() == ZoneInfo("America/New_York")


def test_fixedclock_set_returns_new_instance_without_mutating() -> None:
    # set() is an immutable update: returns a new clock, leaves the original alone.
    t = datetime(2026, 6, 10, 9, 30, tzinfo=ZoneInfo("UTC"))
    clk = FixedClock(t)
    later = clk.set(t + timedelta(hours=1))
    assert later.now() == t + timedelta(hours=1)
    assert clk.now() == t
    assert later is not clk
