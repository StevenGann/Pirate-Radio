# PiRate Radio

A Raspberry Pi + Python project: an automated, multi-station FM radio broadcaster
with an optional AI DJ. See [`PiRate_Radio_Design_Doc.md`](PiRate_Radio_Design_Doc.md)
for the full design (the panel-adopted §21 "Review Resolutions" govern).

## Status

🚧 **Phases 0–3 complete; building toward a deployable radio.** **Not yet a deployable
radio** — there is no coordinator/supervisor, no midnight-regeneration loop, and no real
audio output wired yet (those land in Phase 4). What exists today is the validated,
fully-tested foundation through the single-station MVP slice **plus the full AI DJ**:

- **Phase 0 — complete:** config + fail-fast validation, content catalog scanner,
  grid loader + validation, atomic durable JSON state, clock seam, error taxonomy,
  the R10 audio-device-resolution seam.
- **Phase 1 — complete:** schedule data models, the `AudioBuffer` type, the
  provider-error taxonomy, DJ/audio Protocol seams + fakes, the seeded schedule
  **generator** (R19), `find_now`/**resume** (R11 gap path + R12 re-anchor), the
  look-ahead **playback pipeline** (R11 backstop, virtual-time-testable), the writable
  `state_dir` (A6), and the mtime-cached catalog (A9).
- **Phase 2 — complete (local voice):** real **ffmpeg decode**, **EBU R128 loudness**
  normalization (`pyloudnorm`), **Piper + espeak-ng** TTS behind the existing Protocols,
  scipy resampling to one station format, startup **binary preflight**, and loudness-normalized
  gapless playback.
- **Phase 3 — complete (the AI DJ):** a **grounded LLM → TTS** patter path behind the unchanged
  Phase-1 Protocols — a typed `DjContext` (R16) → "invent nothing" prompts → **Claude / DeepSeek /
  Ollama** text backends, **ranked provider failover** for both LLM and TTS (skip-on-Fatal, a
  *total* floor that never lets a backend bug crash the producer), **ElevenLabs** cloud TTS (D5),
  and producer wiring that keeps the §9.3 "never dead air" floor (every track still plays; empty
  patter degrades to a template line; whole-chain exhaustion → the R11 backstop). The network path
  is lazily imported and **never touched on the CI/test path** (R21) — every backend's prompt-build,
  response-parse, error-map, and failover logic is fully unit-tested with fakes. Still **not a
  deployable radio** — the multi-station coordinator/supervisor, midnight regeneration, systemd
  units, and real audio output land in Phase 4.

Live status and the resume point are in [`docs/BUILD-LOG.md`](docs/BUILD-LOG.md).

## Configuration

Secrets and a couple of operational knobs come from the process environment — see
[`.env.example`](.env.example) for the full list. `config.json` references the credential
vars by *name* (e.g. `api_key_env`); a referenced var that is unset or empty fails fast at
startup. Notable optional knob:

- **`PIRATE_RADIO_TZ`** — IANA zone name (e.g. `America/New_York`) overriding the broadcast
  timezone. Normally unnecessary (the daemon resolves the system zone from `/etc/timezone`
  or `/etc/localtime`). Set it on a minimal/headless Pi with no zone configured — otherwise
  the clock degrades to a fixed UTC offset and **DST transitions are not tracked** (the
  daemon WARNs when this happens and names this variable as the fix).

### Phase 2 runtime prerequisites (system binaries)

Phase 2 (local voice) shells out to three **system binaries** — they are not pip-installed.
The daemon preflights them at startup (fail-fast, §12) and the error names the fix:

- **ffmpeg** — `apt install ffmpeg` (decode). Override the path with `ffmpeg_binary` in
  `config.json` if it is not on `PATH`.
- **espeak-ng** — `apt install espeak-ng` (fallback voice). Found on `PATH` by default.
- **piper** (primary voice) — **not** the Debian `piper` package (that is an unrelated mouse
  configurator). Download piper-TTS from <https://github.com/rhasspy/piper/releases>, then set
  `tts_providers.piper.binary` to its path (there is **no `PATH` fallback** for piper) and put
  each voice's `{voice}.onnx` in `tts_providers.piper.voices_dir`. **Keep `voices_dir` on fast
  storage (USB SSD / NVMe), not the boot SD** — piper reloads the model per call.

Annotated `config.json` excerpt for a Phase-2 station:

```jsonc
{
  "ffmpeg_binary": "/usr/bin/ffmpeg",        // optional; omit to use PATH
  "decode_timeout_seconds": 120,             // ffmpeg decode kill-switch (H14)
  "tts_timeout_seconds": 30,                 // piper/espeak kill-switch (H14)
  "tts_providers": {
    "piper":  { "binary": "/opt/piper/piper", "voices_dir": "/mnt/ssd/voices" },
    "espeak": { }                            // binary omitted -> resolved from PATH
  },
  "stations": [{
    "name": "PiRate One",
    "tts": [{ "backend": "piper", "voice": "en_US-ryan-high", "speed": 1.0 }],
    "loudness_target_lufs": -16.0            // EBU R128 target; range -40..0
    /* ... schedule_dir, content_dir, audio_device, dj_personality, ... */
  }]
}
```

### Phase 3 runtime prerequisites (the AI DJ — network)

The AI DJ reaches cloud/LAN providers over the network. Each backend is optional (ranked failover
falls through to the next, then to a template line, then to the canned backstop — never dead air),
but to actually hear LLM patter you need at least one working text backend and one TTS backend.

- **Credentials come from the environment, by name.** `config.json` references each via `api_key_env`
  (e.g. `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `ELEVENLABS_API_KEY`); a referenced var that is
  unset or empty **fails fast at startup**, naming the variable (never the value). Deliver them via
  `EnvironmentFile=` / SOPS (Phase 4 daemon), never in `config.json`.
