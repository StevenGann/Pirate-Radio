# Phase 5 Implementation Plan — Offline AcoustID/MusicBrainz Batch Tagger — **Rev 2 (for re-vote)**

> **Status:** Rev 2 — folds the **Rev-1 full-seven vote (2 AYE / 5 NAY → REVISE)**. Rev-1 NAYs:
> Devil's Advocate (AcoustID unthrottled + retry bypasses the limiter → key ban), QA (the tag-write
> gate was unfalsifiable / hid behind `@hardware`; rate-limit test needs an injected clock), Old Man
> (two needless SDKs reimplemented anyway; single-impl Protocol), RPi (no resource isolation vs live
> broadcast; non-atomic in-place writes), Field-Op (AcoustID key leaks via the `client=` URL param
> that `scrub_secrets` misses). AYE: Senior (conditional on the SDK/fingerprint de-dup), Fact-Checker
> (claims accurate; fixed the §19-not-§15 citation). **Every NAY point is folded below** (marked
> "Rev-2"). Strict spec-driven TDD; charter ≤1 NAY adopts, ≥2 NAY → revise. Design source: §19 source
> tree (`tools/tag_library.py`), §11 / §21.6, design lines 154–157 / 437 / 495.

## Goal & non-goals

**Goal.** A **standalone, offline batch tool** that enriches a station library's audio-file tags so
the catalog scanner (§7) and the DJ patter grounding (§9.2/§9.3) read clean `title`/`artist`/`album`/
`year` instead of sparse/missing tags. Tag once ahead of time; the running radio never calls these
services.

**Why offline (design §157/§437).** Fingerprinting is CPU-slow, AcoustID is rate-limited (≈3 req/s
per key) and **MusicBrainz requires ≤ 1 request/second** with a descriptive **User-Agent (with
contact)** — four live stations would breach that instantly. Separate CLI (`python -m
pirate_radio.tagging`), NOT in the broadcast path.

**Non-goals.** No runtime tagging; no audio re-encode; no MusicBrainz/AcoustID *writes* or submission
(read-only lookups); no GUI. The daemon never imports `tagging`.

## Rev-2 dependency decision: NO new Python deps (Old Man + Senior)

Rev-1 added `pyacoustid` + `musicbrainzngs`. **Rejected.** Both are reimplemented here anyway: we
split `fpcalc` (subprocess, like `FfmpegDecoder`) from the AcoustID HTTP call, and we *replace*
`musicbrainzngs`'s built-in limiter with our own tested one and want `fmt=json` not its XML. The repo
already has a **lazy httpx seam — `dj/_http.py`** (`post_json` + PURE `map_http_status`/
`map_httpx_exception`); AcoustID is one GET to `api.acoustid.org/v2/lookup`, MusicBrainz one GET to
`/ws/2/recording/{mbid}?fmt=json&inc=artists+releases`. So:

- **No `[tagging]` extra, no new PyPI package.** Reuse `httpx` (already core) + `mutagen` (already
  core). The ONLY external requirement is the **`fpcalc` binary** (`apt install
  libchromaprint-tools`), documented like `libportaudio2`. The CI suite needs nothing extra.

## Constraints carried from the standing rules

- **R21** — no network/`fpcalc` on the CI path: each network/subprocess line is lazy + `# pragma: no
  cover` + a live smoke (`@pytest.mark.network` / `@pytest.mark.hardware`); all argv-build, JSON
  response-parse, selection, tag-diff, and rate-limit logic is PURE + unit-tested with fakes +
  injected clock/sleep. A `no-module-scope-import` ast test guards lazy imports.
- **H22 + Rev-2 key-leak fix** — the AcoustID key is read from the env **by name** at call time,
  placed in the request URL **only at the HTTP-call seam** (never in an exception/log string), and
  `scrub_secrets` gains a **`client=`/`token=` URL-query-param pattern** (Rev-1 Field-Op/DA: AcoustID
  sends `?client=<key>`, which the current patterns miss). A test asserts a simulated AcoustID
  URL-bearing exception is scrubbed.
- **R16** typed frozen results; **R18/R19** injectable clock + deterministic, seed-free selection.
- **Coding style** — sync (batch, not the async path — §21.6); **~5 files** (Rev-2, Old Man);
  per-file isolation (never abort the batch).

## Architecture (`src/pirate_radio/tagging/` — Rev-2 collapsed to 5 modules + CLI)

```
tagging/
  models.py     NEW  frozen: Fingerprint, AcoustIdMatch, RecordingMetadata, TagPlan; TaggingError taxonomy
  selection.py  NEW  PURE choose_best(matches, recording, existing, *, min_score) -> TagPlan (R19)
  clients.py    NEW  fpcalc subprocess (argv/parse PURE) + AcoustID & MusicBrainz HTTP over dj/_http;
                     a shared RateLimiter(min_interval, *, clock, sleep) used by BOTH web clients
  tagger.py     NEW  orchestration: walk -> skip-tagged -> fingerprint -> acoustid -> mb -> select ->
                     atomic tag-write; dry-run; per-file isolation; summary; nice/ionice; --limit
  __main__.py   NEW  argparse CLI + STARTUP validation (fpcalc present, key env set, UA non-empty,
                     warn-if-broadcast-running) then run (python -m pirate_radio.tagging)
```

