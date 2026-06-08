"""RED tests for ``pirate_radio.audio_devices`` — the R10 resolver seam (A2).

Tests first: per adopted amendment A2 the resolver maps a configured device name to
a stable physical ``PortId`` (``resolve(name) -> PortId | None``), so config
validation can detect two distinct names that alias the *same* physical port — the
real R10 failure ("Station 2 transmits on Station 4's frequency"). The real udev
resolver is deferred to Phase 4; Phase 0 ships the Protocol + the static fake.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from pirate_radio.audio_devices import (
    AudioDevice,
    AudioDeviceResolver,
    StaticAudioDeviceResolver,
    UdevAudioDeviceResolver,
)

_SRC = Path(__file__).resolve().parents[2] / "src" / "pirate_radio"


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


# ---- P4-2: the real UdevAudioDeviceResolver (port-path keyed; PortAudio<->ALSA bridge) -----
# Enumeration (reading sounddevice + sysfs port paths) is the ONLY hardware line; the name->PortId
# mapping + the PortAudio-index bridge are PURE and tested here with an injected fake enumeration
# that models BOTH namespaces (the ALSA card name AND the PortAudio device index).


def _udev(devices: list[AudioDevice]) -> UdevAudioDeviceResolver:
    return UdevAudioDeviceResolver(enumerate_devices=lambda: list(devices))


def test_udev_resolves_name_to_portid_keyed_on_port_path() -> None:
    r = _udev([AudioDevice(name="pirate1", port_path="usb-0000:01:00.0-1.2", index=3)])
    assert r.resolve("pirate1") == "usb-0000:01:00.0-1.2"  # the stable physical PORT PATH


def test_udev_unknown_name_resolves_to_none() -> None:
    r = _udev([AudioDevice(name="pirate1", port_path="usb-1.2", index=3)])
    assert r.resolve("nope") is None


def test_udev_keys_on_port_path_NOT_serial() -> None:
    # CM10x dongles share/empty serials; two dongles with the SAME serial on DIFFERENT ports
    # must resolve to DISTINCT PortIds, or Station 2 lands on Station 4's transmitter (FCC).
    r = _udev(
        [
            AudioDevice(name="pirate1", port_path="usb-1.2", index=3, serial="SHARED"),
            AudioDevice(name="pirate2", port_path="usb-1.3", index=4, serial="SHARED"),
        ]
    )
    assert r.resolve("pirate1") != r.resolve("pirate2")  # distinct ports -> distinct PortIds


def test_udev_two_names_same_port_alias_to_one_portid() -> None:
    # the A2 aliasing case: two config names pointing at one physical port -> equal PortId
    r = _udev(
        [
            AudioDevice(name="a", port_path="usb-1.2", index=3),
            AudioDevice(name="b", port_path="usb-1.2", index=3),
        ]
    )
    assert r.resolve("a") == r.resolve("b")


def test_udev_same_port_different_index_still_aliases() -> None:
    # DA: forces keying on port_path NOT the (unstable) PortAudio index — same port, diff index
    # must alias; an index-keyed impl would wrongly return distinct PortIds and fail.
    r = _udev(
        [
            AudioDevice(name="a", port_path="usb-1.2", index=3),
            AudioDevice(name="b", port_path="usb-1.2", index=9),
        ]
    )
    assert r.resolve("a") == r.resolve("b")


def test_udev_same_index_different_port_is_distinct() -> None:
    # DA: the converse — same PortAudio index, different physical ports must be DISTINCT (an
    # index-keyed impl would collapse them).
    r = _udev(
        [
            AudioDevice(name="a", port_path="usb-1.2", index=5),
            AudioDevice(name="b", port_path="usb-1.3", index=5),
        ]
    )
    assert r.resolve("a") != r.resolve("b")


def test_udev_same_port_different_serial_still_aliases() -> None:
    # DA: makes `serial` provably NON-load-bearing — same port, different serial must alias.
    r = _udev(
        [
            AudioDevice(name="a", port_path="usb-1.2", index=3, serial="S1"),
            AudioDevice(name="b", port_path="usb-1.2", index=3, serial="S2"),
        ]
    )
    assert r.resolve("a") == r.resolve("b")


def test_udev_ambiguous_name_resolves_to_none() -> None:
    # DA: one ALSA name mapping to TWO distinct ports (udev rules misconfigured) is ambiguous —
    # resolve must return None (unresolvable -> config rejects), NOT silently pick the first.
    r = _udev(
        [
            AudioDevice(name="dup", port_path="usb-1.2", index=3),
            AudioDevice(name="dup", port_path="usb-1.3", index=4),
        ]
    )
    assert r.resolve("dup") is None
    assert r.device_index("dup") is None


def test_udev_empty_enumeration_resolves_to_none() -> None:
    # §H: the daemon must tolerate boot-before-device-present — empty enumeration -> None, no crash
    assert _udev([]).resolve("pirate1") is None


def test_udev_resolve_and_index_agree_on_existence() -> None:
    # DA: resolve(name) is None IFF device_index(name) is None — the sink must never get a PortId
    # it can't open (or an index for a name that didn't resolve).
    r = _udev([AudioDevice(name="pirate1", port_path="usb-1.2", index=3)])
    for name in ("pirate1", "missing", "dup"):
        assert (r.resolve(name) is None) == (r.device_index(name) is None)


def test_udev_device_index_bridges_to_portaudio() -> None:
    # the sink needs the PortAudio device index; the resolver bridges name -> ALSA -> PA index
    r = _udev(
        [
            AudioDevice(name="pirate1", port_path="usb-1.2", index=3),
            AudioDevice(name="pirate2", port_path="usb-1.3", index=7),
        ]
    )
    assert r.device_index("pirate2") == 7
    assert r.device_index("nope") is None


def test_udev_resolver_satisfies_protocol() -> None:
    assert isinstance(_udev([]), AudioDeviceResolver)


def test_udev_resolver_no_module_scope_sounddevice_import() -> None:
    tree = ast.parse((_SRC / "audio_devices.py").read_text())
    for node in tree.body:
        roots: list[str] = []
        if isinstance(node, ast.Import):
            roots = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            roots = [(node.module or "").split(".")[0]]
        assert "sounddevice" not in roots, "sounddevice must be imported lazily (R21)"


@pytest.mark.hardware
def test_udev_real_enumeration_yields_stable_port_paths() -> None:
    # DA: the FCC-critical enumeration (sounddevice + sysfs -> physical port path) must be
    # exercised on a real box, not only via the injected fake. Matches the TTS/ffmpeg/sink
    # hardware-smoke convention; excluded from CI (`-m "not hardware"`).
    devices = UdevAudioDeviceResolver()._enumerate_hardware()
    assert devices, "no audio output devices enumerated on this host"
    for d in devices:
        assert isinstance(d.port_path, str) and d.port_path  # a real, non-empty stable port path
        assert isinstance(d.index, int)
