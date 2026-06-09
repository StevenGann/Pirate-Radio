# PiRate Radio — `config.json` reference

Every field the daemon reads, with defaults and valid ranges. Start from
[`config.example.json`](../../config.example.json). Config is **fail-fast**: an unknown key, a missing
required field, an out-of-range value, an unset credential var, or an unresolvable `audio_device` all
stop the daemon at startup with an error that names the fix (never a silent default).

Secrets are **never** in this file — credentials are referenced by environment-variable *name*
(`api_key_env` / `token_env`) and read from the `EnvironmentFile`. See [`first-boot.md`](first-boot.md)
§4 and [`.env.example`](../../.env.example).

## Top level (daemon)

| Field | Required | Default | Notes |
|---|---|---|---|
| `state_dir` | yes | — | Mutable-state root (generated schedules) — keep **off the boot SD** (A6); must equal the systemd `StateDirectory`. |
| `stations` | yes | — | ≥1 station object (below). |
| `llm` | yes | — | Default LLM config (per-station `llm` can override). |
| `tts_providers` | no | `{}` | Shared TTS backend setup (`piper`/`espeak`/`elevenlabs` → their params). |
| `ffmpeg_binary` | no | from `PATH` | Absolute path to ffmpeg if not on `PATH`. |
| `decode_timeout_seconds` | no | `120` | >0. Per-track decode timeout (H14). |
| `tts_timeout_seconds` | no | `30` | >0. Per-render TTS timeout (H14). |
| `control` | no | *(absent ⇒ off)* | The control API block — see below + [`control-api.md`](control-api.md). |

## `llm`

| Field | Required | Default | Notes |
|---|---|---|---|
| `providers` | yes | — | ≥1 provider, **ranked**: tried in order, failover on error. Each is `claude` / `deepseek` / `ollama` (discriminated on `backend`), with `model` and either `api_key_env` (cloud) or `endpoint` (ollama). |
| `request_timeout_seconds` | no | `20` | >0. |
| `max_requests_per_minute` | no | `20` | >0. **Reserved — not yet enforced**; nothing throttles on it today. |

## Each `stations[]` entry

| Field | Required | Default | Notes |
|---|---|---|---|
| `name` | yes | — | Unique station name (used in logs / status). |
| `schedule_dir` | yes | — | Where this station's grid YAML files live — see [`grids.md`](grids.md). |
| `content_dir` | yes | — | Root of this station's content; top-level subfolders = groups — see [`grids.md`](grids.md). |
| `audio_device` | yes | — | The udev-assigned ALSA id (e.g. `pirate1`) — see [`udev-audio.md`](udev-audio.md). Must resolve to a present device. |
| `tts` | yes | — | ≥1 TTS backend, **ranked** (failover order): `piper` / `espeak` / `elevenlabs`. |
| `dj_personality` **or** `dj_personality_file` | exactly one | — | The DJ persona prompt, inline or from a file (path resolved relative to `schedule_dir`). Setting both, or neither, is rejected. |
| `tagline` | no | `null` | Short station blurb (used in patter context). |
| `description` | no | `null` | Longer station description. |
| `llm` | no | inherits top-level | Optional per-station LLM override. |
| `loudness_target_lufs` | no | `-16.0` | Range −40.0…0.0. EBU R128 target. |
| `transition_silence_seconds` | no | `2.0` | ≥0. Hard-cut gap between elements. |
| `repeat_window_minutes` | no | `120` | ≥0. Recently-played tracks are down-weighted within this window. |

## `control` (optional API)

| Field | Default | Notes |
|---|---|---|
| `enabled` | `true` | Present-but-`false` keeps it off. An **absent** `control` block is the true off-by-default. |
| `host` | `127.0.0.1` | Loopback by default — **never `0.0.0.0`** without intent (use an SSH tunnel). |
| `port` | `8080` | 1…65535. |
| `token_env` | `PIRATE_API_TOKEN` | Env-var **name** holding the bearer token. |
| `log_ring_size` | `2000` | 1…100000. The bounded in-memory `/logs` ring. |

See [`control-api.md`](control-api.md) for the full control-plane runbook.
