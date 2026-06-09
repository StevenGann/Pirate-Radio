"""External clients for the offline tagger (Phase 5): the rate limiter + the `fpcalc` fingerprinter.

P5-3 ships the `RateLimiter` (the ban-prevention invariant — deficit math against an injected
monotonic clock, with a throttle re-arm) and `FpcalcFingerprinter` (the Chromaprint subprocess seam:
argv-build + `-json` parse PURE; only `subprocess.run` is hardware). P5-4/P5-5 add the AcoustID +
MusicBrainz HTTP clients here, both going through their own `RateLimiter` (≈3 req/s and ≤1 req/s).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from pirate_radio.errors import (
    ConfigError,
    TaggingFatal,
    TaggingThrottled,
    TaggingUnavailable,
)
from pirate_radio.tagging.models import AcoustIdMatch, Fingerprint, RecordingMetadata

_FPCALC_LENGTH_SECONDS = 120  # fingerprint only the first 120 s — bounds per-file CPU (RPi)
_ACOUSTID_URL = "https://api.acoustid.org/v2/lookup"
_ACOUSTID_INTERVAL_SECONDS = 0.34  # AcoustID ≈3 req/s per key
_MUSICBRAINZ_URL = "https://musicbrainz.org/ws/2"
_MUSICBRAINZ_INTERVAL_SECONDS = 1.0  # MusicBrainz policy: ≤1 req/s per IP
_DEFAULT_MAX_RETRIES = 3
_YEAR_RE = re.compile(r"\b(\d{4})\b")

# the injected sync GET seam: (url, *, params, headers) -> parsed JSON dict (raises TaggingError)
GetJson = Callable[..., dict[str, object]]


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


def request_json(
    get_json: GetJson,
    limiter: RateLimiter,
    *,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    **kwargs: object,
) -> dict[str, object]:
    """Rate-limited GET with retry-and-rearm (shared by AcoustID + MusicBrainz). Each attempt waits
    its limiter slot; a ``TaggingThrottled`` (429/503) re-arms the limiter by ``Retry-After`` and
    retries, so a throttled service is never hammered. All throttled -> ``TaggingUnavailable``."""
    last: TaggingThrottled | None = None
    for _ in range(max_retries):
        limiter.acquire()
        try:
            return get_json(**kwargs)
        except TaggingThrottled as exc:
            limiter.note_throttle(exc.retry_after_seconds)
            last = exc
    raise TaggingUnavailable(f"request throttled after {max_retries} attempts") from last


def acoustid_key(env_name: str) -> str:
    """Read the AcoustID key from the env BY NAME at call time (H22). The error names the VAR,
    never a value; the key is placed only in the request params at the GET seam, never logged."""
    value = os.environ.get(env_name, "").strip()
    if not value:
        raise TaggingFatal(f"AcoustID key env var {env_name!r} is not set or empty")
    return value


def build_acoustid_params(key: str, fingerprint: Fingerprint) -> dict[str, object]:
    """PURE: the AcoustID lookup query params (integer duration; recordings metadata requested)."""
    return {
        "client": key,
        "duration": int(fingerprint.duration),
        "fingerprint": fingerprint.fingerprint,
        "meta": "recordings",
    }


def parse_acoustid_response(data: dict[str, object]) -> tuple[AcoustIdMatch, ...]:
    """PURE: AcoustID JSON -> recording matches (MBID + result score), sorted highest-first. A
    non-``ok`` status is ``TaggingFatal``; missing fields are tolerated (sparse is fine)."""
    if data.get("status") != "ok":
        raise TaggingFatal(f"acoustid: status {data.get('status')!r}")
    matches: list[AcoustIdMatch] = []
    for result in cast("list[dict[str, Any]]", data.get("results", [])):
        score = result.get("score")
        if score is None:
            continue
        for rec in result.get("recordings", []):
            rid = rec.get("id")
            if rid:
                matches.append(AcoustIdMatch(recording_id=rid, score=score))
    return tuple(sorted(matches, key=lambda m: (-m.score, m.recording_id)))


class AcoustIdClient:
    """AcoustID lookup over the injected sync GET seam, rate-limited (≈3 req/s) with retry-rearm."""

    def __init__(
        self,
        api_key_env: str,
        *,
        limiter: RateLimiter,
        get_json: GetJson | None = None,
        base_url: str = _ACOUSTID_URL,
    ) -> None:
        self._key_env = api_key_env
        self._limiter = limiter
        self._get_json = get_json or _default_get_json
        self._url = base_url

    def lookup(self, fingerprint: Fingerprint) -> tuple[AcoustIdMatch, ...]:
        params = build_acoustid_params(acoustid_key(self._key_env), fingerprint)
        data = request_json(self._get_json, self._limiter, url=self._url, params=params)
        return parse_acoustid_response(data)


def _default_get_json(  # pragma: no cover (R20/R21: the only network line; tests inject get_json)
    url: str, *, params: dict[str, object] | None = None, headers: dict[str, str] | None = None
) -> dict[str, object]:
    import httpx  # lazy (R21)

    try:
        resp = httpx.get(url, params=cast("Any", params), headers=headers, timeout=20.0)
    except Exception as exc:  # noqa: BLE001 — transport error -> retryable
        raise TaggingUnavailable(f"GET {url} failed: {type(exc).__name__}") from exc
    if resp.status_code in (429, 503):
        retry_after = resp.headers.get("Retry-After")
        raise TaggingThrottled(
            f"{resp.status_code} from {url}",
            retry_after_seconds=float(retry_after)
            if retry_after and retry_after.isdigit()
            else None,
        )
    if resp.status_code >= 400:
        raise TaggingFatal(f"{resp.status_code} from {url}")
    return cast("dict[str, object]", resp.json())


def build_musicbrainz_url(mbid: str, *, base_url: str = _MUSICBRAINZ_URL) -> str:
    """PURE: the MusicBrainz recording lookup URL — JSON, with artist + release sub-queries."""
    return f"{base_url.rstrip('/')}/recording/{mbid}?fmt=json&inc=artists+releases"


def _parse_year(date_str: object) -> int | None:
    """PURE: a leading 4-digit year from an MB date (``YYYY`` / ``YYYY-MM-DD``), bounded 1..9999."""
    if not isinstance(date_str, str):
        return None
    m = _YEAR_RE.search(date_str)
    if not m:
        return None
    year = int(m.group(1))
    return year if 1 <= year <= 9999 else None


def parse_recording(data: dict[str, object]) -> RecordingMetadata:
    """PURE: an MB recording JSON -> ``RecordingMetadata``. Artist is the joined artist-credit;
    album + year come from the first release. Every field is best-effort (sparse is fine)."""
    title = data.get("title")
    credit = cast("list[dict[str, Any]]", data.get("artist-credit", []))
    artist = "".join(c.get("name", "") + c.get("joinphrase", "") for c in credit).strip() or None
    releases = cast("list[dict[str, Any]]", data.get("releases", []))
    album = year = None
    if releases:
        album = releases[0].get("title")
        year = _parse_year(releases[0].get("date"))
    return RecordingMetadata(
        title=title if isinstance(title, str) else None,
        artist=artist,
        album=album if isinstance(album, str) else None,
        year=year,
    )


class MusicBrainzClient:
    """MusicBrainz recording lookup over the injected sync GET seam, rate-limited to ≤1 req/s with a
    REQUIRED descriptive User-Agent (MB policy — missing → ``ConfigError`` at construction)."""

    def __init__(
        self,
        user_agent: str,
        *,
        limiter: RateLimiter,
        get_json: GetJson | None = None,
        base_url: str = _MUSICBRAINZ_URL,
    ) -> None:
        if not user_agent.strip():
            raise ConfigError(
                "MusicBrainz requires a descriptive User-Agent with contact info "
                "(e.g. 'PiRate/1.0 ( you@example.com )')"
            )
        self._ua = user_agent
        self._limiter = limiter
        self._get_json = get_json or _default_get_json
        self._base_url = base_url

    def recording(self, mbid: str) -> RecordingMetadata:
        url = build_musicbrainz_url(mbid, base_url=self._base_url)
        data = request_json(
            self._get_json, self._limiter, url=url, headers={"User-Agent": self._ua}
        )
        return parse_recording(data)
