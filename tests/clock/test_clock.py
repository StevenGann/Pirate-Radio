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

import logging
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

import pytest

import pirate_radio.clock as clock_mod
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


# --- DST correctness of the DEFAULT SystemClock (bug-fix, Devil's Advocate HIGH) ---
# `datetime.now().astimezone().tzinfo` returns a FIXED-OFFSET snapshot, not a
# DST-aware zone; frozen at construction it drifts an hour across a DST transition.
# The default SystemClock must resolve a real IANA ZoneInfo (honoring PIRATE_RADIO_TZ).


def test_env_override_zone_is_dst_aware(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIRATE_RADIO_TZ", "America/New_York")
    z = SystemClock().tz()
    assert z == ZoneInfo("America/New_York")
    # A fixed-offset snapshot would give the SAME offset year-round; a DST zone must not.
    assert z.utcoffset(datetime(2026, 1, 1)) != z.utcoffset(datetime(2026, 7, 1))


def test_default_resolves_dst_aware_zoneinfo_not_fixed_offset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pirate_radio.clock import _system_zone_name

    monkeypatch.delenv("PIRATE_RADIO_TZ", raising=False)
    if _system_zone_name() is None:
        pytest.skip("no resolvable system IANA zone on this host")
    # The default path must yield a real ZoneInfo (DST-aware), never datetime.timezone.
    assert isinstance(SystemClock().tz(), ZoneInfo)


def test_bad_env_override_falls_back_without_raising(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("PIRATE_RADIO_TZ", "Definitely/NotAZone")
    with caplog.at_level(logging.WARNING, logger="pirate_radio.clock"):
        clk = SystemClock()  # must degrade, not crash
    assert clk.now().tzinfo is not None
    # The bad value must be named in a WARNING so a misconfig is diagnosable, not silent.
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert "Definitely/NotAZone" in caplog.text


def test_unresolvable_system_zone_degrades_to_fixed_offset_with_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # No env override, and no resolvable IANA name (headless Pi). The clock must
    # still produce a tz-aware now() and WARN that DST math is degraded.
    monkeypatch.delenv("PIRATE_RADIO_TZ", raising=False)
    monkeypatch.setattr(clock_mod, "_system_zone_name", lambda: None)
    with caplog.at_level(logging.WARNING, logger="pirate_radio.clock"):
        clk = SystemClock()
    assert clk.now().tzinfo is not None
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    # The WARNING must name the env override as the remedy (diagnosable, not generic).
    assert "PIRATE_RADIO_TZ" in caplog.text


def test_unloadable_system_name_degrades_to_fixed_offset_with_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Third fallback tier: the system resolves a NAME but ZoneInfo() can't load it
    # (e.g. /etc/timezone names a zone whose tzdata package is absent). Must degrade
    # to a fixed offset — not crash — and WARN naming the offending value. Without
    # this test a regression that dropped clock.py's try/except would pass silently.
    monkeypatch.delenv("PIRATE_RADIO_TZ", raising=False)
    monkeypatch.setattr(clock_mod, "_system_zone_name", lambda: "Fake/Zone")
    with caplog.at_level(logging.WARNING, logger="pirate_radio.clock"):
        clk = SystemClock()
    assert clk.now().tzinfo is not None
    assert "Fake/Zone" in caplog.text
    # The WARNING must also point the operator at the remedy, not just name the value.
    assert "PIRATE_RADIO_TZ" in caplog.text


def test_default_uses_resolved_system_name(monkeypatch: pytest.MonkeyPatch) -> None:
    # The production default path must build its zone from the resolved IANA name.
    from pirate_radio.clock import _system_zone_name

    monkeypatch.delenv("PIRATE_RADIO_TZ", raising=False)
    name = _system_zone_name()
    if name is None:
        pytest.skip("no resolvable system IANA zone on this host")
    assert SystemClock().tz() == ZoneInfo(name)


# --- _system_zone_name parsing (the /etc seam, exercised via module constants) ---


def test_system_zone_name_reads_etc_timezone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    from pathlib import Path

    from pirate_radio.clock import _system_zone_name

    tzfile = Path(str(tmp_path)) / "timezone"
    tzfile.write_text("America/New_York\n", encoding="utf-8")
    monkeypatch.setattr(clock_mod, "_ETC_TIMEZONE", tzfile)
    assert _system_zone_name() == "America/New_York"


def test_system_zone_name_reads_localtime_symlink(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    from pathlib import Path

    from pirate_radio.clock import _system_zone_name

    base = Path(str(tmp_path))
    # /etc/timezone absent → fall through to the /etc/localtime symlink.
    monkeypatch.setattr(clock_mod, "_ETC_TIMEZONE", base / "no-timezone")
    zinfo = base / "usr" / "share" / "zoneinfo" / "America"
    zinfo.mkdir(parents=True)
    target = zinfo / "New_York"
    target.write_text("TZif", encoding="utf-8")  # content irrelevant to name parsing
    link = base / "localtime"
    link.symlink_to(target)
    monkeypatch.setattr(clock_mod, "_ETC_LOCALTIME", link)
    assert _system_zone_name() == "America/New_York"


def test_system_zone_name_returns_none_when_unresolvable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    from pathlib import Path

    from pirate_radio.clock import _system_zone_name

    base = Path(str(tmp_path))
    monkeypatch.setattr(clock_mod, "_ETC_TIMEZONE", base / "no-timezone")
    monkeypatch.setattr(clock_mod, "_ETC_LOCALTIME", base / "no-localtime")
    assert _system_zone_name() is None
