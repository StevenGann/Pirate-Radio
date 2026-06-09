# 0067 — Deep-dive cycle 3 of 4: CODE QUALITY review + remediation

Cycle 3 of the four dimension-specific deep-dives. A five-reviewer panel — Senior Dev, Old Man, QA
Engineer, Devil's Advocate (personas) + the specialized **python-reviewer** — reviewed code-level
quality: smells, correctness, idioms, test quality, duplication, naming.

## Panel result: CONFIRM ×4, DISPUTE ×1 → remediated

- **CONFIRM:** python-reviewer ("among the highest-quality async Python I have reviewed"; no
  CRITICAL/HIGH), Old Man (cleaner than most; major duplications already retired), QA Engineer
  (genuinely high-quality tests, not coverage-theatre), Devil's Advocate.
- **DISPUTE:** Senior Dev (H1 `play_day` seam erasure, H2 duplicated bisect).

**The headline finding** came from the Devil's Advocate (who voted CONFIRM but proved a real defect):
a genuine shipped bug that CI was green on.

## Remediation

### Correctness
1. **[HIGH — DA, proven bug] Station ID dropped for 14 of 24 hours.** The generator fired the
   once-per-hour `station_id` only when an item boundary landed in a 2-minute top-of-hour window;
   the soft-boundary cursor drifts past HH:02 over the day, so the ID was silently dropped for most
   hours — and the existing test used hour-aligned (3600s) tracks that masked the drift. **Fix:** fire
   the ID at the first item of each new clock-hour (`generator.py`, dropped the minute-window gate +
   the `_TOP_OF_HOUR_MINUTES` constant). New test `test_station_id_covers_every_hour_with_realistic_tracks`
   (realistic 5-min tracks → all 24 hours); the golden fixture regenerated (6 → 24 station IDs).
2. **[MEDIUM — Senior/DA] Resume mid-patter replayed the item from the start.** A resume landing
   inside a `station_id`/`block_transition` re-aired it from second 0. **Fix:** `play_day` now skips a
   partially-aired patter item (re-airing a half-spoken ID is worse than dropping it) while still
   seek-trimming a partial track. Test added.

### The DISPUTE (Senior Dev H1 + H2)
3. **[HIGH — Senior, python-reviewer] `play_day` defeated the typed `run_once` seam** via
   `**kwargs: object` + 5 `cast`s + `# type: ignore` + duplicated format defaults (a desync trap for
   the R11 gap silence). **Fix:** `play_day` now takes `run_once`'s explicit keyword surface and
   forwards by name — no casts, no `type: ignore`, the gap silence built at the same `sample_rate`/
   `channels` `run_once` receives.
4. **[HIGH — Senior] `slice_from_now` and `find_now` were the same bisect copy-pasted** over the same
   timeline (a fix to one wouldn't reach the other; resume and slicing must agree). **Fix:** one
   shared `AnchoredSchedule._locate` (single bisect) that both `find_now` (resume view) and a new
   `slice_from` (play-slice view) derive from; `daily.slice_from_now` delegates.

### Test infrastructure
5. **[HIGH — QA] A critical mutation HANGS instead of failing** (the stale-day-roll spin) — no
   per-test deadline. **Fix:** added `pytest-timeout` with `--timeout=60` so a deadlock/infinite-loop
   regression fails with a traceback, not a CI hang.

### MEDIUMs (batch)
6. `RingLogHandler.emit` now exception-isolated (`try/except: self.handleError`) so a malformed record
   can't escape into the sink-write/uvicorn caller (python-reviewer).
7. De-pragma'd the tested `status_code >= 400` error branches in `dj/_http.py` + `dj/tts.py` (they were
   labelled "network" but are exercised by the fake-httpx tests) — the error-mapping branch now counts
   toward the coverage gate (QA).
8. Extracted `durability.write_bytes_durably` — `persistence.atomic_write_json` and `_replace_keep_bak`
   no longer duplicate the temp→fsync→atomic-replace dance (Old Man).
9. Consolidated three year-parsers into one leaf `yeartag.parse_year` (Old Man).
10. Consolidated the duplicated s16le→float32 PCM decode in `dj/tts.py` into `_s16le_to_buffer` + a
    named `_S16_FULL_SCALE` constant (Old Man).
11. `/now` reports the resuming `block` during a transition gap instead of `None` (Senior).
12. Graceful shutdown `offload_pool.shutdown(wait=True)` so a clean stop doesn't tear down mid-write
    (python-reviewer).

## Carry-forward (LOW, non-blocking)

- `parse_acoustid_response` swallows a present-but-invalid score silently (a `logger.debug` would aid
  diagnosis — Senior MEDIUM/low); `map_ffmpeg_error` classifies "invalid data" as fatal (could be a
  transient truncated read — DA LOW); `query_logs` treats an unknown stored level as match-all (DA
  LOW); a `require_env` helper for the 6× env-read idiom (Old Man LOW); drop the underscore on the
  shared `tagging` constants imported across modules (Old Man LOW); the dead `ElevenLabsTTS(provider=)`
  param (Old Man LOW).

## Re-poll: 5/5 CONFIRM

Senior Dev re-verified H1+H2 (and the resume-mid-patter bonus) CLOSED → flipped to CONFIRM. The DA
re-verified the station-ID fix across 8 seeds with a varied catalog (exactly 24 IDs, all hours 0–23,
no block_reminder regression, R19 determinism intact) → CONFIRM. All five reviewers CONFIRM.

The DA surfaced one **pre-existing, harmless** edge while verifying (NOT a regression, NOT the bug
fixed): a grid slot boundary falling mid-hour (e.g. an 08:30 slot change) yields **two** station IDs
in that hour — one per slot — because `last_id_hour` resets to `None` inside the per-slot loop. This is
over-identification (an extra ID, never a dropped one), legal/harmless, and existed in the old code.
Carry-forward (LOW): carry `last_id_hour` across slots for strict once-per-hour at mid-hour block
boundaries.

## Gate

ruff + ruff-format + mypy `--strict` clean (64 source files); **881 tests** (+5), 97.63% coverage.
