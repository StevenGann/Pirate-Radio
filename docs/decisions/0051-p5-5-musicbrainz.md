# P5-5 — MusicBrainz client (≤1 req/s, required User-Agent, fmt=json recording parse)

Strict spec-driven TDD (tests from plan §Pipeline step 4 / P5-5 → RED → GREEN → gate).

## Implementation (`tagging/clients.py`)

- **`MusicBrainzClient(user_agent, *, limiter, get_json, base_url)`** — `.recording(mbid)` over the
  shared `request_json` (rate-limited, retry-rearm) + the injected sync GET seam. The limiter is the
  ≤1 req/s one (`_MUSICBRAINZ_INTERVAL_SECONDS=1.0`, MB policy). A **descriptive User-Agent is
  REQUIRED** — empty/blank → `ConfigError` at construction (fail fast, not at first call); sent as the
  `User-Agent` header on every request.
- **`build_musicbrainz_url`** — PURE: `…/recording/{mbid}?fmt=json&inc=artists+releases` (JSON, not
  the SDK's XML).
- **`parse_recording`** — PURE: title; artist = the **joined artist-credit** (`name`+`joinphrase`, so
  "A feat. B" is preserved); album + year from the first release; `_parse_year` extracts a leading
  4-digit year (bounded 1..9999, unparseable → None). Every field best-effort — a sparse recording is
  fine (§9.3).

## Tests (`tests/tagging/test_clients.py` +6)

UA required (empty → `ConfigError`); URL is JSON + artists+releases; parse extracts title/artist/
album/year; multi-artist credit joined; sparse + bad-year tolerated; `recording()` sends the UA header
and is rate-limited (back-to-back → the ≤1 req/s limiter sleeps 1.0s via the injected clock).

## Gate

ruff + ruff-format + mypy `--strict` clean (52 source files); **773 tests** (+6), 97.58% coverage.

## Next

P5-6: atomic tag write (temp + same-dir + fsync + rename) via mutagen; CI round-trip (no @hardware).
