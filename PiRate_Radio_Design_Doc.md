# PiRate Radio — Design Document

> *Radio Free Pi* — an automated, multi-station FM radio broadcaster with an AI DJ.

| | |
|---|---|
| **Project** | PiRate Radio (styled with the **Pi** emphasized; tagline *Radio Free Pi*) |
| **Status** | **Reviewed** — panel-adopted (7–0, two rounds). Rev 2 resolutions incorporated; see §21 and `docs/decisions/0001`, `0002`. |
| **Audience** | Development team |
| **Host** | Runs on the `Caliope` server (Linux / Raspberry Pi class hardware) |
| **Predecessor / inspiration** | [FieldStation42](https://github.com/shane-mason/FieldStation42) (broadcast/cable TV simulator) — PiRate Radio is its spiritual successor for radio |

> **Naming note:** "pirate radio" is a generic phrase, so the published package / repo slug should use a distinguishing form (e.g. `pirate-radio`, `pi-rate`, or `pirateradio`). Confirm availability on PyPI/GitHub before publishing.

---

## 1. Overview

PiRate Radio turns a Linux box into a set of automated radio stations. Each station continuously plays audio from a content library, organized into genre/format **groups**, following a hand-authored daily **programming grid**. Between tracks, an optional **AI DJ** introduces and recaps songs, drops grounded factoids, and announces programming blocks — synthesized to speech locally or via a cloud TTS provider.

The system is a **single daemon** that supervises **N independent stations** (one per FM transmitter). In the target deployment, four stations each render audio to a dedicated USB audio device feeding a low-power FM transmitter on its own frequency.

The defining design goal, borrowed from FieldStation42, is **broadcast realism**: programming exists on a wall-clock timeline whether or not anyone is listening. A receiver tuning in catches whatever is currently airing, mid-song — there is no "start." For an FM deployment this falls out naturally, because the transmitter radiates continuously and the *receiver* is what tunes in.

## 2. Goals and Non-Goals

**Goals**
- Continuous, gapless playback per station with no dead air.
- Hand-authored, FieldStation42-style daily schedules driven by folder-based content groups and time-of-day slots.
- Optional AI DJ: TTS intros/outros, grounded factoids, and block announcements.
- Pluggable TTS, LLM, and audio-output backends (local-first, cloud-optional).
- Multiple independent stations from a single supervised process.
- Resilience: a crashed station self-restarts and resumes the correct point in the broadcast.

**Non-Goals (v1)**
- Internet streaming / Icecast / on-demand. Output is to a local audio device only.
- A music library *manager* (PiRate reads tags; it does not rename/move files).
- Live human DJ input, call-ins, or live ad insertion.
- A polished web UI / browser console. (The REST **control API itself is in scope for v1** — see §15 and §21/D4. Only a polished browser UI on top of it is deferred.)

## 3. Glossary

| Term | Meaning |
|---|---|
| **Station** | One independent broadcast: one content library, one grid, one audio device. |
| **Group** | A content category, defined by a top-level subfolder of the station's content dir (e.g. `classical/`, `oldies/`, `radio_plays/`). |
| **Catalog** | The in-memory index of tracks, tagged by group, with metadata. Built by scanning the content dir. |
| **Grid** (a.k.a. *format clock*) | The hand-authored template mapping time-of-day → group. The *intent*. |
| **Slot** | One time range within a grid, bound to a single group. |
| **Daily Schedule** | The concrete, generated, ordered list of items for one calendar day. The *realized instance* of the grid. |
| **ScheduleItem** | One unit in the daily schedule: a track, a station ID, a block transition, or a block reminder, with a planned airtime. (The canned R11 backstop is **not** a ScheduleItem — it is a pre-rendered audio fallback, kept distinct.) |
| **Segment** | What the player actually streams for one item: optional intro + content + optional outro. |
| **Producer** | Per-station task that renders upcoming items just ahead of the playhead (LLM patter → TTS → assembled audio). |
| **Player (Consumer)** | Per-station task that drains the look-ahead buffer and streams to the audio device. |
| **Coordinator** | The single daemon that supervises stations and owns shared services. |

## 4. System Context & Deployment

```
                         Caliope (Linux / Pi)
        ┌───────────────────────────────────────────────┐
        │                PiRate Radio daemon             │
        │                                                │
        │   Station 1 ── USB audio 1 ── FM TX @ f1 ──))) │
        │   Station 2 ── USB audio 2 ── FM TX @ f2 ──))) │
        │   Station 3 ── USB audio 3 ── FM TX @ f3 ──))) │
        │   Station 4 ── USB audio 4 ── FM TX @ f4 ──))) │
        └───────────────────────────────────────────────┘
```

One process, N stations, N audio devices, N transmitters on distinct frequencies. RF concerns (SWR, intermodulation, antenna/patch routing) are handled in hardware and are out of scope for this document.

### 4.1 Deployment / Hardware (per D1 / decision 0002)

**Stations-per-Pi-model guideline** (on-Pi compute = ffmpeg decode + loudness + Piper TTS ×N; LLM inference is off-box, see §21/D2):

| Pi model | Tier | Notes |
|---|---|---|
| **Pi 3 / 1 GB** | single-station **demo** | RAM-bound; requires 64-bit **Bookworm**. |
| **Pi 4 / 4 GB** | **4-station baseline** | medium-quality voices, staggered patter, **active cooling required**. |
| **Pi 5 / 4 GB** | **recommended** | 4 stations comfortably. |

The design does **not** require 8 GB.

**24/7 appliance requirements.** This runs as an always-on broadcaster, so:

- **Active cooling is REQUIRED** (especially at the 4-station tier — sustained multi-core load throttles a passively-cooled SoC; see §17).
- **SSD / USB boot** rather than running long-term off the SD card (mutable writes already kept off the boot SD via `state_dir` and `PrivateTmp`).
- **Official PSU** (under-volt warnings under load otherwise) and a **powered USB hub** for the multiple USB audio dongles + transmitters.

**RF legality (acknowledgment).** FM transmission is **regulated** — e.g. US **FCC Part 15** field-strength limits, with equivalents elsewhere. Operating legality (license/power/antenna) is the **deployer's responsibility**; it is out of scope for the *code* but acknowledged here (§21/D7-style). A **wired or stream-only** deployment sidesteps the RF question entirely.

## 5. Architecture

### 5.1 Single coordinator, supervised stations

PiRate Radio runs as one daemon. This matches FieldStation42's own topology (a single coordinator with a web console managing all channels) and is what unlocks shared, cross-station behavior: shared LLM/TTS clients with ranked provider failover, one catalog index, synchronized top-of-hour station IDs, a single control plane, and unified logging.

```
┌────────────────────────────────────────────────────────────────┐
│                       Coordinator (daemon)                       │
│  ┌────────────┐   ┌──────────────────┐   ┌────────────────────┐ │
│  │ Supervisor │   │ Shared LLM / TTS │   │ Catalog            │ │
│  │ (restarts  │   │ clients +        │   │ (folder → group,   │ │
│  │  stations) │   │ rate limiter     │   │  metadata index)   │ │
│  └─────┬──────┘   └─────────▲────────┘   └─────────▲──────────┘ │
│        │ supervises         │ shared               │ shared      │
│        ▼                    │                      │             │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Station worker  (× N)                                     │  │
│  │                                                           │  │
│  │  Grid ──► Daily Schedule ──► Producer ──► [look-ahead     │  │
│  │  (yaml)    (generated,        (JIT: patter  buffer queue] │  │
│  │            persisted)          + TTS +            │       │  │
│  │                                assemble)          ▼       │  │
│  │                                            Player ──► Sink │  │
│  │                                          (sounddevice →   │  │
│  │                                           USB → FM TX)    │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

### 5.2 Concurrency model

Use `asyncio`. The workload is I/O-bound (network calls to LLM/TTS, disk reads, feeding the audio device), so a cooperative single-threaded event loop is the right fit — tasks yield at `await` points and one loop juggles all stations without locks. CPU-heavy work (audio decode, resample, loudness analysis) is offloaded with `asyncio.to_thread` so it never stalls the loop.

### 5.3 Latency hiding (the core problem)

LLM patter generation and TTS synthesis take seconds. The naive "play file → synthesize next intro → play next" loop produces dead air. PiRate avoids this with a **producer/consumer look-ahead pipeline** (conceptually a ping-pong / double buffer):

- The **producer** assembles complete segments ahead of time and pushes them into a **bounded queue** (`asyncio.Queue`).
- The **player** pulls from the queue and streams gaplessly.
- Queue depth = look-ahead buffer, sized to mask the worst patter cluster (`worst_consecutive_patter + 1`; realistically 2). The RAM budget that bounds it is **Appendix A**.

Slow generation stalls *buffer refill*, never playback.

### 5.4 Fault isolation: the supervisor pattern

Each station is an isolated unit under a supervisor (the "let it crash" / watchdog model). If a station task dies, the supervisor restarts it to a known-good state without affecting the others.

**v1 decision:** stations are `asyncio` tasks under one supervisor (lightweight, shared caches/clients). The known risk is that a hard crash in a native audio library (a segfault, not a Python exception) takes the whole process down — and the **in-process supervisor cannot catch a SIGSEGV**. **Mitigation (per R13):** the actual SIGSEGV recovery is the **`systemd` unit (R7)**, which restarts the whole process. Keep the station boundary a clean interface, but do **not** promise a drop-in subprocess promotion — if a native library proves unstable enough to need subprocess isolation, **expect a real refactor** (the look-ahead buffer, shared clients, and sink handoff all cross the boundary). Do not build subprocess isolation up front.

## 6. The Broadcast-Time Model

A station's schedule is anchored to wall-clock time. The player never "starts from the top"; it asks **what should be airing right now, and at what offset**, then seeks into it.

- **Cold start mid-day** and **post-crash resume** use the identical path.
- The daily schedule is **persisted to disk**. On startup the station loads today's schedule if it exists; it only generates a new one when the file is missing or the day has rolled over. (This is what makes resume meaningful — a restart must not reshuffle the day.)

```python
def find_now(schedule: DailySchedule, now: datetime) -> tuple[ScheduleItem | None, float]:
    for item in schedule.items:
        end = item.planned_start + timedelta(seconds=item.duration)
        if item.planned_start <= now < end:
            return item, (now - item.planned_start).total_seconds()  # seek offset
    return None, 0.0
```

**Drift:** `planned_start` is an *estimate*, because real TTS length is unknown until synthesis (track durations are exact from metadata). The player advances by the **actual** rendered length of each segment, while `find_now` reconstructs the timeline from each item's **estimated** duration — so a mid-day resume seek is *approximate* to within the accumulated patter-estimate error up to that point. *(Correction adopted during implementation: the shipped `schedule/resume.py::anchor` re-anchors the timeline once per day-slice from `items[0].planned_start` (the slice's exact start instant) — it does **not** re-anchor hourly or at station IDs. The real bound on intra-day drift is therefore the **next same-day regeneration / day-roll re-slice**, which rebuilds the timeline from a fresh exact anchor; there is no "never compounds past an hour" guarantee. v1 accepts the accumulated estimate error within a slice.)*

> **Phase-1 correction (H13, implemented in `schedule/resume.py`).** The sketch above
> returns a bare `(item, None)` which is ambiguous about silence gaps. The shipped
> implementation returns a typed **`NowPlaying`** — `(item, offset_seconds, next_item,
> gap_seconds)` — so the two resume rules are explicit: **R11** (a `now` inside a
> transition-silence gap returns `item=None` *with* `next_item`+`gap_seconds`, never
> undefined dead air) and **R12** (the timeline is *re-anchored* — rebuilt from the
> first item's exact start plus each item's duration and the known silence — so a
> drifted stored `planned_start` cannot mislead playback). The lookup is anchored once
> and answered per tick by binary search (**H4**). See `docs/decisions/0011`–`0012`.

**Clock assumptions & DST policy (D6/R9).** Because schedule selection and the day-roll
are wall-clock-driven, the daemon assumes a **time-synced clock**:

- **Startup is gated on a corrected clock.** The shipped `systemd/pirate-radio.service`
  declares `After=… time-sync.target …`, so on an RTC-less Pi the daemon does not start
  (and anchor the day) until the OS has stepped the clock — a cold boot before time-sync
  would otherwise pin the day to a bogus instant.
- **DST policy (the one explicit policy D6 required).** Datetimes are tz-aware; the
  schedule is generated on **local wall positions**, and the timeline advances by **real
  elapsed seconds** (the day-roll sleep uses real seconds-to-midnight — 23 h spring-forward,
  25 h fall-back, via `zoneinfo`). Consequence at the fold: the **fall-back repeated hour is
  not re-aired**, and the **spring-forward gap is skipped** — the broadcast simply tracks
  real time across the transition. No special re-airing or pause logic.

## 7. Content Organization & Catalog

- The station's `content_dir` contains one **subfolder per group** (`classical/`, `oldies/`, `radio_plays/`, …).
- On startup (and on demand), the **catalog scanner** walks the tree, reads tags via `mutagen`, and indexes each track tagged with its parent folder name. This mirrors FieldStation42's directory-as-tag approach.
- Track duration comes from metadata and is treated as exact for scheduling.
- **Runtime coherence.** The catalog is scanned at startup, but content can change out-of-band afterward. A persisted schedule item whose content file has **vanished or become corrupt by render time** is not a special case here — it is caught by the in-band render-poison/backstop policy in the producer (§9.3, §14): the item is backstopped and playback advances, never crashing the station.

**Offline tagging (separate tool).** Untagged or poorly tagged files are handled by a **standalone batch tool**, *not* at runtime. It uses Chromaprint (`fpcalc`) for acoustic fingerprints, `pyacoustid` for lookup, and `musicbrainzngs` for metadata — the engine underneath MusicBrainz Picard. Reasons it must be offline: fingerprinting is slow, and the MusicBrainz API requests ≤ 1 request/second, which four live stations would violate immediately. Tag once, ahead of time; the radio reads clean tags.

## 8. Scheduling

### 8.1 Two layers: Grid (template) vs Daily Schedule (instance)

- The **Grid** is authored by hand, FieldStation42-style: time-of-day → group. It is the *class*.
- The **Daily Schedule** is generated (at midnight, or on first start if absent) by filling the grid's slots with real tracks. It is the *instance* — and the only thing that costs nothing to build, because it touches catalog metadata only (no API calls).

### 8.2 Grid file format (example)

Grid files live in the station's `schedule_dir` (see §12). They are hand-authored YAML (JSON is also accepted if format uniformity with `config.json` is preferred; YAML is recommended for its comment support). Every slot carries `start`, `end`, `group`, and a required `name`, plus an optional `tagline` and `description`. **All three text fields are fed to the DJ's LLM as grounding** (see §9.2) — and the `description` can steer *delivery*, not just content, letting the same station persona shift register between blocks.

```yaml
# stations/pirate-one/weekday.yaml — slots must tile the full day, no gaps/overlaps
slots:
  - start: "00:00"
    end: "06:00"
    group: classical
    name: "Night Music"
    tagline: "The small hours, scored."
    description: >
      Quiet, spacious classical for the overnight — adagios and nocturnes,
      nothing that would startle a sleeper. The host speaks softly and rarely here.

  - start: "06:00"
    end: "09:00"
    group: oldies
    name: "Morning Oldies"
    tagline: "Start the day on the right record."
    description: >
      Upbeat oldies to wake the house. Brighter, chattier energy — the
      coffee-and-sunrise block.

  - start: "12:00"
    end: "13:00"
    group: radio_plays
    name: "Lunchtime Theater"
    tagline: "Stories over your sandwich."
    description: >
      A single vintage radio drama, played whole. Set the scene before, reflect
      briefly after, never talk over the piece.

  # ... remaining slots follow the same shape, tiling through 24:00
```

**Grid resolution by day-of-week.** The scheduler resolves which grid applies today by searching `schedule_dir` in priority order: an exact day file (`monday.yaml` … `sunday.yaml`) → `weekday.yaml` / `weekend.yaml` → `default.yaml`. Per-day grids are the intended model; a simple station can still ship only `default.yaml`. Seasonal programming is handled by manually swapping grid files in and out — not a built-in feature.

### 8.3 Validation (fail fast at load)

- Every `group` referenced by a grid must correspond to a non-empty content subfolder.
- Slots must tile 00:00 → 24:00 contiguously with no gaps or overlaps.
- Time formats parse; `start < end`.
- Every slot has a `name`; `tagline` and `description` are optional but recommended (when absent, the DJ falls back to the name).

A bad grid must fail loudly at startup, never silently at runtime.

### 8.4 Generation algorithm

For the selected grid, walk a cursor through each slot in time order:

1. **(§8.4.1)** Emit a `block_transition` item at the slot boundary.
2. **(§8.4.2)** While the cursor is within the slot, pick a track from the slot's group (weighted to avoid recent repeats) and append a `track` item with `planned_start = cursor`. **Stop when the remaining gap to the boundary is smaller than the shortest item in that block's pool** (i.e. nothing more can fit) — at which point the block ends and the next begins. The final placed track may run slightly past the boundary; soft boundaries absorb it.
3. **(§8.4.3)** Periodically emit a `block_reminder` within long slots.
4. **(§8.4.4)** Insert a `station_id` at the first item of each new clock-hour.

Each placed element advances the cursor by its own duration **plus the transition silence** (`transition_silence_seconds`, default 2.0) — the hard-cut gap between elements (see §10). That silence is part of timing and of the fill calculation.

Persist the result as `<state_dir>/<station>/<YYYY-MM-DD>.json`. *(Correction adopted during implementation per A6: generated schedules live under the writable `state_dir`, per-station, NOT under `schedule_dir` — that keeps mutable artifacts off the read-only/SD content path and separate from the hand-authored grids. The original `<schedule_dir>/generated/…` wording is superseded.)*

### 8.5 Soft boundaries & long-form content

- **Boundaries are fully soft** (v1 decision). A block ends when the remaining gap can't fit the shortest item in its pool (§8.4), so the edge floats by less than one item. No hard top-of-hour markers in v1.
- **Long-form items** (radio plays) are scheduled whole, never chopped. A tail left in the slot is **padded from the same group** — the §8.4 fill rule already does this, drawing more items from the block's pool until the shortest no longer fits.

### 8.6 Midnight regeneration

A coordinator-level task sleeps until the next midnight, then regenerates each station's schedule for the new day. The in-flight segment at the rollover is **not** interrupted; the player finishes it, then splices onto the new day's schedule at the next boundary. A regen failure in one station is logged CRITICAL and isolated — siblings still roll, and the failed station keeps today's schedule (a bad tomorrow-grid must not kill today at 00:00).

> *(Correction adopted during implementation, per `midnight.py`.)* The cross-day splice is **not seamless**. Only **schedule prewarm** is delivered — the new day's file is written **before** the day-roll Event is set (the file-then-event ordering), so the station re-slices onto a schedule already on disk. **Audio prewarm across the day boundary was NOT built**: rendering the new day's opening cluster during the outgoing day's final item would mean churning the frozen in-flight `run_once`, which is forbidden. So at the boundary the splice falls back to the **bounded R11 canned backstop** — the same one-cluster, one-refill-budget backstop as a cold start, **audible as a bumper** (not silence). The day boundary is therefore **backstop-covered, not warm-buffered**: it is explicitly carved out of R11's "deeper/warm buffer at block boundaries" guarantee.

### 8.7 Loading & reload behavior

- Grids are re-read at every regeneration, so editing *tomorrow's* grid today takes effect automatically at the next midnight roll (or via a manual `--regenerate`).
- Changes to `config.json` require a daemon restart in v1. A `SIGHUP`-triggered reload is a later nicety.

## 9. The AI DJ

### 9.1 Patter types

All are `ScheduleItem` kinds rendered just-in-time by the producer:

- **intro / outro** — announce a track before and recap after.
- **factoid** — a grounded aside about the track or artist.
- **block_transition** — closes one block, opens the next.
- **block_reminder** — periodic "you're listening to X, Y is up at \<time\>."
- **station_id** — once-per-clock-hour identification.

### 9.2 Grounding (anti-hallucination)

LLMs will confidently invent facts about obscure tracks. **Every patter prompt is grounded in real data**, assembled in three layers:

1. **Station persona** — the `dj_personality` from `config.json` (how the DJ talks; the constant character).
2. **Block context** — the current slot's `name`, `tagline`, and `description` (and, for transitions/reminders, the next slot's, plus its start time). The `description` can also steer delivery (e.g. "speaks softly here").
3. **Track metadata** — title, artist, album, year from the catalog.

The prompt instructs the model to speak in persona and to assert no facts beyond the supplied grounding. *(Per §21.7: grounding **reduces** fabrication of metadata facts but cannot fully eliminate tone/emphasis drift — treat it as a strong constraint, not a guarantee.)* Because the entire day is decided in advance, block announcements ("next up at noon, Lunchtime Theater") are always accurate — a direct payoff of pre-generating the schedule. The producer builds this grounding into a typed **`DjContext`** (R16, §13) and hands it to `TextGenerator.patter` — conceptually the payload below, for a `block_transition` (the shipped model uses typed `BlockContext`/`TrackMeta` sub-models rather than the bare JSON shown):

```json
{
  "kind": "block_transition",
  "persona": "A warm, unhurried late-night host...",
  "current_block": { "name": "Classical Morning", "tagline": "...", "description": "...", "ends_at": "12:00" },
  "next_block":    { "name": "Lunchtime Theater", "tagline": "Stories over your sandwich.", "description": "...", "starts_at": "12:00" },
  "recent_tracks": [ { "title": "...", "artist": "..." } ]
}
```

A per-station **DJ persona** (string or file, see §12) is the constant voice; the block `description` modulates it per block.

### 9.3 Provider failover & graceful degradation

The DJ must never cause dead air, so resilience is layered:

- **Ranked provider failover.** Both the LLM and TTS are configured as an *ordered* list of providers (§12). On a connection failure or quota/availability error, the system falls through to the next provider in the list. The LLM chain is **all network providers** — `Claude → DeepSeek → a self-hosted Ollama server on the LAN` (Ollama runs on a network host, **not** on the Pi; see §21/D2). For voice, local **Piper** on the Pi is the always-available floor. When *every* network LLM provider (including the LAN Ollama server) is unreachable, the true DJ-brain floor is **NullDJ / pre-rendered patter** (the final fallback below), and the canned-audio backstop (§21/R11) guarantees no dead air. A TTS fallback may change the station's voice — an acceptable degradation.
- **Best-effort patter on sparse metadata.** A track with incomplete tags is **not** skipped; the DJ generates best-effort patter from whatever metadata exists (and is still constrained not to assert facts beyond the grounding — the §9.2 grounding holds, just with less to work with; tone/emphasis drift can't be fully eliminated).
- **Final fallback.** If every provider in a chain fails, fall back to a pre-rendered generic intro, or play the track dry. This rule is mandatory throughout the pipeline.
- **Item-level render poison (backstopped in-band).** *(Correction adopted during implementation, per `pipeline/producer.py`.)* Beyond provider failover and the buffer-miss backstop, the producer backstops **any render exception per item, in-band**, and always advances to the next item — it never propagates the failure or crash-loops the station. A `ProviderError` is backstopped at **WARNING**; any other exception (a C-level decode crash on a corrupt file, `MemoryError`, a code bug) is backstopped at **CRITICAL**. This also covers a **missing or corrupt content file at render time** (the catalog is scanned at startup, so content can change out-of-band — see §7). There is **no skip path in the supervisor**: poison is handled entirely in-band, so an "unrenderable content item" can never escape to crash the process. A persistent station-tagged CRITICAL flood is the operator's signal to investigate.

## 10. Audio Pipeline

- **Decode:** `ffmpeg` (via `pydub` or direct subprocess) → NumPy sample buffers. (MP3/FLAC/etc. all route through ffmpeg.)
- **Output:** `sounddevice` (PortAudio), targeting a specific device by name/index — this is how each station claims its own USB dongle.
- **Loudness normalization:** normalize all elements (tracks *and* TTS) to a common target (EBU R128, e.g. via `pyloudnorm`, or ffmpeg `loudnorm`) so music and speech sit at consistent levels. Applied at the NumPy-buffer stage.
- **Transitions:** hard cuts, separated by a configurable minimum **transition silence** (`transition_silence_seconds`, default 2.0) between elements — a brief breath rather than a crossfade. No crossfading in v1.

## 11. Pluggable Backends (Interfaces)

Backends are swapped via structural-typed `Protocol` interfaces:

```python
from typing import Protocol

class TTSEngine(Protocol):
    async def synthesize(self, text: str) -> AudioBuffer: ...

class TextGenerator(Protocol):          # the "DJ brain"
    # the kind is carried by context.kind (R16); the bare `kind` param was removed (decision 0040).
    async def patter(self, context: DjContext | None) -> str: ...

class AudioSink(Protocol):
    async def play(self, buf: AudioBuffer) -> None: ...
```

*(Correction adopted during implementation: `patter` takes the typed `DjContext` (R16, §9.2), not a bare `dict`, and the separate `kind` argument was dropped — the item kind lives in `context.kind` (decision 0040).)*

**Error & threading contract (R15).** Every backend method raises a `ProviderError` (hierarchy: `ProviderUnavailable` / `ProviderQuotaExceeded` / `ProviderFatal`) on failure — failover retries only the retryable branch, and the pipeline catches any escape to fire the R11 backstop. Protocol docstrings state units, idempotency, and threading: **blocking native implementations MUST hop via `asyncio.to_thread`** so they never stall the shared event loop. `AudioSink` is additionally an **async context manager** — `__aenter__`/`__aexit__` open/tear down the device/stream, entered once per station lifetime.

Planned implementations:

- **TTS:** `PiperTTS` (local, primary — lightweight neural, runs well on ARM), `EspeakTTS` (retro/robotic fallback), `ElevenLabsTTS` (cloud).
- **TextGenerator:** `ClaudeDJ`, `DeepSeekDJ`, `OllamaDJ` (local), plus a `NullDJ` (no patter).
- **AudioSink:** `SoundDeviceSink` (primary).

## 12. Configuration

The daemon reads a single top-level **`config.json`**, validated with **Pydantic** (a typed, self-validating config — malformed config fails at startup, not at 3 a.m.). It separates **shared** settings (LLM/TTS provider credentials and the ranked provider order) from **per-station** settings (what makes each station unique).

```json
{
  "llm": {
    "providers": [
      { "backend": "claude",   "model": "<set to a current model id>", "api_key_env": "ANTHROPIC_API_KEY" },
      { "backend": "deepseek", "model": "<set to a current model id>",                "api_key_env": "DEEPSEEK_API_KEY" },
      { "backend": "ollama",   "model": "llama3.1",                     "endpoint": "http://ollama.lan:11434" }
    ]
  },
  "tts_providers": {
    "elevenlabs": { "api_key_env": "ELEVENLABS_API_KEY" },
    "piper": { "binary": "/usr/local/bin/piper", "voices_dir": "/opt/piper/voices" }
  },
  "stations": [
    {
      "name": "PiRate One",
      "tagline": "Free radio for the Pi-powered.",
      "description": "Eclectic overnight-to-morning mix with a calm, witty host.",
      "schedule_dir": "stations/pirate-one",
      "content_dir": "/library/pirate-one",
      "dj_personality": "A warm, unhurried late-night host with dry wit and a fondness for small asides.",
      "tts": [
        { "backend": "piper", "voice": "en_US-ryan-high", "speed": 1.0 }
      ],
      "audio_device": "USB Audio Device 1"
    },
    {
      "name": "PiRate Two",
      "schedule_dir": "stations/pirate-two",
      "content_dir": "/library/pirate-two",
      "dj_personality_file": "persona.md",
      "tts": [
        { "backend": "elevenlabs", "voice_id": "XXXX", "stability": 0.5, "similarity_boost": 0.75 },
        { "backend": "piper", "voice": "en_US-ryan-high", "speed": 1.0 }
      ],
      "audio_device": "USB Audio Device 2"
    }
  ]
}
```

Design choices, each easily reversed:

- **Secrets stay out of the file.** `api_key_env` names an environment variable rather than embedding the key, keeping `config.json` commit-safe and compatible with a SOPS/age workflow. Provider *credentials* live in `tts_providers`; *voice selection* is per-station.
- **Ranked provider failover.** `llm.providers` is an ordered list shared by all stations; each station's `tts` is its own ordered list. The system tries providers top-down and falls through on connection failure or quota/availability error (§9.3). Put local providers last (Ollama, Piper) as the always-available floor. Each station's `dj_personality` shapes whichever LLM provider is currently active.
- **Per-station LLM (optional).** If a station must use a *different* LLM than the shared list, give it its own `llm` block (resolves §16 #2).
- **Persona inline or file.** Short personas fit as a JSON string; longer ones use `dj_personality_file`, a path relative to the station's `schedule_dir`. Exactly one of the two must be set.
- **Station-level `name` (required), `tagline`, `description` (both optional)** — fed to the DJ for richer station IDs, mirroring the block-level fields.
- **TTS params are backend-specific** (Piper: `voice`, `speed`; ElevenLabs: `voice_id`, `stability`, `similarity_boost`; espeak: `voice`, `speed`, `pitch`). Validate against each entry's `backend`.

**Validation (fail fast at startup):** station `name`s unique; `audio_device`s distinct (error if two stations claim the same device); each `schedule_dir` exists and contains ≥ 1 valid grid; each `content_dir` exists and contains ≥ 1 non-empty group subfolder; exactly one of `dj_personality` / `dj_personality_file` per station; every referenced `*_env` variable is present in the environment.

## 13. Data Models (consolidated)

```python
class Track(BaseModel):
    path: Path
    group: str                # parent folder name
    duration: float           # seconds, from metadata (treated as exact)
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    year: int | None = None

class Slot(BaseModel):
    start: time
    end: time
    group: str                # must match a content subfolder
    name: str                 # block name (required); the DJ says it, the console shows it
    tagline: str | None = None     # short catchphrase, fed to the DJ
    description: str | None = None # longer context + delivery cues, fed to the DJ

class Grid(BaseModel):
    name: str
    slots: list[Slot]

# (Correction adopted during implementation, R17: ScheduleItem is a *discriminated union*
# on `kind`, not a single class with nullable fields — invalid states are unrepresentable.
# All variants share planned_start (tz-aware, D6) + duration + block_name; only TrackItem
# carries a Track. `dj_context` is NOT a stored field — it is the typed `DjContext` (R16,
# below) the producer builds at render time, never persisted. There is NO "bumper" kind:
# the canned backstop is a pre-rendered AudioBuffer, not a ScheduleItem.)

class _ItemBase(BaseModel):                 # frozen, extra="forbid"
    planned_start: datetime                 # tz-aware (D6); estimate for patter (R12)
    duration: float                         # content-only seconds; transition silence is separate
    block_name: str

class TrackItem(_ItemBase):
    kind: Literal["track"] = "track"
    track: Track                            # required -> a track item without a Track is impossible
    intro: bool = False
    outro: bool = False

class StationIdItem(_ItemBase):
    kind: Literal["station_id"] = "station_id"

class BlockTransitionItem(_ItemBase):
    kind: Literal["block_transition"] = "block_transition"
    next_block_name: str
    next_block_starts_at: datetime          # tz-aware

class BlockReminderItem(_ItemBase):
    kind: Literal["block_reminder"] = "block_reminder"

ScheduleItem = Annotated[
    TrackItem | StationIdItem | BlockTransitionItem | BlockReminderItem,
    Field(discriminator="kind"),
]

class DailySchedule(BaseModel):
    date: date
    station: str
    seed: int                               # the RNG seed used (R19 reproducibility record)
    items: tuple[ScheduleItem, ...]
    # persisted with a schema_version envelope (R17, SCHEDULE_SCHEMA_VERSION) by persistence.py

# The grounded patter context (R16, §9.2) — typed, frozen, built at render time, never persisted:
class TrackMeta(BaseModel):                  # title/artist/album/year, all optional (§9.3 sparse-ok)
    ...
class BlockContext(BaseModel):               # name (required) + tagline/description/boundary_at
    ...
class DjContext(BaseModel):
    kind: str                                # the patter type (§9.1)
    persona: str
    station_name: str
    station_tagline: str | None = None
    current_block: BlockContext
    next_block: BlockContext | None = None   # transitions/reminders only
    track: TrackMeta | None = None           # intro/outro/factoid only
    recent_tracks: tuple[TrackMeta, ...] = ()

class StationConfig(BaseModel):
    name: str
    tagline: str | None = None
    description: str | None = None
    schedule_dir: Path
    content_dir: Path                        # root of this station's group subfolders
    dj_personality: str | None = None        # inline persona prompt
    dj_personality_file: Path | None = None  # OR a path relative to schedule_dir (exactly one set)
    tts: tuple[TTSConfig, ...]               # R16: ranked discriminated union on `backend`
                                             #   = PiperTTSConfig | EspeakTTSConfig | ElevenLabsTTSConfig
    audio_device: str
    llm: LLMConfig | None = None             # optional per-station override (§12)
    transition_silence_seconds: float = 2.0  # hard-cut gap between elements
    loudness_target_lufs: float = -16.0      # le=0, ge=-40 (EBU R128)
    repeat_window_minutes: int = 120         # don't replay a track within this window

# R16: no bare dicts in the model layer — providers are discriminated unions on `backend`.
class LLMConfig(BaseModel):
    providers: tuple[LLMProviderConfig, ...]            # ClaudeLLMConfig | DeepSeekLLMConfig | OllamaLLMConfig
    request_timeout_seconds: float = 20.0              # per-call timeout -> failover (no rate limiter, see §12)

class DaemonConfig(BaseModel):
    llm: LLMConfig                                      # shared ranked chain (R16)
    tts_providers: dict[str, dict[str, object]] = {}    # raw on the wire; parsed once into typed
                                                        # TTSProviderConfig (Piper/Espeak/ElevenLabs) at validation
    state_dir: Path                                     # A6: mutable-state root off the boot SD
    decode_timeout_seconds: float = 120.0
    tts_timeout_seconds: float = 30.0
    stations: tuple[StationConfig, ...]
    control: ControlConfig | None = None               # Phase 6 / D4: None => control API off
```

## 14. Failure Handling & Resilience

- **Supervision:** crashed station tasks are restarted by the coordinator's supervisor.
- **Never dead air:** every generation step has a fallback path (§9.3).
- **Item-level render poison:** any render exception (not only `ProviderError`) is backstopped **in-band** by the producer (ProviderError → WARNING, anything else → CRITICAL) and the item advances; the supervisor has **no skip path** — poison never propagates or crash-loops a station. Covers a missing/corrupt content file discovered at render time (§9.3, §7).
- **Provider failover:** LLM and TTS each fail through a ranked provider list; local Ollama/Piper are the always-available floor.
- **Persistence:** all state is **flat JSON** — catalog, daily schedules, and resume state. Schedules are written to disk and read back on resume. (No database; kept deliberately simple.)
- **Quotas:** not designed around in v1. Quota exhaustion is handled *reactively* by provider failover rather than proactive budgeting. MusicBrainz (≤ 1 req/s) remains confined to the offline tagging tool.

## 15. Control API (in scope)

The daemon exposes a **RESTful API** (FastAPI) for inspection and control — the single-process architecture makes this clean, since one process owns all station state. Structured logs go to journald/stdout (§14, R8′); the `GET /logs` endpoint serves a **bounded in-memory ring** (RAM-only, lossy across restarts) for a live view, with journald as the durable archive (§21/R8′). Proposed endpoints:

| Method & path | Purpose |
|---|---|
| `GET /health` | Liveness/readiness. |
| `GET /stations` | List stations with current status (playing/stopped, current block). |
| `GET /stations/{name}/now` | Now playing: current item, block, and playback offset. |
| `GET /stations/{name}/schedule?date=YYYY-MM-DD` | The day's generated schedule (defaults to today). |
| `POST /stations/{name}/regenerate` | Rebuild today's schedule for the station. |
| `POST /stations/{name}/skip` | Skip at the **next** boundary: drop the next buffered item (one-shot). Cannot cut the currently-airing segment — that would break gaplessness. Returns `202 Accepted`. |
| `GET /logs?station=&level=&since=&limit=` | **Query logs** — filter by station, level, and time window. |

The API **binds to loopback (`127.0.0.1`) by default** and **bearer-token auth shipped in Phase 6** (see [`docs/ops/control-api.md`](docs/ops/control-api.md)); reach it over an SSH tunnel. A browser UI / phone remote on top of these endpoints is a later, optional layer — a thin client over this API.

## 16. Resolved Decisions

1. **Transitions:** hard cuts with a minimum **transition silence** between elements (`transition_silence_seconds`, default 2.0). No crossfade. (§10, §8.4)
2. **DJ personas:** one shared ranked LLM provider list, per-station `dj_personality` + per-station voice. A station may override with its own `llm` block. (§12)
3. **Boundaries:** fully soft. A block keeps drawing from its pool until the gap to the boundary is smaller than the shortest item in that pool. (§8.4)
4. **Long-form underfill:** pad from the same group (handled by the §8.4 fill rule).
5. **Grid variety:** per-day grids. Seasonal programming via manual grid swapping, not a built-in feature. (§8.2)
6. **Quotas:** not designed around in v1; exhaustion is caught reactively by provider failover. (§14)
7. **Provider selection:** ranked provider lists for both LLM and TTS; on connection failure or quota error, fall through to the next; local Ollama/Piper are the floor. (§9.3, §12)
8. **Persistence:** flat JSON for everything (catalog, schedules, state). (§14)
9. **Runtime metadata gaps:** best-effort patter — never skip the track. (§9.3)
10. **Observability:** a RESTful API, including a log-query endpoint. (§15)

## 16a. Resolved by review

- **Content directory:** **per-station libraries** (as drafted). Decided by the
  client (§21/D3); a shared content root remains a later option behind the same
  catalog interface. Repeat-window dedup scope stays per-station.

## 17. Risks

| Risk | Mitigation |
|---|---|
| LLM fabricates factoids | Strict metadata/schedule grounding; persona framing; optional `NullDJ`. |
| Native audio library crashes whole process | Clean station boundary; **systemd (R7) is the actual SIGSEGV recovery** (the in-process supervisor cannot catch one). Expect a **real refactor** if the native lib proves unstable enough to warrant subprocess isolation — not a drop-in promotion (R13). |
| Schedule drift over the day | Accept in v1; the timeline re-anchors from an exact start at each day-slice / regeneration (§6). No hourly re-anchor shipped. |
| Cloud API failure / quota exhaustion | Ranked provider failover; local Ollama/Piper as the always-available floor. |
| Slot/track misalignment | Fully soft boundaries by design; the fill rule keeps the gap under one item. |
| **Thermal throttling under sustained 24/7 load** | Sustained multi-core load (decode + loudness + Piper ×N, plus synchronized top-of-hour bursts) heats the SoC → CPU throttles → renders miss refill deadlines → the R11 backstop fires (audible bumpers). Mitigation: **active cooling** (required at the 4-station tier, §4.1) **+ the per-station render stagger** (`lookahead.stagger_offset`) so N stations don't fire renders on the same tick. |

## 18. Proposed Tech Stack

| Concern | Choice | Notes |
|---|---|---|
| Language / concurrency | Python 3.11+, `asyncio` | I/O-bound, cooperative loop |
| Config | Pydantic v2 | typed, fail-fast |
| CLI | Typer (or `argparse`) | |
| Audio output | `sounddevice` (PortAudio) | per-device targeting |
| Decode / resample | `ffmpeg` via `pydub` / subprocess | → NumPy buffers |
| Loudness | `pyloudnorm` or ffmpeg `loudnorm` | EBU R128 |
| Metadata | `mutagen` | ID3 / Vorbis / MP4 / FLAC |
| Offline tagging | `pyacoustid` + Chromaprint (`fpcalc`) + `musicbrainzngs` | separate batch tool |
| Local TTS | Piper (primary), espeak-ng (fallback) | ARM-friendly |
| Cloud TTS | ElevenLabs SDK | verify current SDK/API |
| LLM | Anthropic SDK / DeepSeek (OpenAI-compatible) / Ollama | pluggable; verify current models/SDKs |
| Persistence | Flat JSON files | catalog, schedules, state, logs |
| Control API | FastAPI | RESTful; log-query endpoint (§15) |

> Library/SDK versions and cloud API surfaces (ElevenLabs, Anthropic, DeepSeek) should be verified against current docs at implementation time.

## 19. Proposed Module Layout

> *(Correction adopted during implementation: this "Proposed" sketch is superseded — the shipped
> tree under `src/pirate_radio/` (src-layout) has grown well past it. The authoritative,
> up-to-date area map is [`docs/CODEMAP.md`](docs/CODEMAP.md); `src/pirate_radio/` is the ground
> truth.)*

The top-level shape: a daemon **spine** (`__main__.py`, `coordinator.py`, `station.py`,
`supervisor.py`, `midnight.py`, plus leaf utils) drives per-station **scheduling**
(`schedule/`, `lookahead.py`), the look-ahead render **pipeline** (`pipeline/`), the **AI DJ**
(`dj/`) and **audio** leaves (`audio/`); alongside sit the offline **tagger** (`tagging/`) and
the optional **control API** (`control/`). See [`docs/CODEMAP.md`](docs/CODEMAP.md) for the full
module-by-module map and the Protocol seams.

## 20. Implementation Roadmap

| Phase | Deliverable |
|---|---|
| **0 — Skeleton** | Config + validation (`config.json` + grids), catalog scanner, grid loader with full validation, flat-JSON state. |
| **1 — MVP vertical slice** | Single station: daily schedule generation (fill rule + transition silence), producer/player with a **stub TTS** (logs the announcements it *would* make), `sounddevice` output to a real device, `find_now` resume. Proves gapless playback + broadcast-time + scheduling. |
| **2 — Local voice** | Piper TTS, real intros/outros, loudness normalization, transition silence in the player. |
| **3 — AI DJ** | Grounded LLM patter, block transitions/reminders, station IDs, best-effort patter on sparse metadata; pluggable backends with **ranked provider failover** (LLM + TTS). |
| **4 — Multi-station** | Stations under the supervisor; full `config.json` with multiple stations; one audio device each. |
| **5 — Offline tagging** | The AcoustID/MusicBrainz batch tagger. |
| **6 — Control API** | FastAPI REST endpoints (stations, now-playing, schedule, regenerate, skip, **log query**). A browser UI / phone remote over the API is a later, optional layer. |

The guiding principle: Phase 1 proves the hard part (gapless playback through the look-ahead buffer, on a wall-clock schedule) with everything else stubbed. Each subsequent capability drops in behind a Protocol without rewiring the core.

---

## 21. Review Resolutions (Rev 2 — adopted 7–0)

The standing review panel reviewed this document over two rounds and adopted the
resolutions below unanimously. Full rationale and the vote record are in
`docs/decisions/0001-design-review-rev1.md` and `0002-design-review-rev2.md`.
Where a resolution conflicts with earlier prose above, **this section governs.**

### 21.1 Client decisions (binding)

- **D1 — Hardware target.** Target **Raspberry Pi 5 (4 GB)**; **Pi 4 (4 GB) is the
  4-station baseline**; **Pi 3 is a single-station / demo tier**. The design does
  **not** require 8 GB. Feasibility is gated by on-Pi compute = ffmpeg decode +
  loudness + Piper TTS ×N (LLM inference is off-box, see D2). **Stations-per-model
  guideline (F1, pending Phase-1 load test):** Pi 3 → 1 station (RAM-bound); Pi 4
  4 GB → 4 stations with medium-quality voices, staggered patter, active cooling;
  Pi 5 4 GB → 4 stations comfortably (recommended). *(Updates §1, §4.)*
- **D2 — LLM providers.** Support **Claude, DeepSeek Platform, and Ollama**, all as
  **ranked network providers** (`Claude → DeepSeek → Ollama`). **Ollama is a
  self-hosted server on the LAN, not on-Pi inference.** The on-Pi local floor is
  **Piper (voice)**; the ultimate DJ-brain fallback is **NullDJ / pre-rendered
  patter**. DeepSeek is in v1. *(Updates §9.3, §11, §12.)*
- **D3 — Content root.** **Per-station libraries.** *(Resolves §16a.)*
- **D4 — Control API in v1.** The **FastAPI REST control plane is in v1.** It must
  ship with a **consistent response/error envelope, documented status codes (incl.
  `404` for unknown `{name}`), and bearer-token auth** bound to the homelab
  network. A polished browser UI on top remains out of scope. In the roadmap it
  lands **after** the MVP vertical slice (after current Phase 1). *(Updates §2, §15, §20.)*
- **D5 — ElevenLabs is in v1.** Cloud TTS via ElevenLabs is a **core feature**, not
  a deferred extension. It ships as a ranked TTS provider alongside Piper (local
  floor) and espeak; this is purely "don't defer it" — it sits behind the existing
  `TTSEngine` Protocol with the per-station `tts` ranked list (§11/§12), so no
  structural change. *(Supersedes the ElevenLabs deferral note in §21.6/R22.)*
- **D6 — Use system time, assumed correct.** The daemon uses the **system local
  timezone** and **trusts the OS clock** — no hardware-RTC handling and no
  NTP/clock-step defensive logic. Datetimes remain **tz-aware** so `zoneinfo`
  handles DST transitions automatically; the only explicit policy still required is
  behavior at the DST fold (R9). *(Simplifies §21.2/R9.)*

### 21.2 Resilience & operations

- **R5 — Atomic durable writes.** All state (catalog, daily schedule, resume state)
  is written **temp → `fsync` → `os.replace()` → `fsync` parent dir**, keeping a
  `.bak` last-known-good. *(Updates §14.)*
- **R6 — Corruption recovery, no crash-loop.** On load, parse + Pydantic-validate;
  on failure fall back to `.bak`, else regenerate. Never crash-loop on bad
  persisted state. *(Updates §6, §14.)*
- **R7 — Two-tier supervision.** Ship a **`systemd` unit** (`Restart=on-failure`,
  `RestartSec`, `After=sound.target network-online.target`, optional
  `WatchdogSec`). systemd owns the **process** (and is the only thing that can
  recover a native **SIGSEGV** — the in-process supervisor cannot catch one); the
  in-process supervisor owns **tasks**. *(Updates §5.4, §14.)*
- **R8′ — Logging.** State stays flat JSON; **logs go to journald/stdout** (platform
  rotation/retention; off-box shipping available), transient writes to `tmpfs` to
  spare the SD card. *(Resolution amended — ratified deviation, decisions 0057/0062.)*
  The original wording ("`GET /logs` must be backed by a journald query or an indexed
  SQLite store — never a linear scan") is **superseded**. As shipped (`control/logs.py`),
  `GET /logs` is a **bounded in-memory ring** (`deque(maxlen=N)`) with a **PURE linear
  filter** over the snapshot. It is **RAM-only** (never touches the SD card, H26),
  **R23-safe** (no disk I/O in the handler), and **lossy across restarts and shallow**
  (last N records only). **journald remains the durable source of truth** for deep
  history (`journalctl`); the ring is a convenience/live view, not the archive.
  *(Updates §14, §15.)*
- **R9 — Timezone-aware clock + DST.** Use **tz-aware datetimes** throughout; define
  explicit behavior at the DST fold (spring gap / fall repeat) and on NTP/clock-set
  jumps. **Per client (D6): use the system local timezone and trust the system clock as correct — no RTC/clock-step defensive logic; tz-aware datetimes still let `zoneinfo` handle DST.** *(Updates §6.)*
- **R10 — Stable USB audio device naming.** Four identical USB dongles enumerate
  with identical PortAudio names and reorder across reboots. Require **stable ALSA
  names via udev rules keyed on physical USB port path**; config references those,
  not raw indices; §12 validation fails fast if 4 distinct physical ports can't be
  resolved. *(Updates §10, §12.)*

### 21.3 Broadcast-model correctness

- **R11 — "Never dead air" made real + `find_now` gap path.** Add a **guaranteed
  pre-rendered backstop** (canned bumper/silence) that plays the instant a buffer
  refill misses its deadline; state a **worst-case refill budget**; use a
  **deeper/warm buffer at block boundaries**. **Define the `find_now` `None`/gap
  path:** play the residual `transition_silence` gap as silence and advance to the
  next item's `planned_start` (or return next-item + wait rather than `None`).
  **Carve-out (per implementation, §8.6):** the **day boundary** is **not** warm-buffered —
  audio prewarm across midnight was not built, so the day-roll splice is covered by the
  bounded canned backstop (audible-as-bumper), the same as a cold start. *(Updates §5.3, §6, §8.4.)*
- **R12 — Bound schedule drift in v1.** Because `planned_start` for patter is an
  estimate, either **pull the hourly re-anchor into v1** or **re-anchor `find_now`
  on the nearest exact-duration track** (don't trust persisted estimated
  `planned_start`). Do not ship unbounded same-direction drift silently. *(Updates §6.)*
- **R13 — Subprocess claim + model name.** Downgrade the "promote player to
  subprocess without restructuring" claim (§5.4/§17) to "expect a real refactor if
  the native lib proves unstable," or prove it with a Phase-1 spike. Give the
  DeepSeek config example the same "set to a current model id" caveat as the
  Anthropic entry (`deepseek-chat` retires 2026-07-24). *(Updates §5.4, §12, §17.)*

### 21.4 Architecture & data models

- **R14 — `AudioBuffer` is a first-class model.** Add it to §13 with explicit
  `samples` (NumPy), `sample_rate`, `channels`; every pipeline stage produces a
  normalized buffer shape. *(Updates §11, §13.)*
- **R15 — Protocol error contract.** Define a hierarchy (`ProviderError` →
  `ProviderUnavailable` / `ProviderQuotaExceeded` / `ProviderFatal`); failover
  retries only the retryable branch. Protocols carry docstrings stating units,
  threading (which methods must go via `asyncio.to_thread`), and idempotency.
  *(Updates §11.)*
- **R16 — No bare `dict`s in the model layer.** Replace `dj_context`, `tts:
  list[dict]`, `llm`, `tts_providers` with **discriminated unions keyed on
  `backend`** (`PiperTTSConfig | ElevenLabsTTSConfig | EspeakTTSConfig`, …) and a
  typed `dj_context` model. *(Updates §12, §13.)*
- **R17 — `ScheduleItem` as a discriminated union on `kind`** so invalid states are
  unrepresentable; add a `schema_version` to persisted `DailySchedule`. *(Updates §13, §14.)*

### 21.5 Testability (design constraints)

- **R18 — Injectable clock** for `find_now`, the station loop, and midnight regen;
  never call `datetime.now()` internally. *(Updates §6, §8.6.)*
- **R19 — Seedable scheduler.** Inject `random.Random`/seed; **(catalog + grid +
  seed + clock) → byte-identical persisted `<date>.json`**. Recommend a
  date-derived seed (stable-but-varying days). *(Updates §8.4.)*
- **R20 — Thin hardware seam + coverage honesty.** Only the literal `sounddevice`
  call in `SoundDeviceSink` is `@pytest.mark.hardware`; decode/loudness/buffer/
  timing stay pure and off-device. Keep hardware-only code minimal and
  `pragma: no cover` (CI runs `-m "not hardware"` but `--cov-fail-under=80` is
  package-wide). Ship in-repo fakes (`FakeTTS`, `ScriptedDJ`,
  `FailingTTS`/`FailingDJ`, `FakeAudioSink`). *(Updates §10, §11.)*
- **R21 — Virtual-time pipeline & failover tests.** Test the producer/consumer with
  asyncio + fakes + injected clock (bounded queue depth, ordering, stall
  isolation); test failover with fakes only — zero network, no real SDK import on
  the test path. *(Updates §5.3, §9.3.)*

### 21.6 Scope / dependencies

- **R22 (amended).** Drop **`pydub`** (use the direct ffmpeg subprocess); pick
  **one** loudness path — **`pyloudnorm`** (pure-Python, unit-testable). LLM trio
  (Claude/DeepSeek/Ollama) is **in v1** (per D2). TTS: **Piper** (primary) +
  **espeak** (fallback) in v1; **ElevenLabs** is **in v1** as a core feature (D5), behind the same Protocol
  *(resolved — in v1 per D5)*. Offline-tagging stack stays a
  Phase-5 standalone tool. `Typer` vs stdlib `argparse`: recommend `argparse`
  unless the CLI grows. *(Updates §10, §18.)*
- **R23 — Non-blocking handlers.** The FastAPI control plane shares the audio event
  loop (§5.2). **All API and log-query handlers must be non-blocking; offload any
  synchronous I/O (e.g. `sqlite3`, file reads) via `asyncio.to_thread`** — a
  blocked loop starves the player and the R11 backstop alike. *(Updates §5.2, §15.)*

### 21.7 Accepted as-is (wording/notes only)

- Broadcast-time model (§6), Protocol backends + phased roadmap (§11/§20), fail-fast
  Pydantic config + secrets-via-env (§12) — endorsed. Secrets reach the daemon at
  boot via `EnvironmentFile=` (root-owned, 0600) or SOPS/age decrypt-on-start.
- Reactive quota handling (§14) is fine for a homelab; add a note that a metered
  cloud account should set a provider **spend cap**.
- Grounding (§9.2) reduces fabrication of metadata facts but can't prevent tone/
  emphasis drift — soften "invents no facts" accordingly.
- **RF legality.** Operating four FM transmitters is a **licensing/regulatory
  matter** (e.g. FCC Part 15 field-strength limits in the US; equivalents
  elsewhere) that the **deployer owns**. RF remains out of scope for the *code*,
  but the constraint is acknowledged here. *(Acknowledgment added to §4.1.)*

---

## Appendix A — Look-ahead RAM budget model

*(Documents the shipped model in `src/pirate_radio/lookahead.py`; referenced by §5.3, §13, and §21. The whole module is pure — no clock, IO, or hardware — and is wired by the coordinator at boot.)*

The producer renders **serially**, so the only thing that keeps it ahead of a short-patter cluster is a look-ahead buffer deep enough to pre-render the whole cluster **while the preceding multi-minute track plays** (the track masks the serial renders). The coordinator computes the coupled quantities once at boot from the resolved config + each station's schedule.

**Buffer cost.** Each look-ahead slot holds **one whole-track `float32` `AudioBuffer`** — about **11.5 MB per minute** (mono @ 48 kHz: `seconds × sample_rate × channels × 4 bytes`). Speech segments are far smaller; the budget is sized against the longest **track**.

**Buffer depth.** `depth = worst_consecutive_patter + 1` — the longest run of consecutive non-track items (a patter cluster), plus the one masking-track slot being consumed. The generator's realistic worst case is 2 (`block_transition` + `station_id` at a top-of-hour). An all-track schedule still needs depth 1. This `depth` is passed to the look-ahead queue (`run_once(maxsize=depth)`).

**Fixed RAM budget.** `LOOKAHEAD_RAM_BUDGET_BYTES ≈ 1.6 GB` (≈ 40% of a 4 GB Pi's total RAM, sized for the 4 GB / 4-station target). It is **deliberately a fixed constant, NOT a `psutil`-derived fraction of free RAM**: the boot result must be **byte-identical across reboots** so a config that fails fast at 3 a.m. fails the same way every time. No `psutil` dependency.

**Resident slack.** The budget covers `depth + _RESIDENT_SLACK_SLOTS` (**+2**) whole-track buffers **per station** — the queue **plus** the segment the player popped and is writing, **plus** the segment the producer finished and is blocked trying to `put`. So the boundary is honest, not optimistic by two tracks.

**Fail-fast, never clamp.** `resolve_lookahead_depth` returns the needed depth only if the fixed budget affords the real resident peak across **all** stations (`n_stations × (depth + slack) × worst_track_bytes ≤ budget`); otherwise it raises a `ConfigError` naming the fix (reduce stations, shorten the longest track, or raise the budget). A **silent clamp to an affordable-but-shallower depth is rejected** — a buffer shallower than the worst cluster can't pre-render it during the masking track, which would silently regress to a sustained R11 backstop loop (the C1 bug).

**Render stagger.** `stagger_offset(i) = i × 2.0 s` — a deterministic (no-RNG, reproducible) per-station initial render delay so N stations don't fire Piper/cloud renders on the same tick (the 4-core thundering herd at synchronized top-of-hour IDs). See the thermal-throttling risk in §17.

**Worst-case render.** `worst_case_patter_render = Σ LLM-chain timeouts + Σ TTS-chain timeouts` (a hung backend burns its full timeout before the ranked chain fails over); used to decide the cold-start startup WARNING.
