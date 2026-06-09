# PiRate Radio — code map

A developer's area map of the ~64-file `src/pirate_radio/` tree: subsystem → key modules →
entry points → seams. Derived from the actual tree (`find src -name '*.py'`). The design
intent is in [`../PiRate_Radio_Design_Doc.md`](../PiRate_Radio_Design_Doc.md); this file is the
"where does X live" index.

## Composition root & seams

Everything is wired by an **inject-everything composition root**: `__main__.MainDeps` holds the
hardware/IO collaborators (sink factory, udev resolver, catalog/grid loaders, decoder, clock,
`asyncio.run`, the optional control-API builder). `main(argv, *, deps)` is fully unit-tested
with fakes; only `_prod_deps()` touches real hardware (and is `# pragma: no cover`).

The cross-layer **Protocol seams** (production impl ↔ in-test fake):

| Protocol | Defined in | Prod impl | Fake |
|---|---|---|---|
| `TextGenerator` | `dj/protocols.py` | `dj/text.py` (Claude/DeepSeek/Ollama) | `dj/fakes.py` (`ScriptedDJ`, `NullDJ`) |
| `TTSEngine` | `dj/protocols.py` | `dj/tts.py` (Piper/espeak/ElevenLabs) | `dj/fakes.py` (`StubTTS`) |
| `AudioSink` | `dj/protocols.py` | `audio/sink.py` (`SoundDeviceSink`) | `dj/fakes.py` (`FakeAudioSink`) |
| `Decoder` | `audio/decode.py` | `FfmpegDecoder` | `FakeDecoder` / `FailingDecoder` |
| `AudioDeviceResolver` | `audio_devices.py` | `UdevAudioDeviceResolver` | static fake |
| `Clock` | `clock.py` | system clock | injected fixed clock |
| `Sleeper` | `pipeline/timing.py` | real sleep | virtual-time sleeper |

## The daemon spine

The long-running daemon — supervision, shared services, day-roll.

- **`__main__.py`** — entry point (`python -m pirate_radio`). `main(argv, *, deps)`: logging-first,
  `--config`, `--log-level`, `--regenerate [station]` oneshot. Builds `MainDeps`, runs the
  coordinator (+ crash-isolated control API task).
- **`coordinator.py`** — builds shared services once (LLM-chain cache, per-station persona/TTS/
  catalog, one global audio format), wires the §A look-ahead budget over `lookahead.py`, owns the
  `StationStatus` registry + the "N/N ON AIR" summary, gathers supervisor + midnight + summary.
- **`station.py`** — the per-station `Supervisable`: load-or-generate today's schedule, anchor
  (resume), drive `play_day`, await the day-roll Event, re-slice. `skip_item` poison net.
- **`supervisor.py`** — in-process tier-2 supervision: restart-to-known-good, sibling isolation,
  consecutive-restart ceiling → escalate to the systemd tier; stamps CRASHED/RESTARTING (scrubbed).
- **`midnight.py`** — DST-correct `next_midnight` + `MidnightTask`: sleep-to-midnight, per-station
  isolated regen, file-then-event ordering (schedule prewarm).
- **`status.py`** — `StationStatus` (on_air vs airing_backstop) DTO.
- **`clock.py`** — the `Clock` seam + system-zone resolution (`PIRATE_RADIO_TZ` override, UTC-offset
  degrade WARNING).
- **Leaf utils:** `errors.py` (the error taxonomy), `scrub.py` (`scrub_secrets` for logs),
  `durability.py` (`write_bytes_durably`: temp + fsync + os.replace + dir fsync),
  `yeartag.py` (`parse_year`), `persistence.py` (atomic durable JSON read/write),
  `audio_devices.py` (the udev resolver Protocol + impl).

## Config, catalog, grid

The static inputs and their validation (fail-fast at boot).

- **`config.py`** — Pydantic config models + loader + §12 validation; `load_config(preflight=…)`.
  `ControlConfig` (optional, off by default), `LLMConfig`, `StationConfig`, `tts_providers`.
- **`catalog/`** — `scanner.py` (folder scan → tagged `Track`s, stable `(group, path)` sort),
  `metadata.py` (mutagen reads), `models.py` (`Track`), `cache.py` (mtime-cached catalog, A9).
- **`schedule/grid.py`** — `Slot`/`Grid` models + YAML loader + tiling validation.

## Scheduling & resume

Grid + catalog → a deterministic day; resume after a crash.

- **`schedule/generator.py`** — the §8.4 fill walk → `DailySchedule`, seedable (R19), clock-injected
  (R18). Drops a `station_id` at the first item of each new clock-hour.