No `TagWriter` Protocol (Rev-2, Old Man: one impl) — the tag *diff* is a PURE function in
`selection.py`/`models.py`; `tagger.py` applies it via `mutagen` directly with an **atomic
write-to-temp + rename** (Rev-2, DA/RPi: in-place `mutagen.save()` is not power-loss-safe). The
fpcalc/AcoustID/MusicBrainz callables are injected into `tagger.py` as plain functions (a fake is a
function, not a named Protocol) so tests need no SDK.

`docs/ops/tagging.md` — runbook (below).

## Rate limiting (Rev-2 — DA CRITICAL + QA)

One `RateLimiter(min_interval_seconds, *, clock, sleep)` PURE-ish helper, instantiated **per service**
(`acoustid`: ≈3 req/s → 0.34 s; `musicbrainz`: ≤1 req/s → 1.0 s) and shared by every call to that
service in a run. `acquire()` computes the **deficit** from the injected **monotonic clock** and only
sleeps the remaining time (a call after the interval already elapsed sleeps **zero**). Tests inject a
fake clock + sleep-recorder and assert: back-to-back calls sleep ≈ the deficit; a spaced call sleeps
0; a flat-always-sleep impl FAILS. **Retry path (Rev-2):** a `429`/`503` honors `Retry-After`
(bounded) and then **re-arms the limiter** so the next normal call still respects spacing — tested
("throttle response → backoff ≥ Retry-After AND the following call still ≥ interval"). Both AcoustID
and MusicBrainz go through their limiter; **AcoustID is no longer unthrottled** (the Rev-1 hole).

## Pipeline (per file, isolated)

1. **Skip-tagged gate** — has `title` AND `artist` and `--force` off → skip (DEBUG).
2. **Fingerprint** — `fpcalc -json -length 120` subprocess (argv + JSON parse PURE; the run line
   `@hardware`/pragma; H14 timeout; bad exit/JSON → `TaggingError`, skip). `-length 120` bounds CPU
   per file regardless of track length (Rev-2, RPi).
3. **AcoustID lookup** (rate-limited) — GET `…/v2/lookup` (key in URL only at the seam, H22) →
   parse → sorted `AcoustIdMatch` (MBID + score). Empty → skip (INFO).
4. **MusicBrainz lookup** (rate-limited, UA required) — GET `…/recording/{mbid}?fmt=json` for the top
   match → `RecordingMetadata`. Missing fields tolerated.
5. **Select** — `choose_best(matches, recording, existing, min_score=_MIN_ACOUSTID_SCORE)` (PURE,
   R19): **below the score threshold → NO-OP plan** (Rev-2, DA/QA: a low-confidence match must never
   write over good files); else highest score, **tie-break highest-score then lexicographically
   lowest MBID** (named, tested); merge = FILL missing only, `--force` overwrites, **never write
   empty/None over a present field**.
6. **Write** — apply the `TagPlan` via mutagen with **atomic temp+rename**; `--dry-run` logs the plan
   and writes nothing.

Per-file `try/except (TaggingError, …)` → log (scrubbed) + continue; end summary `tagged N, skipped
M, failed K of T` over a **stably-ordered** file walk (so `--limit` is deterministic, Rev-2 DA).
`tagger.py` lowers its own + the `fpcalc` child priority via `nice`/`ionice` (Rev-2, RPi) so a run
can't starve a live broadcast.

## Increment breakdown (strict spec-driven TDD)

- **P5-1 — `models.py`** frozen types + `TaggingError` taxonomy (a `PirateRadioError` leaf with
  `TaggingThrottled`/`TaggingUnavailable` sub-leaves so the backoff path can branch — Rev-2, Senior).
- **P5-2 — `selection.py`** PURE `choose_best`. **Focused-panel test review** (the correctness heart).
  Gate: below-`_MIN_ACOUSTID_SCORE` → no-op; highest-score wins; **named tie-break** (lowest MBID);
  fill-missing vs `--force`; never overwrite present with empty; empty matches → no-op.
- **P5-3 — fpcalc in `clients.py`** + `RateLimiter`. Gate: argv-build + `-json` parse pure (fake
  runner); bad exit/JSON → `TaggingError`; H14 timeout; **RateLimiter deficit math with an injected
  clock** (back-to-back → deficit sleep; spaced → 0; throttle → re-arm); only `subprocess.run`
  `@hardware`; ast import-guard.
- **P5-4 — AcoustID client** (`clients.py`). Gate: request-build incl. key-by-env-name (H22, error
  names the var never the value); **key-in-`client=`-URL scrubbed** (the new `scrub_secrets` pattern,
  tested); response-parse → sorted matches; throttled→backoff; HTTP lazy (`@network`).
