# P4-3 — `supervisor.py` (R7 tier-2) + `status.py` + `PoisonItemError`

Strict spec-driven TDD: tests authored from the adopted Phase-4 plan §C / §status / P4-3 →
confirmed RED → focused panel (QA + Senior Dev + DA) reviewed the TESTS → folded the must-fixes →
implemented GREEN → gate → commit. The safety-critical heart of multi-station liveness.

## Panel review of the tests (focused: QA + Senior Dev + Devil's Advocate)

**Round 1: QA NAY, Senior Dev AYE, DA NAY → REVISE.** The DA exposed real holes that re-open the
C2 infinite-loop class; all folded:

- **G3 — a poison unit with no `skip_item` was undefined (infinite-loop risk).** Now it falls to
  the ceiling path → escalates within bounded attempts (`test_unskippable_poison_escalates_via_ceiling`).
- **G4 — unbounded poison-skips could starve forever** (a slow all-backstop loop, no alarm). Added a
  **bounded skip budget** (`max_skips`) → an all-poison schedule escalates
  (`test_skip_budget_exhaustion_escalates`).
- **G1 — per-index counting** (not a global counter): `test_poison_counting_is_per_index_not_global`
  (index 2 and index 5 each reach their own threshold; skip is keyed on the exception's `item_index`).
- **G5 — secret-scrub was a single Bearer pattern.** Replaced with a multi-pattern `scrub_secrets`
  (Bearer, `sk-…`, `xi-api-key`, `api_key`, `Authorization: Basic`, URL userinfo), parametrized test.
- **G2 — assert the CRITICAL-on-skip log** names the index; **G7 — CancelledError during backoff**
  propagates; **G8 — on_escalate raising isn't swallowed**.
- **QA — true concurrency** (`test_units_run_concurrently_not_serially`: a rendezvous that deadlocks
  a serial impl); sibling isolation; injected escalation seam (not a real exit).

**Design correction found during GREEN:** `asyncio.gather` converts a child's `SystemExit` →
`CancelledError` (asyncio quirk), so the prod escalation must NOT rely on `sys.exit()` propagating —
it must use **`os._exit()`** (immediate) or a shutdown signal. The supervisor also **stops
supervising the unit** after `on_escalate()` (returns), so even a no-op handler can't leave an
in-process loop. Documented on the class; the test pins "escalation stops the unit" + "a raising
handler propagates" rather than the (unachievable-through-gather) SystemExit propagation.

## Implementation

- `errors.py`: `PoisonItemError(item_index, cause)` — a `PirateRadioError` leaf **sibling to**
  `ProviderError` (a non-ProviderError render crash carrying the item index; the supervisor's skip key).
- `status.py`: `StationState` (StrEnum, incl. `on_air` vs `airing_backstop` — Field-Op) + frozen
  `StationStatus` (name/state/current_item/last_transition_at/restart_count/last_error). No DTO/HTTP (Q6).
- `supervisor.py`: `Supervisable` Protocol (`name` + `run`; `skip_item` optional); `scrub_secrets`
  (multi-pattern, PURE); `Supervisor` — per-unit `_supervise` under `asyncio.gather` (sibling
  isolation), restart-to-known-good + backoff (injected Sleeper), advance-past-poison keyed on the
  exception's item index with a bounded skip budget, consecutive-restart ceiling → injected
  `on_escalate` → stop; CancelledError never swallowed.

## Gate

ruff + ruff-format + mypy `--strict` clean (41 files); **622 tests** (+25), 98.55% coverage;
`supervisor.py` 99% (only the Protocol `...` branch uncovered), `status.py` 100%.

## Next

P4-4: `pipeline/daily.py` (slice_from_now + seek-with-offset-guard + gap silence) + `recent_tracks`
param threading.
