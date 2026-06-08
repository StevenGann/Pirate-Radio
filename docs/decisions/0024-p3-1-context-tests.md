# P3-1 — `dj/context.py` (DjContext / BlockContext / TrackMeta, R16)

Strict spec-driven TDD: tests authored from the adopted Phase-3 plan §3.2 / §5 context row →
confirmed RED (module absent) → focused panel reviewed the TESTS → folded the must-fixes →
implemented GREEN → gate → commit. The first Phase-3 increment — the typed grounded context (R16,
no bare dicts).

## Panel review of the tests (focused: QA + Senior Dev + Devil's Advocate)

**Tally: QA AYE, Senior Dev AYE, DA NAY → 1 NAY (adopts under the ≤1-NAY charter), but the DA's
NAY-blocking gaps were cheap, real coverage-gaming surfaces and were folded in anyway.**

DA's blocking gaps (all folded):
1. **Empty-string sparse contract untested** — an `is None` impl would call `""` "present" and
   pass. Added `test_is_sparse_treats_empty_string_as_absent` pinning the truthy semantics
   (matches `prompts.py`'s `if t.title:` guard).
2. **§9.2 round-trip dropped fields** — `track.title/artist/album`, `current_block.name`,
   `next_block.boundary_at`, `recent_tracks[0].title` were constructed but never read back, so a
   dropped/renamed field passed. Added value assertions for every §9.2 field.
3. **`recent_tracks` immutability** — nothing proved a `list` arg lands as a `tuple` (a
   `list`-annotation regression would put a mutable list on a frozen model). Added
   `test_recent_tracks_coerces_list_to_tuple` + `test_recent_tracks_rejects_non_trackmeta_elements`.

Convergent (DA + Senior Dev): **`year` was unbounded** vs `Track.year`/`_parse_year` (A10) — a
nonsense `year=0` would ground "Year: 0". Bounded `TrackMeta.year` to `ge=1, le=9999` and added
`test_trackmeta_year_bounds_reject_nonsense` / `test_trackmeta_year_accepts_valid_range`. QA's
`test_trackmeta_optionals_default_none` also added.

Noted, not changed (panel's call): `boundary_at` is left tz-un-validated — it is grounding-only
(formatted `%H:%M`), not a D6 scheduling boundary, and the producer always sources it from an
already-D6-validated schedule datetime. Documented in the module docstring.

## Implementation

`dj/context.py`: three frozen `extra="forbid"` pydantic-v2 models (the stricter `schedule/models.py`
idiom). `TrackMeta` (title/artist/album/year all optional, year bounded) + `is_sparse` truthy
property; `BlockContext` (name `min_length=1`, optional tagline/description/boundary_at); `DjContext`
(kind/persona/station_name `min_length=1`, optional station_tagline/next_block/track, `recent_tracks:
tuple[TrackMeta, ...] = ()`). `kind` is left a bounded free string — `PATTER_KINDS` validation lives
downstream in `dj/prompts.py` (P3-2).

## Gate

ruff + ruff-format + mypy clean; **395 tests** (+24 new), 98.78% coverage; `dj/context.py` 100%.

## Next

P3-2: `dj/prompts.py` — grounded, pure prompt construction (§9.2/§9.3), tests-first.
