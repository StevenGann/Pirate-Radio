# P1-5 — `schedule/resume.py` (`find_now`: R11 gap path + R12 re-anchor + H4)

Strict spec-driven TDD: tests authored from design §6 / plan §4.6 → confirmed RED →
focused panel reviewed the tests → adopted → implemented to GREEN → gate → commit.

## Panel review of the tests (focused 3-agent: QA + Senior Dev + Devil's Advocate)

**Round 1 — 3 AYE / 0 NAY → ADOPTED.** Every reviewer hand-traced the arithmetic and
confirmed the re-anchor test is genuinely un-gameable (a naive "scan stored
planned_start" impl returns a gap where the correct re-anchor returns the station_id at
offset 2.0). Advisory findings were folded in before implementation:

- **DA MAJOR / Senior MINOR — monotonic invariant too weak.** `list(starts) == sorted(starts)`
  permits duplicate adjacent starts. Replaced with a strictly-increasing pairwise check
  (`all(a < b ...)`) + an `isinstance(starts[0], datetime)` type pin. duration > 0 and
  silence >= 0 guarantee strictly increasing.
- **Senior MINOR — missing R11 assertion.** `test_before_first_item_is_a_gap_to_it` now
  asserts `gap_seconds == 30.0` (it previously checked only item/next_item).
- **Added coverage:** inclusive-start when coming *out of* a gap onto an item's start
  (now=102); a single-item schedule (degenerate timeline, `next_item` always None); a
  patter-first opening item as a valid anchor.

## Scoping decisions (recorded so they are deliberate, not accidental)

The DA and QA each raised a "wrong-*" case. Both are **out of scope for Phase 1** and
deferred to Phase 2, by design:

- **Wrong patter *duration* (QA).** R12's "drift cannot compound" fully bites only when
  patter durations are estimates. Phase 1's `StubTTS` returns a *deterministic* length,
  so every duration (track from metadata, patter from the stub) is exact and the rebuilt
  timeline is exact. The re-anchor mechanism is what *keeps* it exact once real TTS
  arrives (Phase 2). Adding a wrong-duration test now would assert a "re-anchor at the
  nearest exact track, ignoring patter duration" contract the Phase-1 impl deliberately
  does not provide.
- **Patter-first item with a *drifted* start (DA).** Phase-1 schedules always open with
  the block_transition at an **exact** instant (midnight / slot boundary), so anchoring at
  `items[0].planned_start` is correct. A patter-first item whose *start* has truly drifted
  only arises with real TTS → Phase 2.

Both are tracked here as Phase-2 carry-forwards. The shipped contract is: **anchor at
`items[0].planned_start`; rebuild every later start from `duration + transition_silence`;
ignore all other stored `planned_start`s.**

## Implementation

- `NowPlaying` (frozen dataclass): `(item, offset_seconds, next_item, gap_seconds)`.
- `AnchoredSchedule` (frozen): `items` + precomputed `starts`/`ends`; `find_now(now)`
  does `bisect_right` over `starts` (H4: anchor once, O(log n) per tick). Start-inclusive,
  end-exclusive. Gap → `item=None` + `next_item` + remaining `gap_seconds` (R11). Past the
  last item → all-None (caller regenerates).
- `anchor(schedule, *, transition_silence)` builds the re-anchored timeline (R12);
  `find_now(schedule, clock, *, transition_silence)` is the one-call convenience
  (`anchor(...).find_now(clock.now())`), pinned equal by a test.
- `transition_silence` is re-applied here because the models store `duration` content-only
  (no double-count — Senior Dev verified against `models.py`'s invariant).

## Design-doc correction (H13)

Applied the deferred §6 correction: the design's bare `(item, None)` sketch is annotated
with the shipped `NowPlaying` upgrade (R11/R12/H4). (0010 had deferred this until the
resume module landed.)

## Gate

ruff + ruff-format + mypy clean; **227 tests**, 98.39% coverage; `resume.py` 100%.
