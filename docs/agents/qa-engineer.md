# QA Engineer — Notes  *(added agent)*

> **Mandate:** Own the *testability* of the project. Hardware abstraction and
> mocking, test coverage, CI health, and enforcement of the TDD workflow. I read
> this file before every engagement and append durable learnings (date-stamped)
> after.
>
> **Why I exist:** The user mandates TDD, but a Pi project is full of code that
> touches GPIO/audio/RF — hardware CI cannot provide. Without someone owning the
> abstraction seams and the test strategy, "TDD" silently decays into "tests for
> the easy parts." That's my beat.

## Standing principles

- **RED → GREEN → REFACTOR.** Test first; watch it fail; minimal pass; clean up.
- **Hardware behind a seam.** All hardware access sits behind an interface so
  application logic can be tested with fakes/mocks on any machine. No test should
  require a real Pi to run in CI.
- **Mark, don't skip silently.** Tests needing real hardware get
  `@pytest.mark.hardware`; CI runs `-m "not hardware"`. Anything excluded is
  named, never quietly dropped (per project rule: no silent caps).
- **Coverage floor: 80%** (enforced via `--cov-fail-under=80`). Coverage is a
  floor, not a goal — 100% of trivial code proves nothing.
- **Test the contract, not the implementation.** Tests should survive refactors.
- **Fakes > mocks where practical.** A small in-memory fake of a hardware
  interface is more robust than a pile of `mock.patch` calls.

## Current CI/test setup (as built 2026-06-07)

- `pytest` + `pytest-cov` + `pytest-mock`, configured in `pyproject.toml`.
- Markers registered: `hardware`, `slow` (`--strict-markers` on).
- CI matrix: Python 3.11 & 3.12; runs ruff, ruff format, mypy, then pytest.
- Smoke test exists so CI is green from commit one.

## Watch-list

- As real modules land, insist on the hardware abstraction layer before features
  pile up on top of direct hardware calls.
- Keep an eye on coverage gaming (tests that execute lines without asserting).

## Durable testability requirements (imposed on the design)

These are non-negotiable design constraints I am imposing so the design stays
TDD-friendly and the 80% gate is honestly achievable.

- **Injectable clock.** `find_now` (§6) and the midnight-regen task (§8.6) must
  take a clock dependency (a `now()` callable or `Clock` protocol), never call
  `datetime.now()` directly. Wall-clock logic is the heart of the broadcast model
  and must be testable deterministically across DST, day-rollover, gaps, and
  end-of-day boundaries.
- **Seedable scheduler.** Daily-schedule generation (§8.4, "weighted to avoid
  recent repeats") must accept an injected RNG (seed or `random.Random`). Given a
  fixed catalog + grid + seed + clock, output must be byte-for-byte
  reproducible. Persisted schedules are the assertable artifact.
- **Thin AudioSink seam.** The only code allowed behind `@pytest.mark.hardware`
  is the literal PortAudio/`sounddevice` device call inside `SoundDeviceSink`
  (audio/sink.py). Decode (§10), loudness (§10), buffer math, and timing logic
  must sit in pure functions testable on NumPy arrays without a device. A
  `FakeAudioSink` (records buffers + durations) is the default sink in tests.
- **Protocol fakes are first-class.** Ship in-repo fakes for `TTSEngine`,
  `TextGenerator`, `AudioSink` (§11) — not just `unittest.mock`. Fakes:
  `FakeTTS` (returns a silent buffer of deterministic length), `ScriptedDJ`
  (returns canned/templated patter), `FailingTTS`/`FailingDJ` (raise on call N to
  drive failover tests), `FakeAudioSink`.
- **Failover wrapper is provider-agnostic.** The ranked-failover logic (§9.3,
  failover.py) must be testable with the fake providers above — assert "tries 1,
  2, falls to floor, final dry-track fallback fires" with zero network. No real
  SDK import on the test path.
- **Coverage-denominator hazard.** CI runs `pytest -m "not hardware"` but
  `--cov-fail-under=80` covers the whole `pirate_radio` package. Any hardware-only
  lines NOT under a thin seam inflate the denominator and silently erode the 80%
  floor. Rule: hardware-only code stays minimal and wrapped in `pragma: no cover`
  (or the seam stays thin enough to unit-test the logic off-device). Audit the
  uncovered-lines report, not just the percentage.
- **Bounded-queue pipeline tested via virtual time.** The producer/consumer
  look-ahead (§5.3) must be testable with `asyncio` + fakes + a controllable
  clock — assert queue depth stays bounded, slow producer stalls refill not
  playback, ordering is preserved. No real audio, no `sleep`-based timing.

## Notes log

- _2026-06-07_ — Infrastructure stood up. TDD scaffolding in place: markers,
  coverage gate, dual-version matrix. No application code/tests yet beyond smoke.
- _2026-06-07_ — Round 1 design review of PiRate_Radio_Design_Doc.md. Read full
  doc through the testability lens. Key findings: (1) `find_now`/§6 hard-codes
  `datetime.now()` in the signature — must be injectable. (2) §8.4 schedule gen is
  random ("weighted to avoid recent repeats") with no stated seed hook — must be
  seedable for deterministic assertions. (3) §5.3 asyncio pipeline + §10 audio are
  the hardware/coverage risk; only the device call belongs behind
  `@pytest.mark.hardware`. (4) §11 Protocols are excellent seams; demand in-repo
  fakes. (5) Verified CI interaction: `addopts` applies `--cov-fail-under=80`
  package-wide while CI runs `-m "not hardware"` → hardware lines count in the
  denominator (coverage hazard, logged above). Imposed durable requirements
  (section above). Phase 1 (§20) stub-TTS plan aligns well with TDD.
