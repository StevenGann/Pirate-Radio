"""RED tests for ``pirate_radio.audio_devices`` — the R10 resolver seam (A2).

Tests first: per adopted amendment A2 the resolver maps a configured device name to
a stable physical ``PortId`` (``resolve(name) -> PortId | None``), so config
validation can detect two distinct names that alias the *same* physical port — the
real R10 failure ("Station 2 transmits on Station 4's frequency"). The real udev
resolver is deferred to Phase 4; Phase 0 ships the Protocol + the static fake.
"""

from __future__ import annotations

from pirate_radio.audio_devices import AudioDeviceResolver, StaticAudioDeviceResolver


def test_resolves_known_name_to_its_portid() -> None:
    r = StaticAudioDeviceResolver({"usb-port-1": "phys-A"})
    assert r.resolve("usb-port-1") == "phys-A"


def test_unknown_name_resolves_to_none() -> None:
    r = StaticAudioDeviceResolver({"usb-port-1": "phys-A"})
    assert r.resolve("usb-port-9") is None


def test_distinct_names_can_alias_one_physical_port() -> None:
    # The seam must be able to express the R10 aliasing failure (two names, one port).
    r = StaticAudioDeviceResolver({"usb-port-1": "phys-A", "usb-port-2": "phys-A"})
    assert r.resolve("usb-port-1") == r.resolve("usb-port-2") == "phys-A"


def test_distinct_names_distinct_ports() -> None:
    r = StaticAudioDeviceResolver({"usb-port-1": "phys-A", "usb-port-2": "phys-B"})
    assert r.resolve("usb-port-1") != r.resolve("usb-port-2")


def test_static_resolver_satisfies_protocol() -> None:
    assert isinstance(StaticAudioDeviceResolver({}), AudioDeviceResolver)
