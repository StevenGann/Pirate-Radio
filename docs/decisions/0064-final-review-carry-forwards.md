# 0064 — `0063` carry-forward cleanup (CF1–CF5)

Resolving the five non-blocking carry-forwards recorded in the final whole-system review (`0063`).
The two load-bearing ones (the day-roll guard) went through a focused-panel test review per the
strict-TDD discipline; the rest are mechanical cleanups gated by the suite.

## CF1 — stale day-roll Event guard (DA MEDIUM) + CF2 — reslice load under the regen lock (DA LOW)

A focused, correctness-heart increment → strict-TDD with a **focused-panel test review (QA + Senior
Dev + Devil's Advocate)**.

- **CF1:** `Station.run()` now `self._day_roll.clear()`s at the **top** of each slice and `await
  self._day_roll.wait()`s at the bottom (the clear moved from after-wait to top-of-loop). A roll
  Event left SET while the station wasn't parked on `wait()` (crash/restart, or a tail airing past
  00:00) is discarded at slice start instead of being consumed as an instant spurious **same-day
  re-slice**. Chosen over a date-compare guard because that would depend on the clock advancing and
  break the FixedClock re-slice tests. file-then-event (Q2) is preserved — the loop still only
  re-slices after a roll Event, and (single-setter/single-waiter/single-clear) clear-at-top can only
  ever discard an already-consumed or stale Event, never a legitimate pending roll.
- **CF2:** the daily `_load_or_generate(day)` is wrapped in `async with self._regen_lock` so a
  reslice load can't race a concurrent regenerate write (midnight roll / API regenerate); correctness
  no longer rides solely on `os.replace` atomicity. Scope is the **load only** (released before
  `play_day` — holding it across airtime would block the midnight roll for the whole day). No
  reentrancy: `run()` never calls `prepare_next_day` (the other lock holders' target).

**Panel: AYE ×3.** QA and DA both mutation-verified the increment and **convergently** flagged one
coverage gap (a spurious clear before the bottom `wait()` would drop an in-flight roll and strand the
station ~24h, yet all tests passed). Adopted DA's pre-merge ask: added
`test_run_reslices_once_when_the_roll_fires_during_play_day` (the straddle case — roll fired *during*
`play_day` survives → exactly one re-slice) and `test_run_releases_the_regen_lock_before_play_day`
(lock not held across airtime). Both are mutation-verified (each goes RED on the precise regression).

## CF3 — converge the atomic-write durability helpers (Senior Dev MEDIUM)

`persistence` and `tagging.tag_writer` each carried a private `_fsync_dir`. Extracted a single shared
core `pirate_radio/durability.py` (`fsync_dir`, `atomic_replace`) with the dir-fsync policy made
**explicit per call site**: `strict=True` for the `state_dir` (ext4/f2fs per A7 — a dir-fsync failure
propagates, pinned by a persistence test) vs `strict=False` for the content library (vfat/exotic — a
dir-fsync failure is harmless after the rename). The divergence was *intentional* (different storage
contexts) but previously silent + duplicated; it is now one implementation with a documented flag.
Added `tests/test_durability.py` pinning both policies.

## CF4 — delete dead `UdevAudioDeviceResolver.device_index` (Old Man LOW)

The by-name index method had no production caller (`__main__` uses `device_index_for_port`; the sink
opens by `PortId`). Deleted it and its two by-name tests (kept the `device_index_for_port` coverage).

## CF5 — remove the unenforced `LLMConfig.max_requests_per_minute` (Old Man)

A config field nothing read invited the false assumption that it throttled. Removed the field; v1
handles provider quotas reactively via failover (set a provider-side spend cap for cost control) — the
deliberate non-shipping of a proactive limiter is now a code comment, not a dead knob. Updated
`config.example.json` and `config-reference.md`.

## New carry-forward (surfaced by the panel)

- **Station's own reslice load runs synchronously on the event loop** (`_load_or_generate` in
  `run()`), same class as the midnight HIGH fixed in `0063` — but **lower severity**: the normal
  reslice is a cheap read; only the R6 absent/corrupt fallback does a full generate+write on the loop
  (rare), whereas the midnight task generated every night for every station. The architecture
  deep-dive can decide whether to offload it.

## Gate

ruff + ruff-format + mypy `--strict` clean (63 source files); **872 tests** (+7 net), 97.49% coverage.
