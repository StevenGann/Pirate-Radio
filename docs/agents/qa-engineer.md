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
- _2026-06-07_ — Rev 1 distillation (0001) adopted 7-0; I voted AYE. R18-R21
  captured faithfully + bonus testability wins (R14 AudioBuffer, R15 error
  taxonomy, R16/R17 discriminated unions, R11/R12 find_now gap path, R22
  pyloudnorm). Rev 2 (0002): client put Control API in v1 (D4) + R8' (logs via
  journald/SQLite, not JSON scan). Confirmed FastAPI surface is testable in-process
  via TestClient + app.dependency_overrides, no network/hardware; adds to coverage
  numerator. Voted AYE. R18-R21 carry over unchanged.
- _2026-06-07_ — Phase 0 implementation plan review (docs/plans/phase-0-...).
  Strong TDD plan: RED tests precede every module, dependency-sorted impl order,
  real-mutagen-on-generated-WAVs (correct call — exercises the real tag-zoo
  fallback, not a lying mock), tmp_path everywhere, FixedClock rejects naive dt.
  R18 met (clock is the only now() source + injectable weekday in load_config).
  R20 met HONESTLY: zero hardware code this phase because R10's udev mechanism is
  deferred to Phase 4 behind a resolver seam (StaticAudioDeviceResolver in CI) —
  the *policy* is fully tested now. Durable testability rules I added this round:
  (a) crash-injection coverage for atomic-write (monkeypatch os.replace/os.fsync to
  raise mid-write, assert live-or-bak always valid + no .tmp leak) is REQUIRED, not
  buried prose — must be an explicit RED test in PR4. (b) every "skip+log
  unreadable" path (metadata None, scanner skip) must assert the WARNING was logged
  via caplog, not just that the file is absent — otherwise silent-swallow regresses.
  (c) determinism tests must compare across two *independent* scans of a mutated
  tree (add/remove a file), not just `scan()==scan()` on an identical tree.
  My positions on the plan's open Qs: Q1 value-object now (don't pre-optimize); Q2
  validate ALL present grids at load (catch broken saturday.yaml on Tuesday — fail
  fast is the whole point of §12); Q3 accept 00:00->00:00 as all-day pinned by test,
  but ALSO require an explicit zero-length / start==end!=00:00 rejection test.
- _2026-06-07_ — Phase 0 tests-first reviews (errors/clock/persistence/catalog/
  grid/config). Caught & blocked two real regressions: (1) persistence omitted a
  test forcing the parent-DIR fsync (R5 power-loss line) — a non-durable impl would
  pass; fixed via os.fsync spy + S_ISDIR check. (2) config regressed adopted A2 —
  used string-set resolver, never tested two names aliasing one physical port; fixed
  to resolve(name)->PortId distinctness. Also NAY'd grid tests for missing §8.3
  "time formats parse" coverage. Lesson logged: bare pytest.raises(SameError) is a
  weak fence; demand match= on the failure reason, and always test the ACTUAL
  contract line (dir-fsync, port-alias), not a proxy.
- _2026-06-07_ — Phase 1 plan review (docs/plans/phase-1-...). Hardest phase to
  test; plan is strong (Sleeper seam, FakeAudioSink, StubTTS/FakeDecoder, R19
  byte-identical headline test, find_now->typed NowPlaying). KEY TESTABILITY DEFECT:
  LookAheadBuffer.get uses asyncio.wait_for(q.get(), timeout) — a REAL wall-clock
  timeout — so the R11 backstop deadline is NOT routed through the Sleeper seam,
  contradicting R21 "zero wall-clock sleeps". The slow-producer->backstop test would
  either really wait refill_budget seconds or use a tiny timeout (flaky on loaded
  CI). The refill deadline MUST go through the injected Sleeper/clock, not
  asyncio.wait_for. Also flagged: virtual-time fakes need a documented determinism
  story (how does the player "wait" advance virtual time and wake the producer?) —
  asyncio.Queue + a hand-rolled VirtualSleeper don't compose automatically. Imposed
  requirements + positions in review. R19/R20 otherwise honest; only
  SoundDeviceSink.play is hardware+pragma.