- **P5-5 — MusicBrainz client** (`clients.py`). Gate: **≤1 req/s via the shared limiter** (injected
  clock); **UA required** (missing → `ConfigError`); `fmt=json` recording-parse → `RecordingMetadata`;
  missing fields tolerated; `429/503`→backoff-then-respect-spacing; HTTP lazy (`@network`).
- **P5-6 — atomic tag write** (in `tagger.py`/`models.py`). Gate: tag-diff pure; **real mutagen
  round-trip on a tiny generated file IN CI** (NOT `@hardware` — mutagen writes tags in pure Python;
  Rev-2 QA); `--dry-run` writes nothing; **temp+rename atomicity** (a simulated mid-write failure
  leaves the original intact — Rev-2 DA/RPi).
- **P5-7 — `tagger.py`** orchestration. Gate: skip-tagged; per-file isolation (one raising file →
  others still tagged); dry-run; deterministic ordered `--limit`; rate-limited calls; nice/ionice
  applied (assert the subprocess is launched lowered-priority, via an injected runner); summary; all
  seams faked, zero network/binary.
- **P5-8 — `__main__.py` CLI** + `docs/ops/tagging.md`. Gate: `main(argv, *, deps)` seam tested with
  fakes; **startup validation fails fast** (missing fpcalc / unset key env / empty UA → exit before
  walking files — Rev-2 Old Man); **warn if the broadcast daemon appears to be running** (Rev-2 RPi);
  runbook documents getting an AcoustID key, `read -s`/EnvironmentFile for the key (no shell history),
  the 1–4 h fingerprint cost on a Pi + active cooling, run-against-the-content-mount-not-the-boot-SD
  (A6), `--dry-run` first, and the §7 re-scan.
- **P5-9 — Phase-5 deep-dive** (full-seven) + housekeeping. Gate: CONFIRM, no CRITICAL/HIGH.

## §21 resolution coverage

**Implemented:** offline-tagging stack (design §157/§495) WITHOUT new deps (httpx+mutagen+fpcalc),
R16 typed results, R18/R19 deterministic thresholded selection, R21 lazy-import discipline, H22 +
the `client=` scrub fix, H14 timeouts, A6 (atomic write + SD-wear guidance). **Reused:** catalog
scanner / `mutagen` (Phase 0), `dj/_http.py` seam (Phase 3), per-unit isolation (Phase 4), `main(argv,
*, deps)` (P4-8), `scrub_secrets` (extended). **Deferred (honest):** AcoustID submission, album-art,
disambiguation UI, parallel fingerprinting (rate-limit + Pi cores make it pointless), a persisted
processed-ledger (the skip-tagged gate gives idempotent results; the re-fetch cost for partially-
tagged files is documented — Rev-1 Field-Op MEDIUM).

## Risks & hardening

- **H-T1 throttle/ban (DA CRITICAL, now fixed)** → BOTH services rate-limited via the tested limiter;
  retry honors `Retry-After` and re-arms spacing; required descriptive UA with contact.
- **H-T2 wrong-match corruption (DA/QA HIGH, now fixed)** → `_MIN_ACOUSTID_SCORE` floor (below →
  no-op), fill-not-overwrite default, `--dry-run` first, plan logged for audit.
- **H-T3 fpcalc missing/wrong** → STARTUP fail-fast with the `apt install libchromaprint-tools`
  remedy (not a mid-run stack trace).
- **H-T4 huge library / interrupted run** → `--limit`, stable order, skip-tagged resume (re-fetch
  cost for partially-tagged files documented); **atomic temp+rename so a power loss never corrupts a
  file** (Rev-2 RPi/DA).
- **H-T5 key leak (Field-Op CRITICAL, now fixed)** → key only at the URL seam; `scrub_secrets` gains
  the `client=`/`token=` pattern; tested.
- **H-T6 broadcast contention (RPi CRITICAL, now fixed)** → `nice -n 19` + `ionice -c3` for the run +
  fpcalc; a startup WARN if the daemon looks live; runbook says tag when off-air. (Correcting Rev-1's
  wrong "wall-clock dominated by the rate limit" — with skip-tagged it is fingerprint/CPU-dominated.)

## Acceptance checklist

- [ ] Standalone CLI; daemon never imports `tagging`; **no new PyPI dep** (httpx+mutagen+fpcalc only).
- [ ] BOTH AcoustID + MusicBrainz rate-limited via an injected-clock limiter; retry re-arms spacing.
- [ ] `_MIN_ACOUSTID_SCORE` floor + fill-not-overwrite + named tie-break (R19); `--force`/`--dry-run`.
- [ ] Atomic temp+rename tag write; mutagen round-trip tested IN CI (no `@hardware`).
- [ ] H22 key-by-env-name + `client=` scrub; never logged. Startup fail-fast on missing fpcalc/key/UA.
- [ ] Per-file isolation; deterministic ordered `--limit`; summary; nice/ionice; broadcast-running WARN.
- [ ] R21: zero network/binary on CI; pure logic fully unit-tested; live smokes marked.
- [ ] `docs/ops/tagging.md` runbook (key acquisition w/o shell history, Pi cost/cooling, SD guidance).
