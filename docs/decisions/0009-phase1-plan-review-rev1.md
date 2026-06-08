# Distilled Review — Phase 1 Implementation Plan — **Rev 1**

> **Status:** For panel vote. **Source:** Round 1 reviews from all seven agents on
> `docs/plans/phase-1-implementation-plan.md`.
> Fact Checker verified all code-level claims (numpy/Pydantic ndarray trap correctly
> avoided via a frozen dataclass; `random.Random`+`crc32` determinism; asyncio.Queue
> semantics; every assumed Phase-0 signature) — **no factual blocker**. The plan's
> architecture is sound; the items below are amendments. Vote is on this document.

---

## A. Open-question resolutions (unanimous 7/7)

- **Q1 — `state_dir` (A6) governs.** Generated schedules are written to
  `state_dir/schedules/<station>/<date>.json`, **not** §8.4's
  `schedule_dir/generated/`. §8.4 prose is corrected (doc bug). **A6 writability is
  ratified as narrowed:** `state_dir` must be writable; `content_dir`/`schedule_dir`
  need only be readable (read-only library/grids on a separate mount is a *good*
  field posture). Config logs the device/mount `state_dir` resolves to.
- **Q2 — Exact-track re-anchor** (not the hourly-ID re-anchor). It bounds drift at
  the source (exact metadata durations), needs no top-of-hour scaffolding, and keeps
  cold-start == resume. **Freeze the `find_now`/`NowPlaying` contract now** so Phase 2
  real TTS drops in without a signature change; document that Phase 2 re-synthesizes
  patter durations (not persisted estimates) so between-track offsets stay correct.
- **Q3 — Fixed config default for `refill_budget_seconds`** (derived from
  `look_ahead_depth × assumed_per_item_ceiling`); **no measurement spike** now
  (StubTTS/FakeDecoder are instant — any number would be fiction). Empirical
  calibration is a **Phase-2 spike** on real Pi hardware. **Defer** the warm/deeper
  buffer at block boundaries to Phase 2 with the real budget.

---

## B. Must-fix plan amendments (before GREEN)

- **P1 — Player must not DROP an item on backstop.** *(Devil's Advocate OBJECTION.)*
  The drafted `for _ in range(count): seg=get(timeout); if seg is None: play(backstop);
  continue` consumes a loop iteration on a miss **without ever draining the slow
  segment** → the real item is never played. R11's true property is *never dead air
  AND no item dropped*. **Fix:** decouple "fill the wait with the backstop" from
  "advance to the next item" — after the backstop covers the stall, the real segment
  is still consumed and played. **Test:** ordering `[…, backstop, the-real-item, …]`,
  played-real-count == schedule-item-count, zero items lost.
- **P2 — Backstop deadline via the injected Sleeper/Clock seam, not
  `asyncio.wait_for`.** *(QA BLOCKER.)* A real wall-clock timeout makes the headline
  stall→backstop test flaky/slow and contradicts R21 ("zero wall-clock sleeps").
  Race `queue.get()` against `sleeper.sleep(budget)` where a `VirtualSleeper`
  resolves deterministically; the test advances virtual time. **Specify the
  virtual-time contract** (single event loop, `Sleeper` as the sole time-advancer,
  how producer wake-up composes with the bounded queue) and ship it with
  `pipeline/timing.py` *before* the P1-7 pipeline tests are authored.
- **P3 — Generator final-slot 24:00 boundary.** *(Senior Dev MAJOR.)* `Slot.end ==
  time(0,0)` is the 24:00 sentinel; `_slot_boundary` must roll it to **next-day
  midnight** or the last (most-aired) block computes a negative span and emits zero
  tracks. **RED test:** the `00:00→12:00 / 12:00→00:00` grid fills the PM block.
- **P4 — Gaplessness tested as sequence + no-backstop, not a duration sum.**
  *(QA MAJOR.)* Assert the exact ordered played-buffer sequence (incl. interleaved
  silence) **and** that no "refill missed" WARNING fired on the happy path. A
  `sum(durations)` can be right while ordering/timing is wrong.
- **P5 — R19 determinism tested on the persisted artifact.** *(QA MAJOR.)*
  generate → `save_schedule` → `load_schedule` → regenerate → compare **on-disk
  bytes**, plus assert against a **committed golden JSON**. The in-process
  `model_dump_json()==` check alone doesn't prove the stated "(catalog+grid+seed+
  clock) → byte-identical *persisted* JSON" contract.
- **P6 — `find_now` × re-anchor interaction.** *(QA + Senior Dev.)* Parametrized
  `now`-sweep `[mid-track, exact-start, in-gap, past-end]` **after a non-trivial
  re-anchor**; the R12 test must feed `planned_start`s genuinely offset from
  exact-track math and assert the re-anchored item differs from the naive one
  (else, with deterministic StubTTS, the test passes trivially proving nothing).
- **P7 — Scope the pipeline `ProviderError` catch.** *(Senior Dev MAJOR.)* Phase 1
  fires the backstop on any `ProviderError`, but document it **provisional** with a
  `producer.py` TODO: Phase 3 failover branches `ProviderFatal` (stop retrying this
  provider) vs retryable (advance the chain). Don't bake a catch-all into the
  contract that Phase 3 must unwind.

---

## C. Adopt (hardening / documentation)

