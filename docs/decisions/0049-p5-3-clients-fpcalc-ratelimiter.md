# P5-3 — `tagging/clients.py` (RateLimiter + fpcalc fingerprinter)

Strict spec-driven TDD (tests from plan §"Rate limiting"/P5-3 → RED → GREEN → gate); the
ban-prevention invariant + the Chromaprint subprocess seam.

## Implementation

- **`RateLimiter(min_interval, *, clock, sleep)`** — spaces calls to one service (H-T1). `acquire()`
  sleeps only the REMAINING deficit computed from the injected monotonic `clock`: first call no wait;
  back-to-back → sleep the full interval; a call after the interval already elapsed → sleep ZERO (a
  flat-always-sleep impl fails the test). `note_throttle(retry_after)` pushes the next allowed call
  out by `max(interval, Retry-After)` so a `429/503` retry re-arms the spacing instead of hammering.
- **`build_fpcalc_argv` / `parse_fpcalc_json`** — PURE: `fpcalc -json -length 120 <file>` (bounded
  per-file CPU, RPi); parse → `Fingerprint`; bad JSON / missing fields → `TaggingFatal` (skip).
- **`FpcalcFingerprinter`** — `.fingerprint(path)`; the blocking `subprocess.run` is injectable
  (`runner`) so tests need no binary; the default runner is the only hardware line (R20/pragma);
  non-zero exit / `FileNotFoundError` / timeout → `TaggingFatal`.

The tagger is SYNC (batch, not the async path), so this builds its own tagging-typed seam rather than
reuse the async, `ProviderError`-typed `dj/_http.py` `post_json` (P5-4/P5-5 add sync HTTP here).

## Tests (`tests/tagging/test_clients.py`, 11)

RateLimiter: first-no-sleep, back-to-back→deficit, spaced→zero, throttle→re-arm (with + without
Retry-After), all via an injected `_FakeClock`. fpcalc: argv shape, parse success, bad-JSON →
`TaggingFatal`, missing-field → `TaggingFatal`, successful run, non-zero exit → `TaggingFatal`.

## Gate

ruff + ruff-format + mypy `--strict` clean (52 source files); **756 tests** (+11), 97.67% coverage.

## Next

P5-4: AcoustID HTTP client (sync GET, key-by-env-name H22 + `client=` scrub, throttle→backoff).
