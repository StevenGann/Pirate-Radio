# P5-1 — `tagging/models.py` (frozen result types) + `TaggingError` taxonomy

Strict spec-driven TDD (tests from the adopted Phase-5 plan §architecture / P5-1 → RED → GREEN →
gate). The first increment of the offline tagger: the typed values the pure stages pass (R16) and the
error taxonomy the backoff path branches on.

## Implementation

- `errors.py`: `TaggingError(PirateRadioError)` + leaves `TaggingUnavailable` (transient → retry),
  `TaggingThrottled` (429/503, carries optional `retry_after_seconds` the backoff honors before
  re-arming the limiter — H-T1), `TaggingFatal` (missing fpcalc / unset key·UA / unparseable / a
  degenerate file → fail-fast at startup or skip one file mid-batch). Mirrors the `ProviderError`
  split so the P5-3/4/5 clients can classify failures.
- `tagging/models.py` (frozen Pydantic, `extra="forbid"`): `Fingerprint(duration>0, fingerprint)`,
  `AcoustIdMatch(recording_id, score∈[0,1])`, `RecordingMetadata(title/artist/album/year)` (all
  optional — sparse is fine §9.3; `year` bounded 1..9999 like `Track`, A10), and **`TagPlan(path,
  title?, artist?, album?, year?)`** — the merge OUTPUT where a `None` field means LEAVE UNCHANGED.
  `is_noop` (all None) + `changes()` (only the set fields) so a below-threshold match or a fully-
  tagged file yields a no-op plan and never an empty/destructive write (H-T2).

## Tests (`tests/tagging/test_models.py`, 8)

Errors are `PirateRadioError`/`TaggingError` subclasses; `TaggingThrottled` carries/omits
`retry_after_seconds`; `Fingerprint` frozen+typed; `AcoustIdMatch` score clamped to 0..1;
`RecordingMetadata` tolerates missing fields + bounds `year`; `TagPlan.is_noop`/`changes()` (empty
plan → no-op + `{}`; a partial plan lists only its set fields).

## Gate

ruff + ruff-format + mypy `--strict` clean (50 source files); **720 tests** (+8), 97.50% coverage.

## Next

P5-2: `selection.py` PURE `choose_best` (the correctness heart — focused-panel test review): the
`_MIN_ACOUSTID_SCORE` floor, named tie-break, fill-not-overwrite merge.
