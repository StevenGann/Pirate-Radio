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


# The real UdevAudioDeviceResolver (reads udev/ALSA, bridges PortAudio name ->
# hw:CARD=) is deferred to Phase 4 multi-station bring-up, where it can be tested on
# real dongles behind @pytest.mark.hardware. It belongs here so config.py's import
# target never changes.
