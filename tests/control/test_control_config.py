"""Tests for ``ControlConfig`` — Phase-6 P6-5 safety defaults (P6-6 / QA M1).

The control plane's safe-by-default posture rides entirely on these defaults: the API is OFF unless
a ``control`` block is present (``DaemonConfig.control is None``), and when present it binds
**loopback only** and never ``0.0.0.0`` by accident. The port range and the bounded log-ring size
are validated at the model boundary (fail-fast), so a bad value is a boot error, not a surprise.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pirate_radio.config import ControlConfig, DaemonConfig


def test_defaults_are_safe_loopback_and_enabled() -> None:
    c = ControlConfig()
    assert c.enabled is True
    assert c.host == "127.0.0.1"  # never 0.0.0.0 by default — loopback only (Field-Op guarantee)
    assert c.port == 8080
    assert c.token_env == "PIRATE_API_TOKEN"
    assert c.log_ring_size == 2000


@pytest.mark.parametrize("port", [0, -1, 65536, 99999])
def test_port_out_of_range_rejected(port) -> None:
    with pytest.raises(ValidationError):  # fail-fast at boot, not a runtime bind error
        ControlConfig(port=port)


@pytest.mark.parametrize("size", [0, -1, 100_001])
def test_log_ring_size_out_of_range_rejected(size) -> None:
    # capped so an operator can't set a ring so large that /logs stalls the loop (P6-6 / DA, MEDIUM)
    with pytest.raises(ValidationError):
        ControlConfig(log_ring_size=size)


def test_is_frozen_and_forbids_extra_fields() -> None:
    c = ControlConfig()
    with pytest.raises(ValidationError):
        ControlConfig(enabledd=True)  # typo'd field caught (extra=forbid)
    with pytest.raises(ValidationError):
        c.enabled = False  # type: ignore[misc]  # frozen


def test_daemon_config_control_is_none_by_default() -> None:
    # the actual "off by default" safety: an absent control block => no control plane at all.
    assert DaemonConfig.model_fields["control"].default is None
