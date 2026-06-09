"""The project-wide exception hierarchy for PiRate Radio.

A single project root (``PirateRadioError``) lets callers catch everything from the
package with one ``except``. The assembled taxonomy (phases 0–6): config / grid
validation / grid resolution / catalog scanning / persisted-state corruption leaves;
the provider/failover subtree (R15: ``ProviderError`` -> ``ProviderUnavailable`` /
``ProviderQuotaExceeded`` / ``ProviderFatal``, used by the ranked-failover layer and
the R11 backstop); and the offline-tagger subtree (``TaggingError`` ->
``TaggingUnavailable`` / ``TaggingThrottled`` / ``TaggingFatal``).

Validators raise the *most specific* leaf, and every message is actionable and
free of secrets (security rule). ``StateCorruptionError`` is the only leaf carrying
structured data (the offending path), because R6 recovery branches on it.
"""

from __future__ import annotations

from pathlib import Path


class PirateRadioError(Exception):
    """Root of every error raised by PiRate Radio."""


class ConfigError(PirateRadioError):
    """config.json is missing, malformed, or fails fail-fast validation (§12)."""


class GridValidationError(PirateRadioError):
    """A grid file is missing, malformed, or violates §8.3 validation rules."""


class GridResolutionError(PirateRadioError):
    """No applicable grid file could be resolved for a station/day (§8.2)."""


class CatalogError(PirateRadioError):
    """The content directory cannot be scanned (missing root, no groups, etc.)."""


class ScheduleError(PirateRadioError):
    """Schedule generation cannot proceed (§8.4) — e.g. a grid slot references a group
    with no pool in the catalog. Defense-in-depth: config-load validation
    (``validate_grid_against_catalog``) normally catches this first, but the generator
    raises this typed error rather than a bare ``KeyError`` if it ever slips through."""


class StateCorruptionError(PirateRadioError):
    """Persisted state and its .bak are both unreadable/invalid (R6 last resort).

    Carries the offending path so the caller can decide to regenerate. Raising this
    is the explicit *signal* that recovery via .bak failed and the caller must
    regenerate from source — it is NOT a crash-loop trigger (R6).
    """

    def __init__(self, message: str, *, path: Path) -> None:
        super().__init__(message)
        self.path = path


class TaggingError(PirateRadioError):
    """Base for the offline tagger (Phase 5). Sub-leaves let the backoff path branch: a transient
    or throttled lookup is retried/backed-off; a fatal one (bad config, missing binary, unparseable
    response) skips the file (or fails fast at startup). Never raised on the broadcast path."""


class TaggingUnavailable(TaggingError):
    """Transient tagger failure (connection refused/timeout, 5xx) — retry/backoff."""


class TaggingThrottled(TaggingError):
    """Rate/throttle response (HTTP 429/503). Carries an optional ``Retry-After`` the backoff honors
    before re-arming the limiter so the next normal call still respects the per-service spacing."""

    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class TaggingFatal(TaggingError):
    """Non-retryable tagger failure: missing ``fpcalc``, unset key/UA, unparseable output, a
    degenerate file. Fails fast at startup, or skips the one file mid-batch (per-file isolation)."""


class ProviderError(PirateRadioError):
    """Base for any TTS/LLM/decode backend failure (R15).

    Failover (Phase 3) retries only the *retryable* branch (``ProviderUnavailable`` /
    ``ProviderQuotaExceeded``); ``ProviderFatal`` is terminal for that provider. In
    Phase 1 the pipeline treats ANY ``ProviderError`` as "render failed -> fire the
    R11 backstop, never dead air".
    """


class ProviderUnavailable(ProviderError):
    """Transient: connection refused/timeout, 5xx, model loading. Retryable."""


class ProviderQuotaExceeded(ProviderError):
    """Rate/credit limit hit (HTTP 429 / quota). Retryable against the NEXT provider."""


class ProviderFatal(ProviderError):
    """Non-retryable for this provider: bad request, auth failure, unsupported input."""
