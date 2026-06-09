# Stable USB audio device names (udev) — operator recipe (R10)

PiRate Radio runs one station per USB audio dongle, each feeding its own FM transmitter. ALSA card
numbers (`card0`, `card1`, …) are assigned in **enumeration order and reorder across reboots** — so
without stable names, after a reboot **Station 2 can end up on Station 4's transmitter** (a
wrong-frequency misbroadcast, FCC-relevant). This recipe pins each dongle to a **stable name keyed
on its physical USB port path**, so a station always reaches the same transmitter.

> **Key on the physical PORT PATH, never the serial.** Cheap CM108/CM109 dongles share an identical
> (or empty) USB `iSerial`. A serial-keyed rule collides → two stations resolve to the same device.
> `UdevAudioDeviceResolver` keys on the port path for exactly this reason; the udev rule must too.

## 1. Discover each dongle's physical port path

Plug the dongles into the ports you intend to keep them in (an appliance: one dongle per fixed port,
ideally on a powered USB hub). For each ALSA card:

```bash
# list cards -> card numbers + names
cat /proc/asound/cards

# walk the device tree for card N to find the PHYSICAL PORT PATH (KERNELS=usb...)
udevadm info -a /sys/class/sound/card1 | grep -m1 -E 'KERNELS=="[0-9]+-[0-9.]+"'
#   e.g.  KERNELS=="1-1.2"   <- the physical port path; this is what survives reboots
```

Record which physical port (`1-1.2`, `1-1.3`, …) you want to be `pirate1`, `pirate2`, ….

## 2. Write the udev rules — keyed on `KERNELS` (the port path), assigning a stable ALSA id

`/etc/udev/rules.d/85-pirate-radio-audio.rules`:

```
# Assign a STABLE ALSA card id per physical USB port (NOT per serial).
SUBSYSTEM=="sound", KERNELS=="1-1.2", ATTR{id}="pirate1"
SUBSYSTEM=="sound", KERNELS=="1-1.3", ATTR{id}="pirate2"
SUBSYSTEM=="sound", KERNELS=="1-1.4", ATTR{id}="pirate3"
SUBSYSTEM=="sound", KERNELS=="1-1.5", ATTR{id}="pirate4"
```

Reload + re-trigger (or reboot):

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

## 3. Use the assigned ids in `config.json`

Each station's `audio_device` is the udev-assigned ALSA id:

```jsonc
"stations": [
  { "name": "PiRate One", "audio_device": "pirate1", /* ... */ },
  { "name": "PiRate Two", "audio_device": "pirate2", /* ... */ }
]
```

At boot the daemon resolves each `audio_device` → a stable `PortId` (the physical port path) and
**fails fast** if a name doesn't resolve or if two names resolve to the same physical port (R10/A2).

## 4. Reboot and RE-VERIFY

```bash
sudo reboot
# after boot:
cat /proc/asound/cards          # pirate1..pirateN present
# confirm the daemon resolved every station (no "does not resolve" ConfigError in the journal):
journalctl -u pirate-radio -b | grep -iE 'audio_device|resolve|PortId'
```

Re-verify after **every** physical change. **Moving a dongle to a different USB port reassigns its
station** (the name follows the port, not the dongle) — that's the intended, stable behaviour for a
fixed appliance, but it means you must keep each dongle in its assigned port.


---

**Related:** [`first-boot.md`](first-boot.md) (the full bring-up runbook) · [`config-reference.md`](config-reference.md) (every config key).
