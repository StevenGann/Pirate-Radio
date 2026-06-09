# PiRate Radio

A Raspberry Pi + Python project: an automated, multi-station FM radio broadcaster
with an optional AI DJ. See [`PiRate_Radio_Design_Doc.md`](PiRate_Radio_Design_Doc.md)
for the full design (the panel-adopted §21 "Review Resolutions" govern).

> ⚠️ **Legality first.** Operating an FM transmitter is **regulated and often requires a
> licence**. In the US, unlicensed operation must stay within FCC Part 15 field-strength
> limits (very low power / short range); most jurisdictions have an equivalent rule. Higher
> power or multiple stations generally needs a licence. **Confirm what is legal for your
> band, power, and location before you transmit** — that is the operator's responsibility,
> not the software's. Wired / streaming-only use sidesteps RF entirely.

## Status

✅ **Phases 0–6 complete — a deployable multi-station broadcaster.** Blank Raspberry Pi to
"N/N ON AIR" via the [`docs/ops/first-boot.md`](docs/ops/first-boot.md) runbook. What exists:

- **Phase 0:** config + fail-fast validation, content catalog scanner, grid loader +
  validation, atomic durable JSON state, clock seam, error taxonomy, the R10
  audio-device-resolution seam.
- **Phase 1:** schedule data models, the `AudioBuffer` type, the provider-error taxonomy,
  DJ/audio Protocol seams + fakes, the seeded schedule **generator** (R19),
  `find_now`/**resume** (R11 gap path + R12 re-anchor), the look-ahead **playback pipeline**
  (R11 backstop, virtual-time-testable), the writable `state_dir` (A6), the mtime-cached
  catalog (A9).
- **Phase 2 (local voice):** real **ffmpeg decode**, **EBU R128 loudness** normalization
  (`pyloudnorm`), **Piper + espeak-ng** TTS behind the Protocols, scipy resampling, startup
  **binary preflight**, loudness-normalized gapless playback.
- **Phase 3 (the AI DJ):** a **grounded LLM → TTS** patter path — a typed `DjContext` (R16) →
  "invent nothing" prompts → **Claude / DeepSeek / Ollama** text backends, **ranked provider
  failover** for LLM and TTS (a *total* floor that never lets a backend bug crash the producer),
  **ElevenLabs** cloud TTS (D5). The network path is lazily imported and **never touched on the
  CI/test path** (R21).
- **Phase 4 (multi-station):** the **coordinator** (build-once shared services, look-ahead RAM
  fail-fast, deterministic render stagger), the **supervisor** (restart-to-known-good, sibling
  isolation, consecutive-restart ceiling → systemd), the real **`SoundDeviceSink`**, the **udev
  port→station resolver**, the **DST-correct midnight day-roll**, the `python -m pirate_radio`
  daemon + **systemd unit**, graceful SIGTERM shutdown.
- **Phase 5 (offline tagger):** an AcoustID/MusicBrainz batch tagger
  (`python -m pirate_radio.tagging`) — fingerprint → rate-limited lookups → thresholded
  fill-not-overwrite → atomic tag write, per-file isolation. No new Python dependency.
- **Phase 6 (control API):** an optional FastAPI control plane (off by default, loopback-bound,
  bearer-auth) — status reads + skip/regenerate + a bounded in-memory `/logs` ring,
  crash-isolated from the broadcast. See [`docs/ops/control-api.md`](docs/ops/control-api.md).

Live status and the build history are in [`docs/BUILD-LOG.md`](docs/BUILD-LOG.md).

## Configuration

The full `config.json` field reference (every key, default, and range) is in
[`docs/ops/config-reference.md`](docs/ops/config-reference.md); the content model (grids + content
folders) is in [`docs/ops/grids.md`](docs/ops/grids.md). Start from
[`config.example.json`](config.example.json).

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
- **Set a provider-side spend cap** on every metered cloud account (Anthropic, **DeepSeek**,
  ElevenLabs are all paid). Patter output is bounded by `_MAX_TOKENS = 256` per call and failover
  does **no in-place retry** (≤ chain-length calls per item), but a hard account-level cap is the
  real backstop against a runaway bill.
- **Per-call network timeouts** default to **20 s for every LLM backend** (`llm.request_timeout_seconds`,
  applied uniformly incl. Ollama) and **30 s for TTS** (`tts_timeout_seconds`); a hung call →
  fail-through → floor. **On a flaky link, order the chains local-first** (Piper before ElevenLabs;
  Ollama-on-LAN ahead of cloud) — failover tries providers *in series* with no global deadline, so
  a total-outage worst case for one patter item is the **sum** of its chain timeouts (~Σ ≈ 60 s LLM
  + 30 s TTS); local-first keeps that latency off the critical path.
- **Logging:** the daemon entrypoint (`python -m pirate_radio`) configures logging at startup
  (`configure_logging` + `--log-level`, default INFO); under systemd it goes to journald, so
  `journalctl -u pirate-radio` shows the full failover/degrade trail.

A **complete, copy-able** config lives at [`config.example.json`](config.example.json) (pure JSON —
`cp config.example.json config.json` and edit the `REPLACE-…` values + paths). Annotated excerpt of
the Phase-3-specific parts (ranked LLM + ranked TTS):

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

## Documentation

- **Runbooks** (`docs/ops/`): [`first-boot.md`](docs/ops/first-boot.md) → [`grids.md`](docs/ops/grids.md)
  → [`udev-audio.md`](docs/ops/udev-audio.md) → [`tagging.md`](docs/ops/tagging.md) →
  [`config-reference.md`](docs/ops/config-reference.md) → [`control-api.md`](docs/ops/control-api.md).
- **Design:** [`PiRate_Radio_Design_Doc.md`](PiRate_Radio_Design_Doc.md) (the panel-adopted §21
  "Review Resolutions" govern).
- **Developer area map:** [`docs/CODEMAP.md`](docs/CODEMAP.md) — subsystem → key modules → seams.
- **Testing philosophy:** [`docs/process/strict-tdd.md`](docs/process/strict-tdd.md).

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

Current gate: ruff + ruff-format + mypy `--strict` clean; the full `pytest` suite green with an
enforced **80% coverage floor** (~97%). CI runs
`-m "not hardware and not network"`: hardware-dependent code and the live LLM/TTS smokes are
excluded, and **no CI test imports a provider SDK or opens a socket** (R21) — the network path is
lazily imported and proven absent by import-guard tests.

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
design review, per-phase plans, and per-increment votes — is the full set under
[`docs/decisions/`](docs/decisions/) and
[`docs/agents/README.md`](docs/agents/README.md). Implementation plans live in
[`docs/plans/`](docs/plans/).
