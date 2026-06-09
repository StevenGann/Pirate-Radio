"""RED tests for ``pirate_radio.tagging.clients`` — Phase-5 P5-3 (RateLimiter + fpcalc).

The `RateLimiter` is the ban-prevention invariant (H-T1): deficit math against an INJECTED monotonic
clock (back-to-back → sleep the deficit; spaced → sleep zero; a throttle re-arms the spacing). The
`fpcalc` fingerprinter is the subprocess seam: argv-build + `-json` parse are PURE; only the
`subprocess.run` line is hardware. P5-4/P5-5 add the AcoustID + MusicBrainz HTTP clients here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pirate_radio.errors import TaggingFatal
from pirate_radio.tagging.clients import (
    FpcalcFingerprinter,
    RateLimiter,
    build_fpcalc_argv,
    parse_fpcalc_json,
)
from pirate_radio.tagging.models import Fingerprint


class _FakeClock:
    """A settable monotonic clock for the limiter tests (no wall-clock, R21/R18)."""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


# ---- RateLimiter: deficit math against an injected clock (H-T1) ----------------------------
def test_first_call_does_not_sleep() -> None:
    slept: list[float] = []
    RateLimiter(1.0, clock=_FakeClock(), sleep=slept.append).acquire()
    assert slept == []  # nothing to wait for on the first call


def test_back_to_back_calls_sleep_the_deficit() -> None:
    slept: list[float] = []
    clock = _FakeClock()
    rl = RateLimiter(1.0, clock=clock, sleep=slept.append)
    rl.acquire()  # arms next-allowed at t+1.0
    rl.acquire()  # same instant -> must sleep the full 1.0s deficit
    assert slept == [pytest.approx(1.0)]


def test_a_spaced_call_sleeps_zero() -> None:
    slept: list[float] = []
    clock = _FakeClock()
    rl = RateLimiter(1.0, clock=clock, sleep=slept.append)
    rl.acquire()
    clock.t += 5.0  # more than the interval has elapsed
    rl.acquire()
    assert slept == []  # already past the slot -> no wait (a flat-always-sleep impl FAILS here)


def test_a_throttle_rearms_the_spacing() -> None:
    slept: list[float] = []
    clock = _FakeClock()
    rl = RateLimiter(1.0, clock=clock, sleep=slept.append)
    rl.acquire()
    rl.note_throttle(retry_after_seconds=5.0)  # 429/503 -> push the next call out by >= Retry-After
    rl.acquire()
    assert slept == [pytest.approx(5.0)]  # the next normal call waits the backoff, not just 1.0s


def test_throttle_without_retry_after_falls_back_to_the_interval() -> None:
    slept: list[float] = []
    clock = _FakeClock()
    rl = RateLimiter(2.0, clock=clock, sleep=slept.append)
    rl.acquire()
    rl.note_throttle(retry_after_seconds=None)
    rl.acquire()
    assert slept == [pytest.approx(2.0)]  # falls back to one interval


# ---- fpcalc argv + parse (PURE) ------------------------------------------------------------
def test_build_fpcalc_argv_requests_json_and_bounded_length() -> None:
    argv = build_fpcalc_argv("fpcalc", "/lib/x/a.flac", length=120)
    assert argv[0] == "fpcalc"
    assert "-json" in argv and argv[-1] == "/lib/x/a.flac"
    assert "-length" in argv and "120" in argv  # bounds per-file CPU (RPi)


def test_parse_fpcalc_json_extracts_duration_and_fingerprint() -> None:
    out = json.dumps({"duration": 212.34, "fingerprint": "AQAAA"}).encode()
    fp = parse_fpcalc_json(out)
    assert fp == Fingerprint(duration=212.34, fingerprint="AQAAA")


def test_parse_fpcalc_json_rejects_bad_json() -> None:
    with pytest.raises(TaggingFatal):
        parse_fpcalc_json(b"not json")


def test_parse_fpcalc_json_rejects_missing_fields() -> None:
    with pytest.raises(TaggingFatal):
        parse_fpcalc_json(json.dumps({"duration": 1.0}).encode())  # no fingerprint


# ---- FpcalcFingerprinter: subprocess seam (injected runner, no binary) ---------------------
class _FakeProc:
    def __init__(self, *, returncode: int, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_fingerprint_parses_a_successful_run() -> None:
    out = json.dumps({"duration": 100.0, "fingerprint": "FP"}).encode()
    fp = FpcalcFingerprinter(
        binary="fpcalc", runner=lambda argv: _FakeProc(returncode=0, stdout=out)
    ).fingerprint(Path("/lib/x/a.flac"))
    assert fp == Fingerprint(duration=100.0, fingerprint="FP")


def test_fingerprint_nonzero_exit_is_fatal() -> None:
    eng = FpcalcFingerprinter(
        binary="fpcalc", runner=lambda argv: _FakeProc(returncode=1, stderr=b"bad file")
    )
    with pytest.raises(TaggingFatal):
        eng.fingerprint(Path("/lib/x/bad.flac"))
