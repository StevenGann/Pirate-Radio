"""The one shared free-form year parser — a leaf with NO project deps (consolidation, cycle 3).

Three call sites historically re-implemented "pull a bounded 4-digit year out of a messy date
string" (the catalog metadata reader, the MusicBrainz client, the tag writer's existing-tag read).
They now all route through ``parse_year`` so the bound (A10: 1..9999) and the extraction rule live
in exactly one place. ``\\b(\\d{4})\\b`` takes the FIRST standalone 4-digit run (so ``2021-03-04``
-> 2021 and ``03/12/1968`` -> 1968 — the 2-digit groups never match); an out-of-range hit (e.g.
``0000``) yields None, never a crash.
"""

from __future__ import annotations

import re

_YEAR_RE = re.compile(r"\b(\d{4})\b")


def parse_year(value: str | None) -> int | None:
    """Extract a plausible 4-digit year (bounded 1..9999, A10) from a free-form date; None
    otherwise. A non-string / missing / unmatched / out-of-range value yields None, never raises."""
    if not isinstance(value, str):
        return None
    match = _YEAR_RE.search(value)
    if not match:
        return None
    year = int(match.group(1))
    return year if 1 <= year <= 9999 else None