- **H1 — Name the generator magic numbers** as module constants / `StationConfig`
  fields (`_BLOCK_REMINDER_EVERY`, the `0.05` repeat down-weight, station_id 5.0s,
  reminder 8.0s); flag the guessed durations as accepted Phase-1 debt the R12
  re-anchor absorbs. *(Old Man.)*
- **H2 — Clarify `repeat_window` semantics:** the plan uses a **soft down-weight**
  (a recent track *can* still repeat), which differs from §13's "don't replay within
  this window." Document the soft-down-weight semantics in the config doc (or switch
  to hard exclusion) — make it a decision, not a float-equality accident. *(Old Man.)*
- **H3 — Typed error on missing group pool:** guard `groups[slot.group]` so a grid
  referencing a group empty in the current catalog raises a typed `PirateRadioError`,
  not a raw `KeyError`. *(Senior Dev.)*
- **H4 — Anchor the timeline once at load** (deterministic from exact durations +
  silences); `find_now` binary-searches it rather than re-anchoring O(n) per call.
  *(Senior Dev.)*
- **H5 — One named default sample-rate constant** shared by `AudioBuffer.silence`,
  `StubTTS`, `FakeDecoder` so rates can't desync (a gapless-playback bug). *(Senior Dev.)*
- **H6 — Dispatch on the `ScheduleItem` variant type** (`match`/isinstance) in the
  producer so a future arm is a typecheck obligation; player asserts `seg.item`
  matches the expected next item (ordering invariant). *(Senior Dev.)*
- **H7 — Whole-track-buffer forward note:** Phase 2's `FfmpegDecoder` must
  stream/chunk (4 stations × ~92 MB/track is infeasible on a Pi); the
  `Decoder`/`AudioSink` Protocols must not assume a single full-track buffer; Phase 2
  reconciles chunked playback with whole-track EBU R128 (two-pass/streaming). *(RPi.)*
- **H8 — numpy runtime assumption: 64-bit Raspberry Pi OS (arm64) Bookworm** (armhf
  has no wheel → source build). State in §3.1. *(RPi.)*
- **H9 — A9 cache keys on directory-tree mtimes;** in-place tag edits need an
  explicit rescan/`--regenerate`. Document the invalidation granularity. *(RPi.)*
- **H10 — State explicitly that Phase 1 is NOT a deployable radio** (no coordinator
  /supervisor/midnight-regen/systemd); name the later phase that wires the
  regenerate-on-`None` and crash-restart loop. *(Field Op.)*
- **H11 — Backstop exhaustion:** count/log consecutive backstops and escalate after
  N (feeds the future health signal) rather than looping the same canned clip
  silently forever. *(Field Op.)*
- **H12 — Resume robustness contract:** note that "content file referenced by the
  airing track is missing at airtime → backstop, not crash" (real decode path is
  Phase 2; pin the contract intent now). *(Field Op.)*
- **H13 — Record `NowPlaying` (item/offset/next_item/gap_seconds) as a §6 design-doc
  correction** replacing the `(ScheduleItem | None, float)` tuple — the typed result
  makes the R11 gap case explicit.

---

## D. Accept as-is (strengths recorded)

`find_now == cold-start == resume` as one path with no persisted playhead (A7);
`AudioBuffer` as a frozen dataclass (Fact-Checker-verified: avoids the Pydantic-
ndarray `PydanticSchemaGenerationError` trap); `ScheduleItem` discriminated union
(invalid states unrepresentable); `transition_silence` kept OUT of `duration` so the
exact-track re-anchor stays exact; FakeDecoder/StubTTS keep timing real while audio
is silent (Phase-1 thesis = timing, not fidelity); deferring real ffmpeg to Phase 2
paired with loudness (R22); `sounddevice` optional lazy extra (CI never loads
PortAudio); `pragma: no cover` confined to the one hardware line; numpy the only new
runtime dep.

---

## E. Concrete plan edits (if adopted)

Append a governing "Review Amendments (Rev 1 — adopted)" section to
`phase-1-implementation-plan.md` capturing A–C; correct §8.4 (Q1) and §6 (`NowPlaying`,
H13) in the design doc when those modules land. PR breakdown grows by the new tests
(P1, P4, P5, P6) but no new module is added.

---

## Vote — Round 1 (2026-06-07)

| Agent | Vote | Note |
|---|---|---|
| Senior Dev | **AYE** | P3/P7/H3-H6/P6 captured; P1/P2/P5 strengthen R11/R19. |
| Old Man | **AYE** | H1/H2 as decisions; every amendment is correctness/DRY/named-debt, no speculative generality (H4 simplifies existing O(n)). |
| Raspberry Pi Expert | **AYE** | H7/H8/H9 faithful; Q1/Q2/Q3 as positioned. |
| Devil's Advocate | **AYE** | P1 objection captured verbatim with the exact test; P2/H11/H12 harden it further; noted concerns resolved. |
| QA Engineer | **AYE** | P2 BLOCKER + virtual-time contract captured; P4/P5/P6 + ≥90% per-module floor met. |
| Field Operator | **AYE** | Q1/A6 ratified; H10/H11/H12 track deployability; P1 fixes a real item-drop bug. |
| Fact Checker | **abstain** | Transient API rate-limit mid-vote; had already verified all claims (no refutations) in the gather phase. |

**Tally: 6 AYE / 0 NAY / 1 abstain → ADOPTED.** (Charter: a non-response is an
abstention, not a NAY; ≤1 NAY adopts.)

Manager appends the governing amendments to `phase-1-implementation-plan.md` and
begins implementing increments tests-first.
