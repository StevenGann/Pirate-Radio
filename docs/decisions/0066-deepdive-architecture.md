# 0066 — Deep-dive cycle 2 of 4: ARCHITECTURE review + remediation

Cycle 2 of the four dimension-specific deep-dives. A five-persona panel (Senior Dev, Old Man, RPi
Expert, Devil's Advocate, QA Engineer) reviewed the **architecture** — module boundaries, dependency
graph, seams/injection, data flow, and the single-loop concurrency model.

## Panel result: CONFIRM ×4, DISPUTE ×1 → remediated → re-poll

- **CONFIRM:** Senior Dev (graph acyclic + layered; scrub/supervisor inversion confirmed fixed; seams
  the right boundaries), Old Man (lean, boring, no speculative abstraction; Protocol seams earn their
  keep), RPi Expert (single-loop offload discipline genuinely clean; conditional on the pool +
  reslice fixes), QA Engineer (testable-by-construction; conditional on suite-wide socket + an
  assembled-whole test).
- **DISPUTE:** Devil's Advocate (CRITICAL: on-loop generate-under-lock breaks per-station failure
  isolation).

**Convergent top finding (Senior HIGH, RPi HIGH, DA CRITICAL):** the station's daily
`_load_or_generate` ran the full generate + fsync-heavy write **on the event loop** — the exact hazard
the midnight path was hardened against (0063), applied to only one of the two call sites. A
cold-start/restart/corrupt-fallback reslice would stall *every* station's sink, not just the
regenerating one.

## Remediation

1. **[CRITICAL/HIGH] Offload the station's daily load.** `Station` gains an injected `offload`
   (default `asyncio.to_thread`, threaded from the coordinator), and `run()` now does
   `await self._offload(self._load_or_generate, day)` under the regen lock — uniform with the midnight
   roll and API regenerate. Test: `test_run_offloads_the_daily_load_off_the_event_loop` (asserts the
   load ran via the seam). **This also resolves DA's "dual-`now()` day skew" HIGH:** the reslice
   always targets `clock.now().date()` (the actual current day) and any regenerate now runs off-loop,
   so even a pause-across-midnight airs the correct day with no loop stall.
2. **[HIGH] Bound the offload thread pool.** `_run_daemon` now installs an explicitly-sized default
   executor (`_offload_pool_size()` = CPU cores, min 2) instead of the stdlib `min(32, cpu+4)` — the
   architecture no longer leans on an *emergent* ≤cores bound it never enforced; the per-sink write
   executors stay separate so playback is never starved. Test: `test_offload_pool_size_is_core_bounded`.
3. **[HIGH] R21 is now a suite-wide invariant.** Added `--disable-socket` (+ `--allow-unix-socket`) to
   `addopts` so *every* test on the CI path is socket-blocked, not just one file; the `@pytest.mark.network`
   smokes re-enable real sockets via `enable_socket`. Convention → enforced invariant.
4. **[HIGH] Assembled-whole integration test.** `test_run_drives_the_real_supervisor_over_real_stations`
   runs the REAL supervisor over the REAL stations concurrently under `coord.run()` (only the
   peripheral midnight + summary loops stubbed), asserting both reach `ON_AIR` and open their sinks —
   closing the long-standing 0063 gap where the only `run()` test no-op'd all three loops.
5. **[MEDIUM] Coupling cleanups (Old Man).** Made the cross-module RAM-budget constant public
   (`LOOKAHEAD_RAM_BUDGET_BYTES`, was a `_`-private import); dropped the vestigial `scrub_secrets`
   re-export from the supervisor's `__all__` (callers use `pirate_radio.scrub`).

## Re-poll follow-up (DA CONFIRM + one new finding, fixed)

On re-verification the DA confirmed all prior findings closed (CRITICAL + HIGH genuinely remediated
with mutation-backed tests) and **VOTED CONFIRM**, but raised one new MEDIUM in the bounded-pool fix:
the core-sized pool also backs **I/O-bound** LLM/TTS waits (the sync Anthropic SDK + TTS via
`to_thread`), so on a 1-core Pi (2 workers) two slow-backend patter renders could hold both workers on
network waits and starve sibling decodes. Fixed immediately: `_offload_pool_size(n_stations)` now
returns `max(2, cores, n_stations + 2)` — enough for one in-flight offload per station (the
serial-per-station producer's max concurrency) plus headroom, floored at the core count so CPU work
still parallelizes; the CPU-bound members stay naturally ≈N (serial producers) while the extra slots
only ever hold no-core I/O waits. Test updated to `test_offload_pool_size_absorbs_per_station_io_plus_cores`.

## Carry-forward (non-blocking, recorded)

- **Full assembled-whole stop seam (QA HIGH).** The new integration test exercises supervisor+stations
  concurrently, but a clean virtual-time test that *also* drives the real midnight + summary loops to a
  quiescent point needs a cooperative `stop` seam on those `while True:` loops (a single sleeper can't
  serve both the player's instant-yield and the midnight sleep-to-midnight). Tracked for a focused
  test-infrastructure increment.
- **Midnight regen-failure parks a station ~24h (DA LOW):** on a per-station `prepare_next_day` failure
  the day-roll Event is (correctly) not set, so a station that already finished its day waits for the
  next midnight. Recoverable via restart; a self-heal (re-signal today's still-valid schedule) is the
  fix.
- **`run_once` layering inversion + `play_day` untyped `**kwargs` (Senior MEDIUM)** → code-quality cycle.
- **Decode transient RAM peak (RPi LOW)**; **Coordinator god-object trajectory (Senior LOW)** — noted.
- **TTS temp WAVs → `/tmp`:** mitigated at deploy by `PrivateTmp=yes` (0063); a configurable temp dir
  is the code-level follow-up.

## Outcome

The architecture was found sound by all five reviewers (acyclic layered graph, the right seams,
disciplined offload, clean failure isolation) — the one structural breach (on-loop generate-under-lock)
is fixed, making the offload seam uniform across all three schedule-generation paths. Gate: **875
tests** (+5), 97.58% coverage, ruff/ruff-format/mypy `--strict` clean (63 source files).
