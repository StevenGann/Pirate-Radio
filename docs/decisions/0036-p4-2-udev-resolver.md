# P4-2 — `UdevAudioDeviceResolver` (R10: stable USB device → PortId, port-path keyed) + udev recipe

Strict spec-driven TDD: tests authored from the adopted Phase-4 plan §F / P4-2 → confirmed RED →
focused panel (QA + DA) reviewed the TESTS → folded the must-fixes → implemented GREEN → gate →
commit.

## Panel review of the tests (focused: QA + Devil's Advocate)

**Round 1: QA AYE, DA NAY → REVISE.** The DA caught two CRITICALs the first cut missed:

- **The "port-path not serial" test didn't actually FORCE port-path keying.** It varied name +
  port_path + index all at once, so an impl keyed on the (unstable, reboot-shuffling) PortAudio
  `index` passed — defeating the whole R10 purpose. Added the discriminating pair: **same port /
  different index → must alias** (kills index-keying) and **same index / different port → must be
  distinct** (kills index-keying the other way), plus **same port / different serial → must alias**
  (makes `serial` provably non-load-bearing).
- **The FCC-critical enumeration had no hardware smoke** (vs. the TTS/ffmpeg/sink convention).
  Added `@pytest.mark.hardware test_udev_real_enumeration_yields_stable_port_paths` (real box,
  excluded from CI).
- Plus (DA): **ambiguous name** (one ALSA id → two ports) resolves to `None` (config rejects, not
  silent first-match); **empty enumeration** → `None` (boot-before-device tolerance, §H); and a
  `resolve`/`device_index` **None-biconditional** (the sink never gets an index for an unresolved
  name).

After folding, 14 pure tests + 1 hardware smoke pin the §F contract.

## Implementation

`audio_devices.py`: `AudioDevice` (frozen joined record — ALSA `name` + stable `port_path` +
PortAudio `index` + unused `serial`); `UdevAudioDeviceResolver` — `resolve(name) → PortId` keyed on
the **physical port path**, `device_index(name)` bridges to the PortAudio index for the sink, both
via a shared `_unique` (returns the device only when the name maps to exactly one distinct port;
absent OR ambiguous → None, so the biconditional holds). `_enumerate_hardware` (the only hardware:
lazy `import sounddevice` + sysfs `/sys/class/sound/<card>/device` port-path walk) is `pragma: no
cover` (R20) and validated by the hardware smoke; R21 no-module-scope-import guard. `StaticAudioDeviceResolver`
remains the CI resolver for `load_config`. `docs/ops/udev-audio.md`: the port-path-keyed udev rule +
`udevadm info -a` discovery walk + reboot-reverify + the move-a-dongle-reassigns-the-station note.

## Gate

ruff + ruff-format + mypy `--strict` clean (39 files); **597 tests** (+14; +1 hardware smoke
deselected), 98.53% coverage; `audio_devices.py` 97% (the Protocol `...` stub + the pragma'd
hardware enumeration are the only uncovered lines).

## Next

P4-3: `supervisor.py` (R7 tier-2: restart-to-known-good, sibling isolation, advance-past-poison by
item index, ceiling→injected on_escalate) + secret-scrub + `status.py` (`StationStatus`).
