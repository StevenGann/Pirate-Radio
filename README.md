# PiRate Radio

A Raspberry Pi + Python project: an automated, multi-station FM radio broadcaster
with an optional AI DJ. See [`PiRate_Radio_Design_Doc.md`](PiRate_Radio_Design_Doc.md)
for the full design (the panel-adopted §21 "Review Resolutions" govern).

## Status

🚧 **In active construction (Phase 1).** **Not yet a deployable radio** — there is no
coordinator/supervisor, no midnight-regeneration loop, and no audio output wired yet
(those land in later phases). What exists today is the validated foundation:

- **Phase 0 — complete:** config + fail-fast validation, content catalog scanner,
  grid loader + validation, atomic durable JSON state, clock seam, error taxonomy,
  the R10 audio-device-resolution seam.
- **Phase 1 — in progress:** schedule data models, the `AudioBuffer` type, the
  provider-error taxonomy, and the DJ/audio Protocol seams + Phase-1 fakes.
  Remaining: schedule generator, `find_now`/resume, the look-ahead pipeline.

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

## Development

Requires **Python 3.11+**. The runtime targets **64-bit Raspberry Pi OS (arm64)
Bookworm** — `numpy` has no 32-bit (armhf) wheel, so a 32-bit image triggers a slow
source build. Runtime deps: `pydantic`, `mutagen`, `PyYAML`, `numpy`.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Quality gate (mirrors CI)
ruff check .
ruff format --check .
mypy
pytest -m "not hardware"
```

Current gate: ruff + mypy clean, **195 tests**, ~98% coverage.

### Testing philosophy

Strict **spec-driven TDD**: tests are authored from the spec and **reviewed by the
agent panel before any implementation exists**, then code is written to pass them
(see [`docs/process/strict-tdd.md`](docs/process/strict-tdd.md)). CI runs on Python
3.11 and 3.12 with an enforced **80% coverage floor**.

Hardware-dependent code (the real `SoundDeviceSink`, the udev device resolver) sits
behind Protocol seams and is marked `@pytest.mark.hardware`, excluded from CI, so the
logic is fully testable on any machine with fakes.

## Project governance

Design and implementation decisions are made by a standing seven-agent review panel
(brief → distill → vote) coordinated through a manager loop. The full audit trail —
design review, per-phase plans, and per-increment votes — is in
[`docs/decisions/`](docs/decisions/) (`0001`–`0010`) and
[`docs/agents/README.md`](docs/agents/README.md). Implementation plans live in
[`docs/plans/`](docs/plans/).
