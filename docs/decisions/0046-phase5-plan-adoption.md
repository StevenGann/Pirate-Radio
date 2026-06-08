# Phase-5 plan — Rev 1 vote + Rev 2 adoption (offline AcoustID/MusicBrainz tagger)

## Rev 1 — full-seven vote: 2 AYE / 5 NAY → REVISE

- **AYE:** Senior Dev (conditional on de-duping `fingerprint.py` vs `pyacoustid`), Fact Checker
  (all claims accurate vs repo + external reality; fixed a §15→§19 citation slip).
- **NAY (all substantive + convergent):**
  - **Devil's Advocate** — AcoustID was UNthrottled (only MusicBrainz limited) and the retry path
    could bypass the limiter → the user's API key gets banned; plus low-confidence match corrupts good
    tags, non-atomic write, non-deterministic `--limit`, key in the `client=` URL not scrubbed.
  - **QA** — the tag-write gate was unfalsifiable and could hide the destructive `mutagen` write
    behind `@hardware` (mutagen writes tags in pure Python → CI-testable); rate-limit gate needed an
    injected monotonic clock to prove deficit math, not a flat sleep.
  - **Old Man** — `pyacoustid` + `musicbrainzngs` are needless deps whose jobs the plan reimplements
    anyway; the existing 64-line `dj/_http.py` seam already does this; single-impl `TagWriter`
    Protocol is speculative; validate inputs at startup, not on first network touch.
  - **RPi Expert** — "offline" was a code boundary only: a long `fpcalc` run can starve the live
    broadcast (no nice/ionice, no don't-run-while-broadcasting guard); non-atomic in-place writes
    corrupt files on power loss; CPU cost under-acknowledged + a wrong "rate-limit-dominated" claim.
  - **Field Operator** — the AcoustID key rides in `?client=<key>`, which the reused `scrub_secrets`
    does NOT redact (verified: `_SCRUB_PATTERNS` has no `client=` rule) → H22 "never logged" was
    false; runbook unverifiable; weak resume.

## Rev 2 — every NAY folded; re-vote of the five NAY voters: 5 AYE / 0 NAY

Combined with the Rev-1 Senior AYE + Fact-Checker CONFIRM → **ADOPTED (effectively 7 AYE / 0 NAY)**.
Folded:

- **No new Python deps** — AcoustID + MusicBrainz over the existing `dj/_http.py` seam (`fmt=json`);
  only the `fpcalc` binary (`apt install libchromaprint-tools`). `[tagging]` extra removed.
- **Both services rate-limited** via one `RateLimiter(min_interval, *, clock, sleep)` (AcoustID
  ≈0.34 s, MusicBrainz 1.0 s); retry honors `Retry-After` and **re-arms spacing**; tested with an
  injected clock (deficit sleep; spaced→0; flat-always-sleep FAILS; throttle→still-respects-spacing).
- **`_MIN_ACOUSTID_SCORE` floor** → below-threshold is a NO-OP plan; fill-not-overwrite; named
  tie-break (highest score, then lowest MBID); never overwrite present with empty.
- **Atomic temp+rename** tag write (power-loss safe); **CI mutagen round-trip, no `@hardware`**.
- **Key-leak fix** — key only at the URL seam; `scrub_secrets` gains a `client=`/`token=` pattern,
  tested.
- **Pi resource isolation** — `nice -n 19`/`ionice -c3` for the run + `fpcalc`; startup WARN if the
  broadcast daemon looks live; `fpcalc -length 120` bounds per-file CPU; runbook documents the 1–4 h
  cost, active cooling, content-mount-not-boot-SD (A6).
- **Startup fail-fast** on missing fpcalc / unset key env / empty UA, before walking files.
- ~5 modules; no `TagWriter` Protocol (mutagen-direct, pure tag-diff).

## Carry-forward implementation notes (folded into the increments)

- **`dj/_http.py` is async POST-only** (`post_json`) + the PURE mappers. The sync GET clients (P5-3/4/5)
  must ADD a small sync `get_json` sibling (reuse `map_http_status`/`map_httpx_exception`); the plan's
  "reuse the seam" is a one-function extension, not literal reuse of `post_json`. (Raised by Senior,
  Old Man, DA, Field-Op — non-blocking.)
- **Atomic write must use a same-directory temp + `fsync` before rename** (a cross-device rename to a
  different mount silently degrades to copy+unlink) — the P5-6 atomicity test pins it (raised by RPi).

## Build order

P5-1 models/errors → P5-2 selection (focused-panel test review) → P5-3 fpcalc+RateLimiter → P5-4
AcoustID → P5-5 MusicBrainz → P5-6 atomic write → P5-7 tagger → P5-8 CLI+runbook → P5-9 deep-dive.
Strict spec-driven TDD; one decision record per increment.
