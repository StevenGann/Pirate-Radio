"""Gate for ``systemd/pirate-radio.service`` — Phase-4 plan §H / P4-8 (R7 tier-1, C2, H22, H24).

The unit is the OS-level supervision tier. These assertions pin the directives the design requires
(and the one it forbids — no WatchdogSec footgun), so an accidental edit that drops restart-limiting
or the network/time-sync ordering is caught in CI, not at 3am on the Pi.
"""

from __future__ import annotations

import configparser
from pathlib import Path

_UNIT = Path(__file__).resolve().parents[1] / "systemd" / "pirate-radio.service"


def _unit() -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.optionxform = str  # preserve case (systemd keys are CamelCase)
    parser.read(_UNIT)
    return parser


def test_unit_file_exists() -> None:
    assert _UNIT.is_file()


def test_service_is_type_simple_and_restarts_on_failure() -> None:
    svc = _unit()["Service"]
    assert svc["Type"] == "simple"
    assert svc["Restart"] == "on-failure"
    assert int(svc["RestartSec"]) >= 1


def test_start_limit_bounds_the_crash_loop() -> None:
    # C2: terminal `failed` instead of an infinite fast restart thrash
    svc = _unit()["Service"]
    assert int(svc["StartLimitIntervalSec"]) > 0
    assert int(svc["StartLimitBurst"]) > 0


def test_orders_after_network_online_and_time_sync() -> None:
    after = _unit()["Unit"]["After"]
    assert "network-online.target" in after  # LAN LLM/TTS reachable (H22)
    assert "time-sync.target" in after  # corrected clock before the wall-clock schedule (H24)
    assert "network-online.target" in _unit()["Unit"]["Wants"]


def test_secrets_come_from_an_environment_file_not_the_unit() -> None:
    svc = _unit()["Service"]
    assert svc["EnvironmentFile"].endswith("secrets.env")  # H22: root-owned 0600, never in the unit
    # the unit must not inline any secret-looking Environment= value
    assert "Environment" not in svc or "key" not in svc.get("Environment", "").lower()


def test_no_watchdog_in_v1() -> None:
    # a WatchdogSec without a real sd_notify heartbeat is a footgun (documented optional upgrade)
    assert "WatchdogSec" not in _unit()["Service"]
