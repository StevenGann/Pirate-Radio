# P4-6b — `coordinator.py` (shared services, §A budget wired, status registry)

Strict spec-driven TDD; per the documented efficiency stance (0038), this integration-glue increment
folds the prior-panel lessons directly and relies on the **P4-9 full-seven deep-dive** as the quality
backstop (the algorithmic risk — the C1 budget math — was already panel-reviewed in P4-6a/0041).

## Implementation (`coordinator.py`)

- `Coordinator(*, config, clock, resolver, sleeper, sink_factory, on_escalate=None, catalog_loader=
  None, grid_loader=None, decoder_factory=None, summary_period_seconds=60, ram_budget_bytes=…)`.
  The heavy seams (catalog scan, grid load, decoder, sink) are **injected** (defaults wire the real
  ones) so the wiring is tested with fakes only — **no hardware, no `sounddevice` import** (R21).
- **Build-once (§5.1):** per station resolve the LLM (`resolve_station_llm`) and build the ranked
  text chain **cached by the resolved LLM *value*** (a `dict[LLMConfig, RankedTextGenerator]`; frozen
  Pydantic models are value-hashable) so stations with identical LLM settings share ONE chain;
  `resolve_persona`; `build_tts_engine`; catalog via the loader; one pre-normalized silence backstop.
  All audio is the **one global format** (`DEFAULT_SAMPLE_RATE`, mono) so decoder/TTS/backstop/station
  agree by construction (Q7).
- **§A budget (over `lookahead.py`, P4-6a):** generate each station's schedule once (in-memory, for
  measurement only — the Station persists its own on its load-or-generate path) → `lookahead_depth`;
  global `needed = max`; `worst_track_seconds = max` track duration across catalogs; `resolve_
  lookahead_depth(...)` → `self.depth` (**FAIL-FAST `ConfigError`** if RAM can't afford the cluster,
  not a clamp). The depth is threaded to each `Station(maxsize=self.depth)` → `run_once(maxsize)`.
- **Stagger:** each Station gets `start_delay_seconds=stagger_offset(index)` (deterministic, no RNG);
  the Station sleeps it once before its first render (a small P4-5 Station addition).
- **Cold-start WARNING:** if `worst_case_patter_render` (Σ chain timeouts) > the shortest opening
  patter item, log a startup WARNING naming the irreducible one-render cold-start residual (R11).
- **StationStatus registry + summary:** each Station's `on_status` updates `self.registry`; `_log_
  summary()` logs "N/N ON AIR — …" (answerable from journald alone, no HTTP). `run()` gathers
  `supervisor.run(stations)` + the summary loop; the `Supervisor` (P4-3) is built internally with
  `on_escalate` defaulting to `os._exit(1)` (the P4-3 finding: a `SystemExit` inside `gather` becomes
  a swallowed `CancelledError`, so only `os._exit` ends the process for the systemd tier).

## Deviations from plan (for P4-9 ratification)

1. **Module split** (continued from 0041): the §A math lives in `lookahead.py`; the coordinator
   orchestrates over it. Keeps both files under the 400-line ceiling.
2. **Day-roll prewarm + midnight deferred to P4-7.** The plan's §D `run()` gathers `supervisor` +
   `midnight`, and the §A prewarm renders the next day's opening cluster during the outgoing day's
   final item. Both require the day-roll `asyncio.Event` that the **midnight** task (P4-7) sets, so
   they are untestable here. P4-6b ships everything else; P4-7 adds the midnight task to `run()` and
   the prewarm. Documented; `coordinator.py`'s docstring states it.
3. **Test fix, not impl fix:** the first draft's `distinct-LLM` test wrongly used value-equal LLMs;
   the cache *correctly* shares a chain for value-identical LLMs (the §5.1 intent), so the test was
   corrected to use distinct-valued LLMs (different model). The implementation behaviour is right.

## Tests (`tests/test_coordinator.py`, 14)

one-station-per-config; shared-chain reuse (identical LLM) vs distinct chain (distinct LLM); real
persona supplied; depth = worst cluster + 1 (3) threaded to `Station.maxsize`; RAM fail-fast
`ConfigError`; deterministic stagger (0, step); cold-start WARNING (caplog); one-format wiring
(decoder/backstop/station); `sink_factory` called with each resolved `PortId`; unresolvable device →
`ConfigError` (R10); registry seeded; summary "1/2 ON AIR" (caplog); `run()` supervises all stations.
Plus the P4-5 Station stagger addition (`start_delay_seconds`, slept once before the loop).

## Gate

ruff + ruff-format + mypy `--strict` clean (45 source files); **683 tests** (+14), 98.33% coverage.

## Next

P4-7: `midnight.py` (next_midnight DST-correct, per-station isolated regen, file-then-event, straddle,
day-roll prewarm) — and wire midnight + prewarm into `Coordinator.run()`.
