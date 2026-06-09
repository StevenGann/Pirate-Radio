"""RED tests for ``pirate_radio.tagging.__main__`` — Phase-5 P5-8 (the CLI).

``main(argv, *, deps)`` is the testable seam: configure logging FIRST, then **startup fail-fast**
(fpcalc present, key env set, User-Agent non-empty — before any walking/fingerprinting), then run.
All side-effecting collaborators are injected so this runs with fakes — no fpcalc, no net, no FS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pirate_radio.errors import ConfigError
from pirate_radio.tagging.__main__ import TagMainDeps, main
from pirate_radio.tagging.tagger import TagSummary


@dataclass
class _Recorder:
    order: list[str] = field(default_factory=list)
    log_level: str | None = None
    run_args: Any = None
    preflight_fail: Exception | None = None

    def configure_logging(self, level: str) -> None:
        self.order.append("log")
        self.log_level = level

    def preflight(self, args: Any) -> None:
        self.order.append("preflight")
        if self.preflight_fail is not None:
            raise self.preflight_fail

    def run(self, args: Any) -> TagSummary:
        self.order.append("run")
        self.run_args = args
        return TagSummary(tagged=3, skipped=1, failed=0, total=4)


def _deps(rec: _Recorder) -> TagMainDeps:
    return TagMainDeps(
        configure_logging=rec.configure_logging, preflight=rec.preflight, run=rec.run
    )


_BASE = ["--content-dir", "/lib", "--user-agent", "PiRate/1.0 ( me@x.com )"]


def test_configures_logging_before_preflight_before_run() -> None:
    rec = _Recorder()
    assert main(_BASE, deps=_deps(rec)) == 0
    assert rec.order == ["log", "preflight", "run"]


def test_preflight_failure_exits_nonzero_and_does_not_run() -> None:
    rec = _Recorder(preflight_fail=ConfigError("fpcalc not found"))
    rc = main(_BASE, deps=_deps(rec))
    assert rc == 2 and "run" not in rec.order  # fail fast BEFORE touching the library


def test_threads_dry_run_force_and_limit_to_run() -> None:
    rec = _Recorder()
    main([*_BASE, "--dry-run", "--force", "--limit", "5"], deps=_deps(rec))
    assert rec.run_args.dry_run is True
    assert rec.run_args.force is True
    assert rec.run_args.limit == 5


def test_defaults_are_safe() -> None:
    rec = _Recorder()
    main(_BASE, deps=_deps(rec))
    assert rec.run_args.dry_run is False and rec.run_args.force is False
    assert rec.run_args.limit is None
    assert rec.run_args.acoustid_key_env == "ACOUSTID_API_KEY"  # documented default env var name
