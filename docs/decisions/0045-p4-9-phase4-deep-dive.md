# P4-9 — Phase-4 full-seven deep-dive + remediation (phase gate)

The mandated phase-gate review of the assembled Phase 4 (P4-1…P4-8 + the P4-9 housekeeping). Seven
persona agents (opus) reviewed the wired daemon against the adopted plan and the four documented
deviations.

## Panel result (round 1): CONFIRM ×2, CONCERNS ×5

- **CONFIRM:** QA Engineer (verified gate: 709 tests, 97.66%, ruff/mypy clean; two LOW test nits),
  Fact Checker (all gate numbers + symbols + the four deviations accurately documented; one LOW: the
  0043 "(9)" label vs 7 midnight tests).
- **CONCERNS:** Senior Dev, Devil's Advocate, RPi Expert, Old Man, Field Operator.

The reviewers ratified the four deviations on their merits — **in-band render-poison RATIFY**
(strictly safer than plan §C, no crash-loop, R11 held), **module split RATIFY** (clean pure-math
extraction), **deferred audio-buffer prewarm RATIFY** (the bound is honest; churning the frozen
`run_once` to chase it is rejected), **prod sink_factory** ratified *conditionally* — but surfaced
real defects the assembled-but-faked gate had hidden.

## Findings remediated (all CRITICAL/HIGH fixed; gate re-green; re-verified RESOLVED)

1. **[CRITICAL — Senior, DA] The real `SoundDeviceSink` was never entered.** It is an async context
   manager whose `__aenter__` starts the stream; nothing did `async with sink`, so on hardware every
   station would crash on its first `play()` → crash-loop → permanent dead air. Invisible because
   `FakeAudioSink` needed no `__aenter__`. **Fix:** `AudioSink` Protocol now declares
   `__aenter__`/`__aexit__`; `FakeAudioSink` implements them (`entered`/`exited` flags); `Station.run`
   wraps its loop in `async with self._sink:` (stream open for the station's lifetime). Test:
   `test_run_opens_the_sink_as_a_context_manager`.
2. **[HIGH — RPi] Prod sink_factory passed the udev port_path as PortAudio `device=`** (wrong
   namespace). **Fix:** new `UdevAudioDeviceResolver.device_index_for_port(port_id) -> int | None`
   (port_path → PortAudio index, None if absent/ambiguous); `_prod_deps` builds
   `SoundDeviceSink(device=index)` (int), failing loud if None; `SoundDeviceSink.device` widened to
   `str | int`. Tests: translation + ambiguity.
3. **[CRITICAL — Field-Op / HIGH — Old Man] StationStatus speculative surface + lying summary.**
   `AIRING_BACKSTOP`/`GAP` states and `current_item`/`last_transition_at` fields were never emitted;
   `CRASHED`/`RESTARTING` were never set (supervisor had no status handle). **Fix:** removed the
   unemittable states + unused fields (status is now exactly the emitted set); the **Supervisor takes
   `on_status`** and stamps `CRASHED`/`RESTARTING` with `restart_count` + a **scrubbed** `last_error`
   (coordinator passes `_record`); the producer's backstop/poison logs are now **station-tagged**
   (`station <name>: backstop fired` / `render-poison`) so degradation is greppable; first-boot.md
   step 8 points at the grep instead of the removed `airing_backstop`. Tests:
   `test_emits_crashed_and_restarting_status_to_the_registry`, the revised `test_status`.
4. **[HIGH/MEDIUM — Senior, DA, Old Man] Poison-skip dead code.** `Station.skip_item`/`_poisoned`
   were written-never-read while cited as a "net." **Fix:** removed them; the producer's in-band
   backstop is documented as the SOLE producer poison policy; the supervisor retains its **general**
   poison capability (documented as not Station-triggered, still exercised by its own suite).
5. **[HIGH — RPi] RAM peak undercount.** The budget used `depth × stations`; the real resident peak
   is `depth + 2` per station (queue + in-flight player + producer-blocked). **Fix:**
   `_RESIDENT_SLACK_SLOTS = 2`; `resolve_lookahead_depth` fail-fasts unless the budget affords
   `needed_depth + slack` per station. Test: `test_resolve_accounts_for_the_resident_slack_slots`.

LOWs also fixed: 0043 "(9)"→"(7)"; first-boot.md `sk-...`→`REPLACE_WITH_YOUR_KEY`; stale
`skip_item` docstrings. (LOW QA wall-clock-timed station tests left as-is — they match the existing
suite pattern; deferred.)

## Round 2 re-verification: RESOLVED ×3

Senior Dev, RPi Expert, and Field Operator (the CRITICAL/HIGH raisers) re-reviewed the fixes against
the code + tests and each returned **RESOLVED** — both of their findings fixed, no new CRITICAL/HIGH,
all gates green. Only a stale test-module docstring remained (LOW), now corrected.

## Final gate

ruff + ruff-format + mypy `--strict` clean (48 source files); **713 tests** pass
(`-m "not hardware and not network"`), 97.60% coverage. The 4 deviations are RATIFIED.

## Phase 4 status

**COMPLETE.** Multi-station coordinator, two-tier supervision, real audio sink + udev resolver,
DST-correct midnight day-roll, the C1 look-ahead budget, the systemd unit, the entrypoint, the
operator log vocabulary, and the first-boot runbook are built, reviewed, remediated, and green.
