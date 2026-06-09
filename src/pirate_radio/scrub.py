"""Secret scrubbing for the logging path (H22) — a leaf utility, no project deps.

A cross-cutting security concern used by the journald stream handler, the ``/logs`` ring, and a few
crash-log call sites. It lived in ``supervisor.py`` historically; it is here so the offline tagger
and the control API can use it without importing the broadcast supervisor (a coupling that had
nothing to do with supervision — final-review MEDIUM).

``scrub_secrets`` redacts common credential shapes from a message BEFORE it reaches a log record.
Defense-in-depth: our own code never logs secret values, but a bubbled-up third-party exception
might embed one. ``SecretScrubFilter`` makes that scrub a property of the *sink* — attached to a
handler it scrubs EVERY record that handler emits (incl. records our code never scrubbed at the call
site), so a secret can never reach journald/stdout verbatim (final-review HIGH).
"""

from __future__ import annotations

import logging
import re

# Multi-pattern secret scrub (H22 / Phase-3 deep-dive carry-forward): redact common credential
# shapes from any text BEFORE it reaches a log record.
_SCRUB_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(//[^/\s:@]+:)[^/\s@]+(@)"), r"\1<redacted>\2"),  # url user:PASS@host
    (re.compile(r"(Bearer\s+)\S+", re.IGNORECASE), r"\1<redacted>"),
    (re.compile(r"(Authorization:\s*Basic\s+)\S+", re.IGNORECASE), r"\1<redacted>"),
    (
        re.compile(r'((?:xi-api-key|api[_-]?key)"?\s*[:=]\s*"?)[^"\s,}]+', re.IGNORECASE),
        r"\1<redacted>",
    ),
    (re.compile(r"\bsk-\S+"), "<redacted>"),  # bare sk-... tokens (Anthropic/OpenAI shape)
    # API keys carried as a URL query param (AcoustID `?client=<key>`, generic `?token=`) — P5-4.
    (re.compile(r"((?:client|token)=)[^&\s]+", re.IGNORECASE), r"\1<redacted>"),
]


def scrub_secrets(message: str) -> str:
    """Redact known credential shapes (Bearer, sk-…, xi-api-key, api_key, Basic auth, URL
    userinfo, ``client=``/``token=`` query params) from ``message``. PURE."""
    out = message
    for pattern, repl in _SCRUB_PATTERNS:
        out = pattern.sub(repl, out)
    return out


class SecretScrubFilter(logging.Filter):
    """A logging filter that scrubs the FULLY-FORMATTED message of every record it sees, so a
    secret embedded in any handler's output (journald/stdout, the /logs ring) is redacted at the
    sink — not only at the call sites that remembered to scrub. Attach to a handler (handler filters
    run for all records the handler emits, including propagated ones)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = scrub_secrets(record.getMessage())
        record.args = ()  # message is now fully rendered; clear args so it isn't %-formatted again
        return True
