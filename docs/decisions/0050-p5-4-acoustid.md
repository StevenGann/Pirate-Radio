# P5-4 — AcoustID client + `request_json` retry-rearm + `scrub_secrets` `client=` fix

Strict spec-driven TDD (tests from plan §Pipeline step 3 / P5-4 → RED → GREEN → gate).

## Implementation (`tagging/clients.py` + `supervisor.py`)

- **`scrub_secrets` `client=`/`token=` query-param pattern** (the Field-Op CRITICAL from the plan
  review): AcoustID carries the key as `?client=<key>`, which the prior patterns missed. Added a
  case-insensitive `(client|token)=…` redaction + two scrub tests. H22 "never logged" now holds even
  if a bubbled exception embeds the request URL.
- **`request_json(get_json, limiter, *, max_retries, **kw)`** — the shared rate-limited GET with
  retry-and-rearm (AcoustID + MusicBrainz both use it): each attempt waits its limiter slot; a
  `TaggingThrottled` (429/503) calls `limiter.note_throttle(retry_after)` and retries, so a throttled
  service is never hammered; all attempts throttled → `TaggingUnavailable`.
- **`acoustid_key(env_name)`** (H22) — reads the key from the env BY NAME at call time; unset → a
  `TaggingFatal` naming the VAR (never a value); the key is placed only in the request params at the
  GET seam, never in an exception string.
- **`build_acoustid_params` / `parse_acoustid_response`** — PURE: params (integer duration, recordings
  meta); response → `tuple[AcoustIdMatch]` (recording MBIDs + the result score) sorted highest-first;
  non-`ok` status → `TaggingFatal`; missing fields tolerated.
- **`AcoustIdClient(api_key_env, *, limiter, get_json)`** — `.lookup(fingerprint)` composes the above
  over the injected sync GET seam (`get_json`); the default `_default_get_json` is the only network
  line (pragma'd, lazy httpx, maps 429/503→`TaggingThrottled` w/ Retry-After, transport→`Unavailable`).

## Tests (`tests/tagging/test_clients.py` +9, `test_supervisor.py` +2)

`request_json` retries-then-succeeds (re-arms each throttle) / gives-up→`Unavailable`; `acoustid_key`
reads-by-name / unset→Fatal-naming-var; params shape; parse extracts+sorts / empty / non-ok→Fatal;
`AcoustIdClient.lookup` threads the key only to the GET seam; `scrub_secrets` redacts `client=`/`token=`.

## Gate

ruff + ruff-format + mypy `--strict` clean (52 source files); **767 tests** (+11), 97.61% coverage.

## Next

P5-5: MusicBrainz client (≤1 req/s, required User-Agent, `fmt=json` recording-parse) over the same
`request_json` + `_default_get_json` seam.
