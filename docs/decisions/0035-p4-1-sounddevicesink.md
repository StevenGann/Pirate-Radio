# P4-1 — `audio/sink.py` `SoundDeviceSink` (R20: the only new Phase-4 hardware)

Strict spec-driven TDD: tests authored from the adopted Phase-4 plan §G / P4-1 → confirmed RED →
focused panel (QA + Senior Dev + DA) reviewed the TESTS → folded the must-fixes → implemented
GREEN → gate → commit. The first Phase-4 increment.

## Panel review of the tests (focused: QA + Senior Dev + Devil's Advocate)

**Round 1: QA NAY, Senior Dev AYE, DA NAY → 2 NAY, REVISE.** Both NAYs converged on real gaps:

- **DA CRITICAL — §10 "returns only when fully consumed" was untested** (a fire-and-forget impl
  passed). Added `test_play_blocks_until_write_completes` (a blocking-write fake + an Event: `play`
  must not return until the write is released).
- **DA HIGH — the xrun fake's name was fictional.** Real sounddevice raises `PortAudioError`, not
  `_PaOutputUnderflowed`; matching the fake name would recognize zero real xruns. Renamed the fake
  to `PortAudioError` (the real class, matched by name — no sd import) and strengthened the
  recover-vs-propagate guard.
- **QA + DA + Senior — "dedicated executor" was unproven** (`!= main` is satisfied by the shared
  default pool, the §G anti-goal). Added `test_writes_run_on_one_dedicated_worker_thread` (one
  stable worker ident across plays, distinct from a `asyncio.to_thread` default-pool ident).
- **DA HIGH + Senior obligation — thread leak on close untested.** Added
  `test_dedicated_executor_thread_joined_on_exit` (the worker is gone from `threading.enumerate()`
  after exit → `executor.shutdown(wait=True)`).
- **DA MEDIUM — coercion was tautological.** Added non-C-contiguous (sliced-view) → contiguous,
  sample-rate-mismatch rejection, and 0-frame no-op.

After folding, the tests pin the §G/Q9 contract precisely (16 tests).

## Implementation

`audio/sink.py`: `SoundDeviceSink` (AudioSink), an async context manager. A **persistent**
`sd.OutputStream` opened once (gapless, §10); `play` `await`s the write on a **dedicated
single-thread `ThreadPoolExecutor`** (isolated from the shared decode/normalize pool — RPi/DA-M1),
so it returns only when the buffer is fully consumed. A `PortAudioError` (xrun) is a **logged
glitch** — buffer dropped, stream recovered; any other error propagates (supervisor → advance-past-
poison). `__aexit__` stops+closes the stream and `shutdown(wait=True)`s the executor in `finally`
(no stream/thread leak under a crash-loop). Format guards: channel + sample-rate desync → ValueError,
`ascontiguousarray` before write, 0-frame no-op. R20: only the lazy `import sounddevice` +
`sd.OutputStream(...)` construction is `pragma: no cover`; R21: no module-scope sd import (ast guard).
`pyproject` adds `sounddevice>=0.4,<1` (+ the `libportaudio2` apt note) and the mypy missing-stub
override.

## Gate

ruff + ruff-format + mypy `--strict` clean (39 files); **583 tests** (+16), 98.51% coverage;
`audio/sink.py` 97% (only the defensive `__aexit__` None-guard branches uncovered; the sd
construct/write is pragma'd, R20). A `@pytest.mark.hardware` real-device smoke is deferred to land
with the coordinator wiring (no real device in CI).

## Next

P4-2: `UdevAudioDeviceResolver` (port-path keyed, PortAudio↔ALSA bridge) + `docs/ops/udev-audio.md`.
