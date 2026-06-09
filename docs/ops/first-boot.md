# PiRate Radio — first-boot runbook

The ordered steps to bring a fresh Raspberry Pi from blank to "N/N ON AIR". Do them in order; each
step assumes the previous one succeeded. Commands assume a Debian/Raspberry Pi OS box and the deploy
path `/opt/pirate-radio`.

## 0. Appliance prerequisites (24/7 hardware)

> ⚠️ **Legality first — read before transmitting.** Operating an FM transmitter is **regulated and
> often requires a licence**. In the US, unlicensed operation must stay within FCC Part 15
> field-strength limits (very low power, a few hundred feet at most); most countries have an
> equivalent rule, and higher power or multiple stations generally needs a licence. **Confirm what is
> legal for your band, power, and location before you key up** — it is your responsibility, not the
> software's. Wired or stream-only output (no RF) sidesteps this entirely.

This is an always-on appliance, not a desktop. Before software:

- **Active cooling** — a heatsink + fan. A passively-cooled Pi throttles under sustained encode/TTS.
- **SSD boot, not the SD card** — boot from a USB/NVMe SSD. The mutable state dir (schedules) and the
  OS journal both write continuously; SD cards wear out and corrupt (A6/H26).
- **Official PSU** — an undervolted Pi browns out under USB-audio + CPU load. Use the official supply.
- **Powered USB hub** — the FM transmitter dongles draw more than the Pi's ports reliably provide;
  feed them from a powered hub.
- **RAM headroom** — a **4 GB** Pi is the multi-station baseline (Pi 3 / 1 GB is a single-station
  floor). The daemon fail-fasts at boot if the look-ahead **audio buffers** (≈ one decoded whole
  track per buffered slot × stations × depth) won't fit its fixed budget; the error names the fix
  (fewer stations, shorter longest track, or a higher budget). Note that budget covers the audio
  buffers specifically — the Python/numpy/ffmpeg/Piper baseline adds a few hundred MB of RSS on top,
  so leave headroom. One very long track (a live set, a podcast) drives the whole fleet's budget — if
  boot rejects your RAM, check for an outlier-length file.

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
# Optional, for the Piper neural voice — the maintained piper1-gpl fork (rhasspy/piper is archived):
.venv/bin/pip install piper-tts
.venv/bin/python -m piper.download_voices en_US-ryan-high   # into tts_providers.piper.voices_dir
```

Piper runs as `python -m piper` from this venv (no `binary` path; set `tts_providers.piper.python`
only if you install it in a *separate* venv). Keep `voices_dir` on the SSD (it reloads per call).

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

**`state_dir` MUST equal the unit's `StateDirectory` path** (`/var/lib/pirate-radio`, created `0700`
by systemd on start — this is what `config.example.json` ships). If they differ, schedules write
outside the unit-managed dir — wrong owner/mode, and you lose the systemd-managed lifecycle.

**Keeping state off the boot SD (A6).** The schedules under `state_dir` write continuously, so they
must not live on the SD card. The §0 **SSD/USB boot** recommendation handles this automatically:
when the whole OS (and thus `/var/lib`) is on the SSD, `/var/lib/pirate-radio` is already off the SD.
**If you must boot from the SD card**, mount the SSD over `/var/lib` (or `/var/lib/pirate-radio`
specifically) via `/etc/fstab` *before* first start, so `StateDirectory` lands on the SSD.

To enable the optional control API, add a `control` block here too — see
`docs/ops/control-api.md` (off by default).

**Before this step, lay out your content folders and write your grid files.** The radio plays what
your grids schedule from your content groups, and the dry-run below validates both. If you have not
done this yet, follow [`grids.md`](grids.md) (grid YAML schema, filename resolution, the
`content_dir/<group>/` layout, accepted audio extensions, and a worked example) — then come back.

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
  regen on its next midnight day-roll or a `systemctl restart`. (See [`grids.md`](grids.md) for the
  grid schema.)
- **Add + tag content:** drop files into the right `content_dir/<group>/` folder and tag them — see
  [`tagging.md`](tagging.md). Regenerate to pick them up.
- **Status / control (optional):** if you enabled the control API, see
  [`control-api.md`](control-api.md) for skip/regenerate/status/logs over an SSH tunnel.
- **Logs:** `journalctl -u pirate-radio`. Restart/backoff/escalation, midnight regen done|FAILED, and
  backstop-fired events are all there, station-tagged.
- **Turn up verbosity on a degraded station:** the entrypoint takes `--log-level` (default `INFO`).
  Add `--log-level DEBUG` to the `ExecStart=` line (or via a drop-in) and `systemctl restart` to see
  per-render detail. Note **DEBUG is dropped from the control-API `/logs` ring** — DEBUG shows in
  journald only (`journalctl -u pirate-radio`), so that is where to look when chasing a render issue.
- **Schedules** live under `state_dir/<station>/<date>.json` and roll automatically at local midnight
  (DST-correct).

## Recovery & troubleshooting

A quick journald vocabulary, and what to do when things break unattended:

| You see (`journalctl -u pirate-radio`) | Meaning | Action |
|---|---|---|
| `station <n> starting` → `on air` | normal bring-up | — |
| `N/N ON AIR` (periodic) | all N stations up | — |
| `backstop fired` (WARN, station-tagged) | a station is up but airing the R11 bumper | check that station's LLM/TTS reachability + content |
| `render-poison` (CRITICAL) | an item repeatedly failed to render | inspect/replace the offending file |
| `<n>: crashed … restart k/5` | a station crashed; supervisor is restarting it | watch for escalation |
| `escalating to the systemd tier` | the in-process restart ceiling was hit | see "keeps crashing" below |
| `control-api task crashed\|exited` | the control plane died (broadcast continues) | see [`control-api.md`](control-api.md) |

- **The daemon keeps crashing / is in `failed` state.** After 5 crashes in 60s systemd stops
  restarting and the unit enters a terminal **`failed`** state (so a human looks, instead of an
  infinite flap). Check `systemctl status pirate-radio` (look for `start-limit-hit`), read the
  journal for the cause (bad grid, missing content, unresolved `audio_device`, missing secret), fix
  it, then **`sudo systemctl reset-failed pirate-radio && sudo systemctl start pirate-radio`**.
- **Disk fills up.** Unattended for weeks, the journal + per-day schedules can fill the disk; writes
  then fail and you'll see schedule-write/regen errors in the journal. Mitigate: keep `state_dir` on
  the SSD (not the SD), cap the journal (`journalctl --vacuum-size=200M`, or set `SystemMaxUse=` in
  `/etc/systemd/journald.conf`), and monitor with `df -h`.
- **Stop / restart cleanly.** `sudo systemctl restart pirate-radio` — the daemon catches SIGTERM and
  drains (closing the audio devices) before exiting, so a USB dongle is released cleanly for the
  restart.
