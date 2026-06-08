# P1-4 — `schedule/generator.py` (§8.4 fill rule + R19 seedable)

Strict spec-driven TDD: tests authored from §8.4 / plan §4.5 → confirmed RED → focused
panel reviewed the **tests** → adopted → implemented to GREEN → gate → commit.

## Panel review of the tests (focused 3-agent: QA + Senior Dev + Devil's Advocate)

**Round 1 — 3 NAY** (revise + re-vote, per charter ≥2 NAY). Findings:
- **BLOCKER (all three):** `_station()` test builder omitted the required `tts` field → every
  test died at fixture construction (a `ValidationError`, i.e. the wrong RED).
- **BLOCKER (DA/Senior/QA):** `BlockTransitionItem.duration` was an unspecified constant; the
  station_id placement test over-coupled to it (`hours[:3]==[0,1,2]` only holds for a small
  transition duration).
- **MAJOR (QA):** the soft-boundary test couldn't distinguish the §8.5 soft stop from a hard
  cutoff.
- **MAJOR (DA):** the repeat-window test proved the window isn't ignored but not that the
  down-weight is *soft* (a track may still recur).
- Plus MINORs: `_transition` open/close `block_name` semantics undocumented; a probabilistic
  saturated-pool assertion; PYTHONHASHSEED note.

**Revisions:** added the `tts` field; imported and pinned the H1 constants
(`_BLOCK_TRANSITION_SECONDS`, `_STATION_ID_SECONDS==5.0`, `_BLOCK_REMINDER_SECONDS==8.0`);
replaced the brittle station_id oracle with `hours[0]==0` + `len>=3` + ascending + unique;
documented and asserted the open/close `block_name` convention; added
`test_recently_played_track_still_recurs_within_window` (pigeonhole: 10 tracks can't fill 24h
without a repeat) for the soft half of H2; de-randomized the saturated-pool test to a
completion/non-crash assertion.

**Round 2 — QA AYE, Senior Dev AYE, DA NAY → 2 AYE / 1 NAY → ADOPTED** (charter: ≤1 NAY adopts).
The DA's NAY carried two sharp points, both honored regardless of the tally:
- **BLOCKER-A** — the (round-1-suggested) "last item ends *past* the boundary" assertion is
  **false for a correct impl** (the DA simulated seed=3/seed=4: the last track ends ~4 min
  *before* the boundary; overflow is not guaranteed by the `>= shortest` stop rule). This had
  already been replaced, before the DA's verdict landed, with the **guaranteed** invariant
  `residual_gap < shortest + silence` — which is exactly the DA's recommended fix and is what
  the stop rule actually guarantees.
- **BLOCKER-B** — the pinned bound `0 < _BLOCK_TRANSITION_SECONDS < 120` was looser than the
  station_id test tolerates (per-hour drift = station_id + reminder seconds). Tightened to the
  real relationship: `_BLOCK_TRANSITION_SECONDS + 2*(_STATION_ID_SECONDS + _BLOCK_REMINDER_SECONDS) < 120`.

## Implementation decisions (helpers the plan had elided)

- **`_slot_boundary` (P3):** a `time(0,0)` slot end rolls to **NEXT-day midnight**; otherwise
  the final block computes a negative span and emits zero tracks. Proven by
  `test_final_midnight_slot_actually_fills`.
- **`_transition` open/close convention:** `next_block_name` / `next_block_starts_at` describe
  the block being **entered** (anchored at the slot's scheduled start, not the drifting
  cursor); `block_name` names the block the announcement airs **within** — the prior block
  being closed, or, for the day's opening transition (no prior), the block it opens.
- **`_bind`:** `datetime.combine(day, t, tzinfo=clock_zone)` — wall-clock binding so zoneinfo
  owns DST (D6).
- **H1 constants** named in the module: transition 10.0s, station_id 5.0s, reminder 8.0s,
  reminder cadence 30 min, top-of-hour window 2 min, recent-down-weight 0.05.
- **H3:** a grid group with no catalog pool raises the new typed `ScheduleError`
  (`PirateRadioError` leaf), never a bare `KeyError`.
- **R19 determinism:** a single injected `random.Random`; `_pick` iterates the *sorted* pool to
  build weights and uses `recent` only for membership (never iterated) → no hash-order
  dependence. Two-run-identical + persist→load→regenerate pinned now; a committed golden JSON
  is the cross-run guard, deferred to P1-5 per the BUILD-LOG resume note.

## A test-bug caught during GREEN (not an impl bug)

The first P3 assertion (`all PM tracks planned_start >= noon`) was wrong: the cursor is
continuous, so the AM block's soft boundary can leave the cursor slightly before noon and the
PM block legitimately begins from that carry-over cursor. Replaced with the non-emptiness +
fills-to-next-midnight invariant. (The §8.5 algorithm intentionally does not align block
airtime to the nominal boundary; only `next_block_starts_at` carries the scheduled time.)

## Gate

ruff + ruff-format + mypy clean; **211 tests**, 98.29% coverage; `generator.py` 100%.
