# PiRate Radio — first-boot runbook

The ordered steps to bring a fresh Raspberry Pi from blank to "N/N ON AIR". Do them in order; each
step assumes the previous one succeeded. Commands assume a Debian/Raspberry Pi OS box and the deploy
path `/opt/pirate-radio`.

## 0. Appliance prerequisites (24/7 hardware)

This is an always-on appliance, not a desktop. Before software:

- **Active cooling** — a heatsink + fan. A passively-cooled Pi throttles under sustained encode/TTS.
- **SSD boot, not the SD card** — boot from a USB/NVMe SSD. The mutable state dir (schedules) and the
  OS journal both write continuously; SD cards wear out and corrupt (A6/H26).
- **Official PSU** — an undervolted Pi browns out under USB-audio + CPU load. Use the official supply.
- **Powered USB hub** — the FM transmitter dongles draw more than the Pi's ports reliably provide;
  feed them from a powered hub.

## 1. System packages

```
sudo apt update
sudo apt install -y libportaudio2 ffmpeg espeak-ng
```

- **`libportaudio2` is mandatory** — the `sounddevice` wheel is pure-Python and does NOT bundle
  PortAudio; `pip install` succeeds but `import sounddevice` fails at runtime without this `.so`.
- `ffmpeg` is the decoder (R22). `espeak-ng` is the offline TTS floor.
- Piper / a cloud TTS / a LAN LLM are optional per your `config.json`.

## 2. Deploy the code + venv

```
sudo mkdir -p /opt/pirate-radio
sudo chown pirate:pirate /opt/pirate-radio
# copy the repo to /opt/pirate-radio, then:
cd /opt/pirate-radio
python3 -m venv .venv
.venv/bin/pip install -e .
```

## 3. Create the service user + state dir

```
sudo useradd --system --no-create-home --shell /usr/sbin/nologin pirate || true
sudo usermod -aG audio pirate            # PortAudio/ALSA device access
# StateDirectory= in the unit creates /var/lib/pirate-radio (0700) automatically on start;
# point config.state_dir at it (off the boot SD if that's a separate SSD mount — A6).
```

## 4. Secrets (root-owned, 0600)

NEVER put API keys in `config.json` or the unit file. Put them in the `EnvironmentFile`, named by the
`api_key_env` your config references (H22):

```
sudo install -m 0600 -o root -g root /dev/null /etc/pirate-radio/secrets.env
sudo tee -a /etc/pirate-radio/secrets.env >/dev/null <<'EOF'
ANTHROPIC_API_KEY=REPLACE_WITH_YOUR_KEY
ELEVENLABS_API_KEY=REPLACE_WITH_YOUR_KEY
EOF
```

The daemon reads each variable by name at build time; the value never touches a log or the repo.

## 5. udev rules — one stable name per dongle

Each FM transmitter must resolve to a stable name keyed on its **physical USB port** (R10/A2 — NOT
the serial; the CM10x dongles share/blank serials). Follow `docs/ops/udev-audio.md` to write one rule
per port, then:

```
sudo udevadm control --reload-rules
sudo reboot          # re-verify the names survive a reboot
# after reboot:
aplay -l             # confirm each dongle shows its assigned card name
```

Put each assigned name in the matching station's `audio_device` in `config.json`. **Moving a dongle to
another port reassigns which station transmits on it** — re-verify after any physical change.

## 6. Configuration

```
sudo install -m 0644 config.example.json /etc/pirate-radio/config.json
sudoedit /etc/pirate-radio/config.json     # set stations, audio_device names, grids, LLM/TTS, state_dir
```

**`state_dir` MUST equal the unit's `StateDirectory` mount** (`/var/lib/pirate-radio`, created `0700`
by systemd on start). If they differ, schedules write outside the unit-managed dir — wrong owner/mode
and, if that path is on the boot SD, defeating the off-SD goal (A6). To enable the optional control
API, add a `control` block here too — see `docs/ops/control-api.md` (off by default).

Dry-run the schedule generation before going live (oneshot, does not start the daemon):

```
sudo -u pirate /opt/pirate-radio/.venv/bin/python -m pirate_radio \
    --config /etc/pirate-radio/config.json --regenerate
```

A bad grid / missing content / unresolved `audio_device` fails loudly here, not at 3am.

## 7. Install + start the service

```
sudo cp systemd/pirate-radio.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pirate-radio
```

## 8. Confirm it's broadcasting

```
journalctl -u pirate-radio -f
```

Watch for, per station, `station <name> starting` then `station <name> on air`, and the periodic
**`N/N ON AIR`** summary. `N/N` means every station is up (a `crashed`/`restarting` station drops the
count and logs its scrubbed cause). A station that is up but airing the R11 bumper instead of real
content logs a **station-tagged** `backstop fired` WARNING (or, for a poison item, a `render-poison`
CRITICAL) — grep those to find a degraded-but-up station and check its LLM/TTS reachability:

```
journalctl -u pirate-radio | grep -E 'backstop fired|render-poison'
```

## Day-to-day

- **Regenerate after editing a grid:** re-run the `--regenerate` oneshot (optionally
  `--regenerate <station>` for just one). The **running daemon is unaffected** — it picks up a manual
  regen on its next midnight day-roll or a `systemctl restart`.
- **Logs:** `journalctl -u pirate-radio`. Restart/backoff/escalation, midnight regen done|FAILED, and
  backstop-fired events are all there, station-tagged.
- **Schedules** live under `state_dir/<station>/<date>.json` and roll automatically at local midnight
  (DST-correct).
