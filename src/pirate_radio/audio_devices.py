"""Stable audio-device-name resolution seam (R10, amendment A2).

R10 requires each station's configured ``audio_device`` to resolve to a STABLE
physical identity (a ``PortId``, keyed on the udev/ALSA physical USB port path), and
config validation to fail fast if a name does not resolve or if two *distinct* names
alias the *same* physical port (the real "Station 2 on Station 4's transmitter"
failure). CI has no hardware, so resolution is a Protocol: production injects a real
udev/ALSA resolver; tests inject a ``StaticAudioDeviceResolver`` backed by a fixed
name->PortId mapping. Phase 0 ships only the Protocol + the static fake.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import NewType, Protocol, runtime_checkable

# A stable physical device identity (e.g. a udev-assigned ALSA card id keyed on the
# physical USB port path). Distinct from the human-facing config `audio_device` name.
PortId = NewType("PortId", str)


@runtime_checkable
class AudioDeviceResolver(Protocol):
    """Resolves a configured device name to its stable physical identity."""

    def resolve(self, name: str) -> PortId | None:
        """Return the stable ``PortId`` for ``name``, or ``None`` if it does not
        resolve to a device on this host (R10). Config validation rejects ``None``
        and rejects two names resolving to the same ``PortId``."""
        ...


class StaticAudioDeviceResolver:
    """Test/dev resolver backed by a fixed name->PortId mapping. CI uses this.

    Maps names to PortIds (not a bare name set) so config validation can detect two
    distinct config names that alias one physical port (amendment A2).
    """

    def __init__(self, mapping: dict[str, str]) -> None:
        self._by_name: dict[str, PortId] = {name: PortId(pid) for name, pid in mapping.items()}

    def resolve(self, name: str) -> PortId | None:
        return self._by_name.get(name)


@dataclass(frozen=True)
class AudioDevice:
    """One enumerated output device — the POST-ENUMERATION joined record spanning both
    namespaces: ``name`` (the ALSA card id the operator puts in ``config.audio_device``,
    udev-assigned per the recipe), ``port_path`` (the stable physical USB port path — the
    ``PortId`` key, survives reboots), and ``index`` (the PortAudio device index the sink opens).
    ``serial`` is recorded but NEVER used for keying (CM10x dongles share/empty serials, R10)."""

    name: str
    port_path: str
    index: int
    serial: str | None = None


class UdevAudioDeviceResolver:
    """Real R10 resolver: configured name -> stable ``PortId`` **keyed on the physical USB port
    path** (NOT serial — identical/empty CM10x serials would alias distinct transmitters). Also
    bridges name -> the PortAudio device index for the sink. The udev/ALSA + sysfs enumeration is
    the ONLY hardware line; the name->port_path / name->index mapping over the enumerated records
    is PURE (the enumeration is injectable for tests)."""

    def __init__(self, *, enumerate_devices: Callable[[], list[AudioDevice]] | None = None) -> None:
        self._enumerate = enumerate_devices or self._enumerate_hardware

    def _unique(self, name: str) -> AudioDevice | None:
        """The single device for ``name``, or None if absent OR ambiguous (one ALSA name mapping
        to >1 distinct physical port — a misconfigured udev rule). None makes config validation
        reject it rather than silently picking the wrong transmitter."""
        matches = [d for d in self._enumerate() if d.name == name]
        ports = {d.port_path for d in matches}
        if len(ports) != 1:  # 0 = absent, >1 = ambiguous
            return None
        return matches[0]

    def resolve(self, name: str) -> PortId | None:
        device = self._unique(name)
        return PortId(device.port_path) if device is not None else None

    def device_index_for_port(self, port_id: PortId) -> int | None:
        """The PortAudio **device index** for a resolved ``PortId`` (port path). The sink opens by
        index, NOT by the sysfs port path — the prod ``sink_factory`` receives the stable ``PortId``
        (R10 identity) and must translate it here; passing the port path to PortAudio would fail.
        None if no enumerated device has that port path (or it is ambiguous across indices)."""
        indices = {d.index for d in self._enumerate() if d.port_path == str(port_id)}
        if len(indices) != 1:  # 0 = gone since resolution, >1 = ambiguous
            return None
        return next(iter(indices))

    def _enumerate_hardware(self) -> list[AudioDevice]:  # pragma: no cover (R20: hardware only)
        # Lazy (R21): never imported on the CI path. Enumerate PortAudio output devices, parse the
        # ALSA card id from each, and derive the stable physical port path from sysfs
        # (/sys/class/sound/<card>/device -> the USB ID_PATH). The udev recipe (docs/ops) assigns
        # each dongle a stable ALSA card id keyed on its physical port. Validated by the
        # @pytest.mark.hardware enumeration smoke on a real box.
        import re
        from pathlib import Path

        import sounddevice as sd

        devices: list[AudioDevice] = []
        for index, info in enumerate(sd.query_devices()):
            if info.get("max_output_channels", 0) < 1:
                continue
            pa_name = str(info["name"])
            card = pa_name.split(":", 1)[0].strip()  # "pirate1: USB Audio (hw:2,0)" -> "pirate1"
            m = re.search(r"hw:(\d+)", pa_name)  # also grab the ALSA card number for the sysfs walk
            card_no = m.group(1) if m else None
            port_path: str | None = None
            for candidate in (f"card{card_no}" if card_no else None, card):
                if not candidate:
                    continue
                dev = Path(f"/sys/class/sound/{candidate}/device")
                if dev.exists():
                    port_path = dev.resolve().name  # the stable USB port-path leaf
                    break
            if port_path is None:
                continue
            devices.append(AudioDevice(name=card, port_path=port_path, index=index))
        return devices
