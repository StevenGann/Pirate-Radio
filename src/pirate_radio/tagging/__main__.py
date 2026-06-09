"""``python -m pirate_radio.tagging`` — the offline tagger CLI (Phase 5, P5-8).

``main(argv, *, deps)`` is the testable seam: configure logging FIRST, then **startup fail-fast**
(fpcalc present, key env set, User-Agent non-empty — before any walking/fingerprinting), then run.
Side-effecting collaborators are injected; only ``_prod_deps`` (the real fpcalc/network wiring +
process-priority drop) is hardware/network-adjacent (``pragma: no cover``).
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from dataclasses import dataclass

from pirate_radio.errors import ConfigError, TaggingError
from pirate_radio.tagging.selection import _MIN_ACOUSTID_SCORE
from pirate_radio.tagging.tagger import TagSummary

logger = logging.getLogger(__name__)

_DEFAULT_KEY_ENV = "ACOUSTID_API_KEY"


@dataclass(frozen=True)
class TagMainDeps:
    """Injected collaborators (prod wires the real ones; tests wire fakes)."""

    configure_logging: Callable[[str], None]
    preflight: Callable[[argparse.Namespace], None]  # startup fail-fast; raises Config/TaggingError
    run: Callable[[argparse.Namespace], TagSummary]


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pirate_radio.tagging", description="Offline AcoustID/MusicBrainz batch tagger"
    )
    parser.add_argument("--content-dir", required=True, help="library root to tag")
    parser.add_argument(
        "--user-agent",
        required=True,
        help="MusicBrainz User-Agent WITH contact, e.g. 'PiRate/1.0 ( you@example.com )'",
    )
    parser.add_argument(
        "--acoustid-key-env",
        default=_DEFAULT_KEY_ENV,
        help=f"env var holding the AcoustID API key (default: {_DEFAULT_KEY_ENV})",
    )
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--dry-run", action="store_true", help="log planned tags, write nothing")
    parser.add_argument(
        "--force", action="store_true", help="overwrite existing tags, not just fill"
    )
    parser.add_argument("--limit", type=int, default=None, help="tag at most N files (trial run)")
    parser.add_argument("--min-score", type=float, default=_MIN_ACOUSTID_SCORE)
    return parser.parse_args(argv)


def main(argv: list[str], *, deps: TagMainDeps) -> int:
    args = _parse_args(argv)
    deps.configure_logging(args.log_level)  # FIRST: a preflight error is logged through the stream
    try:
        deps.preflight(args)  # fail fast BEFORE walking/fingerprinting the library
    except (ConfigError, TaggingError) as exc:
        logger.error("tagging preflight failed: %s", exc)
        return 2
    summary = deps.run(args)
    logger.info(
        "done: %d tagged, %d skipped, %d failed of %d",
        summary.tagged,
        summary.skipped,
        summary.failed,
        summary.total,
    )
    return 0


def _preflight(args: argparse.Namespace) -> None:  # pragma: no cover (probes the real host)
    import os
    import shutil

    if shutil.which("fpcalc") is None:
        raise ConfigError("fpcalc not found — install it: sudo apt install libchromaprint-tools")
    if not os.environ.get(args.acoustid_key_env, "").strip():
        raise ConfigError(f"AcoustID key env var {args.acoustid_key_env!r} is not set or empty")
    if not args.user_agent.strip():
        raise ConfigError("--user-agent must be a non-empty descriptive string with contact info")
    _warn_if_broadcasting()


def _warn_if_broadcasting() -> None:  # pragma: no cover (best-effort host probe)
    import shutil
    import subprocess

    systemctl = shutil.which("systemctl")
    if systemctl is None:
        return
    try:
        result = subprocess.run(
            [systemctl, "is-active", "pirate-radio"], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return
    if result.stdout.strip() == "active":
        logger.warning(
            "pirate-radio daemon appears ACTIVE — tagging contends for CPU/IO and can glitch the "
            "live stations; stop it or run off-peak (H-T6)"
        )


def _run(args: argparse.Namespace) -> TagSummary:  # pragma: no cover (real fpcalc + network wiring)
    import time
    from pathlib import Path

    from pirate_radio.tagging.clients import (
        _ACOUSTID_INTERVAL_SECONDS,
        _MUSICBRAINZ_INTERVAL_SECONDS,
        AcoustIdClient,
        FpcalcFingerprinter,
        MusicBrainzClient,
        RateLimiter,
    )
    from pirate_radio.tagging.tagger import tag_library

    acoustid = AcoustIdClient(
        args.acoustid_key_env,
        limiter=RateLimiter(_ACOUSTID_INTERVAL_SECONDS, clock=time.monotonic, sleep=time.sleep),
    )
    musicbrainz = MusicBrainzClient(
        args.user_agent,
        limiter=RateLimiter(_MUSICBRAINZ_INTERVAL_SECONDS, clock=time.monotonic, sleep=time.sleep),
    )
    return tag_library(
        content_dir=Path(args.content_dir),
        fingerprinter=FpcalcFingerprinter(),
        acoustid=acoustid,
        musicbrainz=musicbrainz,
        force=args.force,
        dry_run=args.dry_run,
        limit=args.limit,
        min_score=args.min_score,
    )


def _prod_deps() -> TagMainDeps:  # pragma: no cover - the real wiring
    from pirate_radio.logging_setup import configure_logging

    return TagMainDeps(configure_logging=configure_logging, preflight=_preflight, run=_run)


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    import sys

    raise SystemExit(main(sys.argv[1:], deps=_prod_deps()))
