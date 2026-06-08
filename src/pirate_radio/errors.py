"""Phase-0 exception hierarchy for PiRate Radio.

A single project root (``PirateRadioError``) lets callers catch everything from the
package with one ``except``. Phase-0 leaf types cover the failure classes this phase
can raise: config, grid validation, grid resolution, catalog scanning, and
persisted-state corruption. The provider/failover taxonomy (R15: ``ProviderError``
-> ``ProviderUnavailable``/``ProviderQuotaExceeded``/``ProviderFatal``) is
intentionally NOT here yet — it is Phase 3 and will attach under
``PirateRadioError`` without disturbing these leaves.

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


class StateCorruptionError(PirateRadioError):
    """Persisted state and its .bak are both unreadable/invalid (R6 last resort).

    Carries the offending path so the caller can decide to regenerate. Raising this
    is the explicit *signal* that recovery via .bak failed and the caller must
    regenerate from source — it is NOT a crash-loop trigger (R6).
    """

    def __init__(self, message: str, *, path: Path) -> None:
        super().__init__(message)
        self.path = path
