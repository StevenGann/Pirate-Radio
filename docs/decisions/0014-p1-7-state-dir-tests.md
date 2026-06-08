# P1-7 — config `state_dir` (A6: mutable state off the boot SD)

Strict spec-driven TDD: tests authored from plan §4.9 / A6 → confirmed RED → focused
panel reviewed the tests → adopted → implemented to GREEN → gate → commit.

## Panel review of the tests (QA + Senior Dev/RPi Expert + Devil's Advocate)

**Vote: QA NAY, Senior+RPi AYE, DA AYE → 1 NAY → ADOPTED** (charter ≤1 NAY).

**A6 writability ruling — unanimous, and already ratified.** QA surfaced that the A6
narrowing was *already* decided 7/7 in `0009 §Q1`: **only `state_dir` must be writable;
`content_dir`/`schedule_dir` need only be readable** (a curated library + hand-authored
grids on a read-only mount is a good field posture, and requiring write there would block
that deployment). So this increment *implements a ratified decision*, it did not re-open
it. `test_readonly_content_and_schedule_dirs_are_accepted` is the regression guard that
stops a future implementer adding W_OK checks to the other two dirs. (My initial test
comment mis-cited "0014"; corrected to cite 0009 §Q1.)

QA's NAY (and convergent findings from all three) were folded in before GREEN:
- **state_dir pointing at a FILE** (exists but not a dir) was untested — the spec says
  "missing OR not a directory". Added `test_state_dir_pointing_at_a_file_rejected`.
- **Writability untested under a root CI** (root bypasses `os.access(W_OK)`, so the
  chmod-based test only skips). Added `test_unwritable_state_dir_rejected_deterministic`
  that monkeypatches `os.access`→False, giving uid-independent coverage of the W_OK branch;
  kept the real-permissions chmod test (skipped under root) as the integration check.
- **Type + log pinned**: the happy test now asserts `isinstance(cfg.state_dir, Path)` and
  (A6 "log where writes land") a `caplog` INFO assertion that the resolved path is logged.
- **`match=`** added to the state_dir `ConfigError` raises so they fail for the right
  reason, not any earlier ConfigError.

## Scope notes / deferred (panel MINORs, not blocking)

- **Relative-path `state_dir`** policy: Pydantic accepts a relative `Path`; `is_dir()` then
  resolves against CWD, which is undefined at load on a Pi. The plan states no policy;
  deferred (operators pass absolute paths; the systemd unit sets them). Flagged for a
  future `.resolve()`/reject decision.
- `_valid_config` now injects a default `state_dir = schedule_dir.parent` (always an
  existing writable dir under `tmp_path`) so the existing suite stays valid; the DA
  confirmed this cannot mask an existing wrong-dir test (those still fail on the intended
  ConfigError).

## Implementation

- `DaemonConfig.state_dir: Path` (required, no default).
- `_check_state_dir(config)` in `_validate_config`: `is_dir()` then `os.access(W_OK)`, then
  `logger.info("state_dir resolved to %s", sd)`. Daemon-level (one mutable root per
  process; per-station state lives under `state_dir/<station>/` at runtime — Senior Dev).
  Does NOT create the dir (a missing mount must fail loud, not silently fall back to the
  boot SD — RPi Expert).

## Gate

ruff + ruff-format + mypy clean; **257 tests**, 98.56% coverage; config.py 99%.
