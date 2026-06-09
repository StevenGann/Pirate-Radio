# P5-8 — `tagging/__main__.py` CLI + `docs/ops/tagging.md` runbook

Strict spec-driven TDD (tests from plan §P5-8 → RED → GREEN → gate).

## Implementation

- **`tagging/__main__.py`** (`python -m pirate_radio.tagging`): `main(argv, *, deps: TagMainDeps)` is
  the testable seam — `configure_logging` FIRST, then **startup fail-fast** `preflight` (before any
  walking/fingerprinting), then `run`; a `ConfigError`/`TaggingError` from preflight → log + exit 2.
  argparse: `--content-dir` (required), `--user-agent` (required, MB policy), `--acoustid-key-env`
  (default `ACOUSTID_API_KEY`), `--dry-run`, `--force`, `--limit`, `--min-score`, `--log-level`.
- `_preflight` (pragma — probes the host): `fpcalc` present (else the `apt install
  libchromaprint-tools` remedy), key env set, UA non-empty.
- `_run` (pragma — real fpcalc/network wiring): builds `FpcalcFingerprinter` + `AcoustIdClient` +
  `MusicBrainzClient` with `RateLimiter(time.monotonic, time.sleep)` and calls `tag_library`.
- **No new dependency / no `[tagging]` extra** (Rev-2 decision): httpx + mutagen are already core; the
  only external requirement is the `fpcalc` binary, documented in the runbook like `libportaudio2`.
- **`docs/ops/tagging.md`** — the operator runbook: when-to-run (not during broadcast; 1–4 h cost),
  `apt install libchromaprint-tools`, `read -s` key entry (no shell history), **dry-run first**, real
  run (fill-not-overwrite default, `--force`, atomic writes, content-mount-not-SD), the summary/logs,
  and the §7 re-scan (`touch` + restart).

## Tests (`tests/tagging/test_tag_main.py`, 4)

logging→preflight→run order; preflight failure → exit 2 + run NOT called; `--dry-run/--force/--limit`
threaded to `run`; safe defaults (`acoustid_key_env == "ACOUSTID_API_KEY"`).

## Gate

ruff + ruff-format + mypy `--strict` clean (55 source files); **792 tests** (+4), 97.43% coverage.

## Next

P5-9: Phase-5 full-seven deep-dive + housekeeping.
