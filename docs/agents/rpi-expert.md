# Raspberry Pi Expert — Notes

> **Mandate:** Subject-matter expert on Raspberry Pi hardware, Raspberry Pi OS,
> and optimizing for the Pi. I read this file before every engagement and append
> durable learnings (date-stamped) after.

## Reference knowledge (verify specifics with Fact Checker before relying on them)

- **OS baseline:** Raspberry Pi OS (Bookworm, Debian 12) ships **Python 3.11**.
  CI therefore must pass on 3.11. Bookworm enforces PEP 668 ("externally managed
  environment") — system pip installs are blocked; use a venv or `pipx`.
- **GPIO landscape:** On Bookworm the modern stack is **`lgpio` / `gpiozero`**;
  legacy `RPi.GPIO` may not work the same on Pi 5 (new RP1 I/O chip). Prefer
  `gpiozero` for portability, abstracted behind our own interface.
- **Models matter:** Pi Zero/Zero 2 W vs Pi 4 vs Pi 5 differ hugely in CPU, RAM,
  power draw, and I/O. Confirm the **target model** before optimizing — it drives
  every performance decision.
- **Storage:** SD cards wear out under heavy writes. Minimize logging to card,
  consider `tmpfs` for transient writes, and design for read-mostly operation.
- **Power:** Brownouts corrupt filesystems. Favor journaled writes, atomic file
  replacement, and graceful handling of unexpected power loss.
- **Audio/RF:** "Pirate radio" likely involves audio out and possibly RF
  transmission. RF transmission is **heavily regulated** — flag legality to the
  Field Operator and user; never assume it's permitted.
- **Thermal:** Sustained load throttles the SoC without cooling. Long-running
  transmit/encode loops need thermal headroom.

## Optimization posture

- Measure on the **actual target model** before optimizing. Pi performance
  intuition from a Pi 4 does not transfer to a Pi Zero.
- Prefer hardware-accelerated paths where they exist; fall back gracefully.
- Keep the optimization KISS-compatible (Old Man will challenge complexity).

## Open questions

- Which Pi model(s) are we targeting?
- Audio output path? RF transmit, streaming, or both?
- Headless or with display/peripherals?

## Notes log

- _2026-06-07_ — Panel established. Awaiting design doc. Top unknowns: target Pi
  model and whether the project transmits RF (regulatory implications).

- _2026-06-07_ — **Round 1 review of PiRate_Radio_Design_Doc.md.** Durable
  Pi-specific findings:
  - **Doc never names a Pi model.** "Raspberry Pi class hardware" (§1/§4) spans
    Pi Zero (1 core, 512MB) to Pi 5 8GB — a >50x compute/RAM spread. The doc must
    pin a minimum model. This is the single biggest gap from a Pi lens.
  - **Local LLM (Ollama llama3.1) is the killer.** llama3.1 default = 8B params;
    Q4_K_M quant ≈ 4.7GB on disk and needs ~5–6GB RAM resident. Only the Pi 5 8GB
    can hold it at all, and CPU-only token gen on Pi 5 for an 8B model is ~2–5
    tok/s (assertion). A 40-word DJ intro (~55 tokens) = ~15–30s generation. The
    look-ahead buffer (§5.3, depth 1–2) hides latency only if production keeps up;
    one local-LLM call per item across 4 stations will not. Treat Ollama as a
    degraded **last-resort floor that may not meet real-time**, not a peer of cloud.
    Recommend: smaller model (llama3.2:1b/3b, phi3:mini, qwen2.5:3b) if local LLM
    is truly required, OR document that local-LLM-only mode runs NullDJ-equivalent
    cadence (sparse patter).
  - **Piper is the realistic local floor, but 4× concurrent is the load.** Piper
    (ONNX, CPU) synthesizes faster-than-real-time on Pi 4/5 for one stream
    (assertion: ~0.3–0.5x RTF single-thread on Pi 4), but 4 stations each running
    Piper + loudnorm via asyncio.to_thread will saturate a 4-core Pi during patter
    bursts. Bursts are bounded (look-ahead is depth 1–2, not continuous), so it's
    survivable IF generation is staggered, not synchronized. Synchronized top-of-hour
    station IDs (§5.1) deliberately align 4 TTS bursts — a thundering-herd risk.
  - **Core budget:** Pi 4/5 = 4 cores. 4 stations + asyncio loop + to_thread pool +
    (optional) Ollama all contend. asyncio is single-threaded; CPU offload is the
    real parallelism and there are only 4 cores. No headroom for local LLM on top.
  - **USB audio:** Pi 4/5 USB controller: Pi 4 has 2×USB3 + 2×USB2 on a shared
    VL805 hub; Pi 5 has a dedicated RP1. 4 full-duplex (output-only here) 48kHz/16-bit
    stereo dongles ≈ 4×1.5Mbit/s — trivial bandwidth, BUT 4 *identical* cheap USB
    dongles create a device-naming nightmare for sounddevice/PortAudio: identical
    "USB Audio Device" strings, index reordering across reboots/replug. §10/§12
    target device "by name/index" — both are unreliable across 4 identical units.
    Need ALSA persistent names via udev rules keyed on physical USB port path.
  - **SD card wear:** §14 writes catalog + daily schedules + resume state + flat-JSON
    logs all to card. Logs especially (per-item, 4 stations, 24/7) will wear a
    consumer SD card. Recommend logs/transient state to tmpfs or external SSD;
    boot from SSD/USB on Pi 4/5 is the right call for a 24/7 appliance.
  - **Thermal:** 24/7 sustained multi-core load (esp. with any LLM) WILL throttle a
    bare Pi 4/5 (throttle at 80–85°C). Active cooling (Pi 5 official cooler or
    case fan) is mandatory for this workload, not optional. Doc says nothing.
  - **Power:** 4 USB dongles + 4 FM TX modules possibly USB/GPIO-powered + sustained
    CPU = must use the official 27W (Pi 5) / 15W (Pi 4) PSU and likely powered USB
    hub for the dongles. Brownout corrupts the SD/SSD.
  - **Verdict:** Pi 5 8GB with active cooling + SSD boot is the only viable model
    for the full 4-station + AI-DJ vision. Cloud LLM + local Piper is feasible there.
    Local-LLM-on-Pi for 4 stations is NOT realistically real-time. Pi Zero/Zero 2 W
    is a non-starter for even one station with neural TTS.

- _2026-06-07_ — **Rev 2 client decisions update.** D1: target relaxed to Pi 5
  4GB, baseline Pi 4 4GB, must run acceptably on Pi 3 (1GB/4×A53). D2: the
  "local" LLM is a NETWORKED Ollama server on the LAN, NOT on-Pi inference — my
  on-Pi LLM RAM/tok-s BLOCKER is moot; on-Pi compute is now just ffmpeg + loudness
  + Piper TTS ×N. F1 stations-per-model guideline I gave: Pi 3 = 1 station (RAM
  wall: OS + 4 Piper models + 4 buffers spills to SD swap; A53 cores saturate on
  synchronized bursts); Pi 4 4GB = 4-station baseline w/ medium voices + staggered
  patter + active cooling; Pi 5 4GB = comfortable 4 stations, recommended target.

- _2026-06-07_ — **Phase 0 implementation plan review (RPi lens).** Phase 0 is
  pure logic (config/catalog/grid/persistence), no audio/RF, so most Pi risk is
  Phase 1+. Durable Pi-specific findings on the plan:
  - **R10 seam (audio_devices.py) is well-designed for testability** (Protocol +
    StaticAudioDeviceResolver fake, real UdevAudioDeviceResolver deferred to Phase
    4 behind @pytest.mark.hardware). BUT the contract is underspecified: the plan
    never pins WHAT a "stable name" is. ALSA card names (snd-usb-audio id=) are
    assignable via udev ATTR{id} keyed on KERNEL/physical port path, NOT by USB
    serial — cheap CM108/CM109 dongles share identical or absent serials, so
    serial-based udev rules collide. Must key on the physical port path. Also:
    sounddevice/PortAudio enumerate by PortAudio name, which is NOT the ALSA card
    id — the resolver must bridge PortAudio name -> ALSA hw:CARD=. Flag for Phase 4.
  - **Catalog full eager scan at startup (Open Q1) is a real Pi concern.** Flat
    tuple[Track,...] read via mutagen on every file. On Pi 3/4 with an SD-resident
    library of thousands of tracks, cold scan is slow (poor SD random-read IOPS);
    4 stations × full rescan at boot = noticeable startup latency. RAM is fine
    (Track ~hundreds of bytes). Result is persistable -> recommend Phase 1 cache +
    mtime-based rescan. Phase 0 eager is acceptable; flag latency, not a blocker.
  - **Atomic-write fsync cost on SD (persistence.py R5):** 2 fsyncs/write; cheap
    SD fsync = 10–100ms+ each. Phase 0 writes catalog cache only (infrequent), fine.
    Phase 1 per-item resume state ×4 stations would multiply this -> recommend
    batch/debounce and/or tmpfs+periodic flush in Phase 1. Flag forward.
  - **No Pi-hostile assumptions in Phase 0.** Python 3.11 / Bookworm OK; PyYAML
    safe_load, mutagen, pydantic all pure-Python or have ARM wheels. zoneinfo uses
    Bookworm system tzdata at /usr/share/zoneinfo (no pip tzdata needed); fine.
  - **D6 local-zone resolution** via datetime.now().astimezone().tzinfo: headless
    Pi with no RTC can have a wrong clock at boot until NTP syncs — D6 says trust
    OS, and only the zone (not instant) is resolved here, so OK. Host should have
    NTP + correct /etc/timezone. The PIRATE_RADIO_TZ override floated in Open Q5 is
    worth adopting for deterministic deployments.