- **Ollama runs on a LAN host, NOT on the Pi** (D2). Point `llm.providers[].endpoint` at it (e.g.
  `http://nas.local:11434`); the daemon validates the URL shape at boot. On-Pi LLM inference is out
  of scope (RAM/throughput).
- **Set a provider-side spend cap** on any metered cloud account (Anthropic / ElevenLabs). Patter
  output is bounded by `_MAX_TOKENS = 256` per call and failover does **no in-place retry** (≤ chain
  length calls per item), but a hard account-level cap is the real backstop against a runaway bill.
- **Per-call network timeouts** default to 20 s (LLM) / 30 s (Ollama + ElevenLabs) and are tunable
  via `llm.request_timeout_seconds` and `tts_timeout_seconds`; a hung call → fail-through → floor.

Annotated `config.json` excerpt for a Phase-3 station (ranked LLM + ranked TTS):

```jsonc
{
  "llm": {
    "request_timeout_seconds": 20,
    "providers": [                                   // ranked: tried in order, fall through on failure
      { "backend": "claude",   "model": "<current-claude-model>", "api_key_env": "ANTHROPIC_API_KEY" },
      { "backend": "deepseek", "model": "deepseek-chat",          "api_key_env": "DEEPSEEK_API_KEY" },
      { "backend": "ollama",   "model": "llama3", "endpoint": "http://nas.local:11434" }
    ]
  },
  "tts_providers": {
    "elevenlabs": { "api_key_env": "ELEVENLABS_API_KEY" },
    "piper":      { "binary": "/opt/piper/piper", "voices_dir": "/mnt/ssd/voices" }
  },
  "stations": [{
    "tts": [                                         // ranked: ElevenLabs first, Piper as the local floor
      { "backend": "elevenlabs", "voice_id": "<voice>" },
      { "backend": "piper",      "voice": "en_US-ryan-high" }
    ],
    "llm": { "providers": [ /* optional per-station override of the global llm */ ] }
    /* ... */
  }]
}
```

> **Verify the model ids** (`model`) against current vendor docs at deploy time — a retired model is
> a `config.json` edit, not a code change (the `model` is config, never hardcoded).

## Development

Requires **Python 3.11+**. The runtime targets **64-bit Raspberry Pi OS (arm64)
Bookworm** — `numpy`/`scipy` have no 32-bit (armhf) wheels, so a 32-bit image triggers a
slow source build. Runtime deps: `pydantic`, `mutagen`, `PyYAML`, `numpy`, plus (Phase 2)
`pyloudnorm` (pure-Python EBU R128) and `scipy` (resampling), plus (Phase 3) `anthropic`
(Claude SDK) and `httpx` (DeepSeek/Ollama/ElevenLabs). All ship `aarch64` cp311/cp312 wheels
(`anthropic` is pure-Python but pulls native `jiter`/`pydantic-core`, which publish prebuilt
arm64 wheels), so they install cleanly on **64-bit** Pi OS — a 32-bit image has no aarch64 wheels
and triggers slow source builds.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Quality gate (mirrors CI)
ruff check .
ruff format --check .
mypy
pytest -m "not hardware and not network"
```

Current gate: ruff + mypy clean, **566 tests**, ~99% coverage. CI runs `-m "not hardware and not
network"`: hardware-dependent code and the live LLM/TTS smokes are excluded, and **no CI test
imports a provider SDK or opens a socket** (R21) — the network path is lazily imported and proven
absent by import-guard tests.

### Testing philosophy

Strict **spec-driven TDD**: tests are authored from the spec and **reviewed by the
agent panel before any implementation exists**, then code is written to pass them
(see [`docs/process/strict-tdd.md`](docs/process/strict-tdd.md)). CI runs on Python
3.11 and 3.12 with an enforced **80% coverage floor**.

Hardware-dependent code (the real `SoundDeviceSink`, the udev device resolver) sits
behind Protocol seams and is marked `@pytest.mark.hardware`, excluded from CI, so the
logic is fully testable on any machine with fakes. The live LLM/TTS provider smokes are
marked `@pytest.mark.network` and likewise excluded — they skip without credentials and
exist only to validate the real wire shape on a deployment.

## Project governance

Design and implementation decisions are made by a standing seven-agent review panel
(brief → distill → vote) coordinated through a manager loop. The full audit trail —
design review, per-phase plans, and per-increment votes — is in
[`docs/decisions/`](docs/decisions/) (`0001`–`0031`) and
[`docs/agents/README.md`](docs/agents/README.md). Implementation plans live in
[`docs/plans/`](docs/plans/).
