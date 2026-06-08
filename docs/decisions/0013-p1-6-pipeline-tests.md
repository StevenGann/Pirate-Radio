# P1-6 — `pipeline/` (look-ahead producer/consumer: P1 no-drop, R11 backstop, P2/R21)

Strict spec-driven TDD: tests authored from plan §4.7-§4.8 / design §5.3+§10 → confirmed
RED → focused panel reviewed the tests → adopted → implemented to GREEN → gate → commit.

## Modules

`pipeline/timing.py` (Sleeper Protocol + RealSleeper/VirtualSleeper), `segment.py`
(RenderedSegment), `buffer.py` (LookAheadBuffer — bounded asyncio.Queue, back-pressure),
`producer.py` (render-ahead + announcement templates), `player.py` (drain + R11 backstop),
`__init__.py` (`run_once` harness). New test-support fakes: `FailingTTS` (dj/fakes.py),
`FailingDecoder` (audio/decode.py), both raising a configurable `ProviderError`.

## Panel review of the tests (focused 3-agent: QA + Senior Dev + Devil's Advocate)

**Round 1 — 3 NAY** (revise + re-vote). The convergent blockers were sharp:

- **DA — `AudioBuffer == AudioBuffer` raises `ValueError`.** AudioBuffer is a frozen
  dataclass over a numpy array, so `==` returns an ambiguous array. The `sink.played == [...]`
  assertions only "passed" because Python's list `==` short-circuits on identity — and
  would have *crashed* (not failed cleanly) against any impl that reconstructed a buffer.
  Fixed: all AudioBuffer comparisons use explicit `is` (also the correct R11 contract — the
  sink must receive the exact canned backstop object).
- **QA + Senior — the player test contradicted must-fix P1.** The original backstop test had
  the backstop *consume* a play slot (dropping the slow item). P1 requires the backstop be
  *gap-fill* and the real item still air. Rewrote to `test_backstop_gap_fills_then_late_item_still_plays`
  (asserts `played == [_BACKSTOP, real.audio]`) + `test_segment_arriving_within_first_budget_skips_the_backstop`.
  The player loop is now decoupled: a backstop never advances the item cursor.
- **QA + Senior — `FailingTTS`/`FailingDecoder` did not exist.** Added (raise
  `ProviderUnavailable`; error configurable so a `ProviderFatal` test proves the producer
  catches the *base* `ProviderError`).
- **QA + DA — VirtualSleeper yield contract unpinned.** A pure-no-op sleeper would starve
  the producer and fire spurious backstops. Pinned by `test_virtual_sleeper_yields_to_the_event_loop`;
  impl does `await asyncio.sleep(0)`.
- **Senior — `run_once` scope.** DECISION: `run_once` is the producer+player harness over a
  *pre-selected* item list for P1-6; the `DailySchedule → find_now → run_once` daily slice is
  the coordinator's job (Phase 4). Documented in `pipeline/__init__.py`.

**Round 2 — QA AYE, Senior AYE, DA AYE → 3 AYE / 0 NAY → ADOPTED.** Non-blocking notes
folded in: a "no WARNING fired" assertion on the no-drop integration test (proves no
spurious backstop regardless of cooperative-scheduling order), and a test covering the
`announcement_text` TrackItem guard.

## Key design decisions

- **Player loop (P1 + R11):** `get_nowait → if None: sleep(budget) → recheck → while still
  None: play backstop (gap-fill) + sleep + recheck → then play the real item`. Backstops fill
  air during an underrun; the item cursor advances only on a real segment, so nothing is
  dropped. Fast path (buffer non-empty) sleeps zero. Contract: `run(count=N)` requires the
  producer to deliver N segments (it always does — it substitutes a backstop on
  ProviderError), so the loop terminates.
- **Two R11 paths, kept distinct:** producer-substitution (a render `ProviderError` → backstop
  *segment* enqueued, counts as the item) vs player-timeout (queue empty at play time →
  backstop *gap-fill*, does not count). Tested separately.
- **Sleeper seam over `asyncio.wait_for` (P2/R21):** the player owns the refill deadline via
  the injected Sleeper (non-blocking `get_nowait` + `sleep`), so the deadline runs in virtual
  time. `asyncio.wait_for`'s timeout uses the loop's wall-clock and is not injectable — the
  seam is both more testable and gives a zero-latency fast path.
- **Trailing transition silence after the last element is intentional** — mirrors the
  generator's per-item `duration + silence` cursor budgeting.
- **`maxsize == len(items)` in the no-drop integration test** is documented load-bearing
  scaffolding (producer never blocks → no interleave → no spurious backstop); back-pressure
  itself is covered in `test_buffer`.

## Carry-forward

- The committed golden-JSON cross-run determinism guard (P5) is still pending — fold into P1-8.
- A per-test asyncio timeout (so a non-conformant impl surfaces as a clean failure rather than
  a hang) is a nice-to-have (DA note); deferred (no new dep added now).

## Gate

ruff + ruff-format + mypy clean; **250 tests**, 98.54% coverage; pipeline modules ~100%.
