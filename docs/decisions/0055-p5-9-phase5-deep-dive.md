# P5-9 — Phase-5 full-seven deep-dive + remediation (phase gate)

The mandated phase-gate review of the assembled offline tagger (P5-1…P5-8). Seven persona agents
(opus) reviewed the `tagging/` package against the Rev-2 plan.

## Panel result: CONFIRM ×3, CONCERNS ×4

- **CONFIRM:** Senior Dev (RateLimiter math, retry-rearm, selection→tagger wiring, atomic write, the
  sync-vs-async seam split all correct), QA (gate verified 792/97.43%; every pragma is the literal
  hardware/network line, no logic hidden; load-bearing invariants pinned), Fact Checker (all gate
  numbers, decision records, API facts, and the no-new-deps claim CONFIRMED).
- **CONCERNS:** Devil's Advocate, Old Man, RPi Expert, Field Operator.

The panel ratified the substance (no new deps, fail-fast, no speculative surface, no hidden state;
the corruption gate, ban limiter, and key handling are genuinely sound) but found gaps, now fixed.

## Findings remediated

1. **[HIGH — DA] Generic per-file isolation untested.** `test_per_file_failure_is_isolated` only
   raised `TaggingError` (the `except TaggingError` branch); the `except Exception` branch (the guard
   for a bare `RuntimeError`/`OSError` from a degenerate file) was uncovered. **Fix:** added
   `test_generic_exception_is_also_isolated` (a non-`TaggingError` raise → that file fails, the
   sibling still tags, batch not aborted).
2. **[HIGH — RPi, Field-Op] The Rev-2 "broadcast-running WARN" was never implemented.** **Fix:**
   `_warn_if_broadcasting()` (best-effort `systemctl is-active pirate-radio`) called from CLI
   `_preflight` → logs a WARNING that tagging contends with a live broadcast (H-T6). Non-fatal.
3. **[MEDIUM — DA, RPi] Atomic write didn't fsync the directory** (rename durability on power loss).
   **Fix:** `_fsync_dir(path.parent)` after `os.replace`; and `shutil.copy2` moved INSIDE the
   try/except so an interrupt between copy and replace never leaves a stray temp.
4. **[LOW→fixed — Senior] A bad AcoustID `score`** (non-numeric / out of [0,1]) raised a
   `ValidationError` logged as CRITICAL. **Fix:** `parse_acoustid_response` now skips an
   out-of-range/non-numeric score as a tolerated sparse result (+ test).
5. **[MEDIUM — Field-Op, RPi] Runbook gaps.** **Fix:** `docs/ops/tagging.md` now documents active
   cooling for the 1–4 h run, the full-file-copy write amplification (motivating content-drive-not-SD),
   and the partial-tag re-fetch cost on re-runs.

## Not a defect (verified)

The two reviewers who reported a `mypy` `unused-ignore` on `tag_writer.py:64` hit a stubs-present
sandbox artifact (Fact-Checker + RPi confirmed it). A cache-cleared `mypy --strict src/` in the
canonical environment is **clean (55 files)** — the `# type: ignore[attr-defined]` on `mutagen.File`
is needed here (mirrors `catalog/metadata.py`). Left as-is.

LOW items deferred (non-blocking, noted for Phase 6 housekeeping): the three `tagger.py` seam
Protocols are thin (kept as documented test seams); a few defensive parse branches in `clients.py` are
uncovered fall-throughs; a redundant year-range guard in `read_existing_tags`.

## Final gate

ruff + ruff-format + mypy `--strict` clean (55 source files); **794 tests** (+2 remediation),
97.47% coverage.

## Phase 5 status

**COMPLETE.** The offline AcoustID/MusicBrainz batch tagger is built, reviewed, remediated, and green:
fpcalc fingerprint → rate-limited AcoustID → rate-limited MusicBrainz → thresholded fill-not-overwrite
selection → atomic tag write, with per-file isolation, a CLI with startup fail-fast + broadcast WARN,
and an operator runbook. No new Python dependency.
