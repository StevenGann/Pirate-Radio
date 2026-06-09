"""External clients for the offline tagger (Phase 5): the rate limiter + the `fpcalc` fingerprinter.

P5-3 ships the `RateLimiter` (the ban-prevention invariant — deficit math against an injected
monotonic clock, with a throttle re-arm) and `FpcalcFingerprinter` (the Chromaprint subprocess seam:
argv-build + `-json` parse PURE; only `subprocess.run` is hardware). P5-4/P5-5 add the AcoustID +
MusicBrainz HTTP clients here, both going through their own `RateLimiter` (≈3 req/s and ≤1 req/s).
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

from pirate_radio.errors import TaggingFatal
from pirate_radio.tagging.models import Fingerprint

_FPCALC_LENGTH_SECONDS = 120  # fingerprint only the first 120 s — bounds per-file CPU (RPi)


class RateLimiter:
    """Spaces calls to one service by ``min_interval_seconds`` (H-T1: AcoustID ≈3 req/s → 0.34 s,
    MusicBrainz ≤1 req/s → 1.0 s). ``acquire`` sleeps only the REMAINING deficit computed from the
    injected monotonic ``clock`` (a call after the interval already elapsed sleeps zero). A ``429``/
    ``503`` calls ``note_throttle`` to push the next call out by ``Retry-After`` (re-arming the
    spacing) so a retry never hammers a service that is already signalling overload."""

    def __init__(
        self,
        min_interval_seconds: float,
        *,
        clock: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        self._min = min_interval_seconds
        self._clock = clock
        self._sleep = sleep
        self._next_allowed: float | None = None

    def acquire(self) -> None:
        now = self._clock()
        if self._next_allowed is None:
            self._next_allowed = now + self._min  # first call: no wait, arm the next slot
            return
        wait = self._next_allowed - now
        if wait > 0:
            self._sleep(wait)
        # the call happens at the later of now / the armed slot; next slot is +interval from there
        self._next_allowed = max(now, self._next_allowed) + self._min

    def note_throttle(self, retry_after_seconds: float | None) -> None:
        """A throttle response: push the next allowed call out by ``Retry-After`` (>= one interval),
        so the following ``acquire`` waits the backoff and the spacing stays intact."""
        delay = max(self._min, retry_after_seconds if retry_after_seconds else self._min)
        self._next_allowed = self._clock() + delay


def build_fpcalc_argv(binary: str, path: str, *, length: int = _FPCALC_LENGTH_SECONDS) -> list[str]:
    """PURE: the `fpcalc` argv — JSON output, a bounded fingerprint window, the file last."""
    return [binary, "-json", "-length", str(length), path]


def parse_fpcalc_json(stdout: bytes) -> Fingerprint:
    """PURE: `fpcalc -json` stdout -> ``Fingerprint``. Bad JSON / missing fields -> ``TaggingFatal``
    (skip the file; never a bare ``KeyError``/``JSONDecodeError``)."""
    try:
        data = json.loads(stdout)
        return Fingerprint(duration=data["duration"], fingerprint=data["fingerprint"])
    except Exception as exc:  # noqa: BLE001 — JSONDecodeError, KeyError, ValidationError -> typed
        raise TaggingFatal(f"fpcalc: unparseable output ({type(exc).__name__})") from exc


class FpcalcFingerprinter:
    """Computes a Chromaprint fingerprint via the `fpcalc` subprocess. The blocking `subprocess.run`
    is injectable (``runner``) so tests need no binary; the default real runner is the only hardware
    line (R20/pragma). The argv/parse around it is PURE."""

    def __init__(
        self,
        *,
        binary: str = "fpcalc",
        length: int = _FPCALC_LENGTH_SECONDS,
        timeout_seconds: float = 120.0,  # H14
        runner: Callable[[list[str]], subprocess.CompletedProcess[bytes]] | None = None,
    ) -> None:
        self._binary = binary
        self._length = length
        self._timeout = timeout_seconds
        self._run = runner or self._default_runner

    def fingerprint(self, path: Path) -> Fingerprint:
        argv = build_fpcalc_argv(self._binary, str(path), length=self._length)
        try:
            proc = self._run(argv)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise TaggingFatal(f"fpcalc: {type(exc).__name__} running {self._binary!r}") from exc
        if proc.returncode != 0:
            raise TaggingFatal(
                f"fpcalc exited {proc.returncode} for {path}: "
                f"{proc.stderr.decode('utf-8', 'replace').strip()}"
            )
        return parse_fpcalc_json(proc.stdout)

    def _default_runner(
        self, argv: list[str]
    ) -> subprocess.CompletedProcess[bytes]:  # pragma: no cover (R20: the only hardware line)
        return subprocess.run(argv, capture_output=True, check=False, timeout=self._timeout)