- **`schedule/models.py`** — the `ScheduleItem` discriminated union (`TrackItem`/`StationIdItem`/
  `BlockTransitionItem`/`BlockReminderItem`) + `DailySchedule`.
- **`schedule/resume.py`** — `find_now` → `NowPlaying` (R11 gap path, R12 re-anchor).
- **`lookahead.py`** — PURE look-ahead budget math (the C1 fix): `worst_consecutive_patter`,
  `lookahead_depth`, `resolve_lookahead_depth` (FAIL-FAST `ConfigError`, never clamp),
  `stagger_offset`, `worst_case_patter_render`, `LOOKAHEAD_RAM_BUDGET_BYTES` (public; imported by
  the coordinator).

## The render pipeline

JIT render → look-ahead buffer → gapless audio out.

- **`pipeline/producer.py`** — JIT render: schedule item → `DjContext` → patter → TTS → decode →
  loudness-normalized assembled segment. The R11 backstop lives here (any render exception → bumper).
- **`pipeline/player.py`** — consumer: drains the buffer → the `AudioSink`, with the player-side gap
  backstop and §10 transition silence.
- **`pipeline/buffer.py`** — the bounded look-ahead queue + `run_once(maxsize=depth)` harness.
- **`pipeline/daily.py`** — `slice_from_now` (PURE) + `play_day` (R11 gap, seek-trim first track).
- **`pipeline/timing.py`** — the `Sleeper` seam (virtual-time testable).
- **`pipeline/segment.py`** — the assembled-segment type.

## Audio leaves

- **`audio/decode.py`** — `Decoder` Protocol + `FfmpegDecoder` (f32le @ station rate, H14 timeout).
- **`audio/loudness.py`** — EBU R128 normalization via pyloudnorm (pad-then-measure, clamp+WARN).
- **`audio/resample.py`** — `to_rate` via scipy `resample_poly`.
- **`audio/sink.py`** — `SoundDeviceSink` (persistent gapless stream, async CM lifecycle).
- **`audio/binaries.py`** — `resolve_binary` / `preflight_binaries` (startup fail-fast, §12).
- **`audio/buffer.py`** — the `AudioBuffer` type + `DEFAULT_SAMPLE_RATE`.

## The AI DJ + ranked failover

- **`dj/protocols.py`** — `TextGenerator` / `TTSEngine` / `AudioSink` Protocols.
- **`dj/context.py`** — `DjContext`/`BlockContext`/`TrackMeta` (R16; grounding inputs).
- **`dj/prompts.py`** — grounded "invent nothing" prompt templates (`_sanitize`, H26).
- **`dj/text.py`** — Claude/DeepSeek/Ollama text backends (lazy network import, R21).
- **`dj/tts.py`** — Piper/espeak/ElevenLabs TTS backends.
- **`dj/failover.py`** — the ranked-provider wrapper: tries each in series, skip-on-Fatal, a TOTAL
  floor that never crashes the producer.
- **`dj/build.py`** — the boot seam: ranked chains from config, `NullDJ` floor last.
- **`dj/_http.py`** — shared httpx POST/GET helpers (no cross-sibling imports).
- **`dj/text.py`/`tts.py`/`fakes.py`** — fakes (`ScriptedDJ`/`NullDJ`/`StubTTS`/`FakeAudioSink`) on CI.

## The offline tagger (standalone CLI)

`python -m pirate_radio.tagging` — independent of the broadcast daemon.

- **`tagging/__main__.py`** — CLI: `main(argv, *, deps)`, startup fail-fast preflight, broadcast WARN.
- **`tagging/tagger.py`** — `tag_library`: stable walk, per-file isolation, dry-run, `--limit`.
- **`tagging/clients.py`** — `RateLimiter` + `FpcalcFingerprinter` + shared `request_json`.
- **`tagging/selection.py`** — PURE `best_match` / `merge_tags` / `choose_best` (fill-not-overwrite).
- **`tagging/tag_writer.py`** — atomic `apply_tag_plan` (same-dir temp + fsync + os.replace).
- **`tagging/models.py`** — `Fingerprint`/`AcoustIdMatch`/`RecordingMetadata`/`TagPlan`.

## The control API (optional, off by default)

`control/` — a FastAPI control plane, loopback-bound + bearer-auth, crash-isolated from broadcast.

- **`control/server.py`** — `make_server` (no-bind, unit-testable) + `serve` (the real bind).
- **`control/api.py`** — `create_app`: §15 routes, bearer auth, `{success,data,error}` envelope.
- **`control/service.py`** — read paths (stations/now/schedule) + write actions (skip/regenerate).
- **`control/logs.py`** — `RingLogHandler` (bounded, locked, secret-scrubbed) + `query_logs`.
- **`control/models.py`** — the `ApiResponse{success,data,error}` envelope.
