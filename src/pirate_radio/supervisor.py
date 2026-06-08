"""In-process supervision — R7 tier-2 (§5.4 "let it crash").

Each station runs as an ``asyncio`` task; on a crash the supervisor restarts it to KNOWN-GOOD state
(re-entering ``run()``, which reloads/re-anchors from disk — R6/R12) with **sibling isolation** (one
crash never cancels another) and a backoff via the injected ``Sleeper`` (virtual-time-testable). A
render-poison item (``PoisonItemError``, a non-``ProviderError`` crash carrying the item index) is
**advanced past** after K crashes attributed to that index — skip + backstop its slot — keyed on the
item INDEX (NOT a clock offset, which drifts every restart), so a poison item never infinite-loops
(Phase-4 C2 fix). A **bounded skip budget** stops an all-poison schedule from skipping forever; the
**consecutive-restart ceiling** escalates non-poison flapping via the injected ``on_escalate``,
then **stops supervising that unit** (returns — a no-op handler can never leave an in-process loop).
In prod ``on_escalate`` must be TERMINAL: use ``os._exit(...)`` (immediate, so systemd tier-1
restarts the whole process) — NOT ``sys.exit()``, whose ``SystemExit`` ``asyncio.gather`` would
convert to ``CancelledError`` and swallow. A native SIGSEGV cannot be caught here — that is
explicitly the systemd tier's job (R7).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable, Sequence
from typing import Protocol, runtime_checkable

from pirate_radio.pipeline.timing import Sleeper
from pirate_radio.status import StationState, StationStatus

logger = logging.getLogger(__name__)

_DEFAULT_BACKOFF_SECONDS = 5.0
_DEFAULT_MAX_CONSECUTIVE_RESTARTS = 5  # non-poison flapping -> escalate to systemd
_DEFAULT_POISON_THRESHOLD = 3  # K crashes on one item index before skipping its slot
_DEFAULT_MAX_SKIPS = (
    50  # a station needing more skips than this is fundamentally broken -> escalate
)

# Multi-pattern secret scrub (H22 / Phase-3 deep-dive carry-forward): redact common credential
# shapes from any exception text BEFORE it reaches a log record. Defense-in-depth — our own code
# never logs secret values, but a bubbled-up third-party exception might embed one.
_SCRUB_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(//[^/\s:@]+:)[^/\s@]+(@)"), r"\1<redacted>\2"),  # url user:PASS@host
    (re.compile(r"(Bearer\s+)\S+", re.IGNORECASE), r"\1<redacted>"),
    (re.compile(r"(Authorization:\s*Basic\s+)\S+", re.IGNORECASE), r"\1<redacted>"),
    (
        re.compile(r'((?:xi-api-key|api[_-]?key)"?\s*[:=]\s*"?)[^"\s,}]+', re.IGNORECASE),
        r"\1<redacted>",
    ),
    (re.compile(r"\bsk-\S+"), "<redacted>"),  # bare sk-... tokens (Anthropic/OpenAI shape)
]


def scrub_secrets(message: str) -> str:
    """Redact known credential shapes (Bearer, sk-…, xi-api-key, api_key, Basic auth, URL
    userinfo) from ``message``. PURE; the supervisor scrubs every crash message it logs."""
    out = message
    for pattern, repl in _SCRUB_PATTERNS:
        out = pattern.sub(repl, out)
    return out


@runtime_checkable
class Supervisable(Protocol):
    """A supervised unit: a ``name`` + an awaitable ``run()``. ``skip_item(index)`` is OPTIONAL —
    a general advance-past-poison capability for any future unit that raises ``PoisonItemError``;
    the ``Station`` does NOT implement it (its producer backstops render-poison in-band)."""

    name: str

    async def run(self) -> None: ...


class Supervisor:
    def __init__(
        self,
        *,
        sleeper: Sleeper,
        on_escalate: Callable[[], None],
        backoff_seconds: float = _DEFAULT_BACKOFF_SECONDS,
        max_consecutive_restarts: int = _DEFAULT_MAX_CONSECUTIVE_RESTARTS,
        poison_threshold: int = _DEFAULT_POISON_THRESHOLD,
        max_skips: int = _DEFAULT_MAX_SKIPS,
        on_status: Callable[[StationStatus], None] | None = None,
    ) -> None:
        self._sleeper = sleeper
        self._on_escalate = on_escalate
        self._backoff = backoff_seconds
        self._max_consecutive = max_consecutive_restarts
        self._poison_threshold = poison_threshold
        self._max_skips = max_skips
        self._on_status = on_status  # the coordinator registry: stamp CRASHED/RESTARTING here

    def _status(self, name: str, state: StationState, **kw: object) -> None:
        if self._on_status is not None:
            self._on_status(StationStatus(name=name, state=state, **kw))  # type: ignore[arg-type]

    async def run(self, units: Sequence[Supervisable]) -> None:
        """Supervise every unit concurrently; a crash/escalation in one never cancels a sibling."""
        await asyncio.gather(*(self._supervise(unit) for unit in units))

    async def _supervise(self, unit: Supervisable) -> None:
        consecutive = 0
        poison: dict[int, int] = {}
        skips = 0
        while True:
            try:
                await unit.run()
                return  # ran to completion (clean shutdown / end of work)
            except asyncio.CancelledError:
                raise  # cooperative shutdown — never a crash, never swallowed
            except Exception as exc:  # noqa: BLE001 — re-typed/classified below
                scrubbed = scrub_secrets(str(exc))
                index = getattr(exc, "item_index", None)
                skip_item = getattr(unit, "skip_item", None)
                if index is not None and skip_item is not None:
                    poison[index] = poison.get(index, 0) + 1
                    if poison[index] >= self._poison_threshold:
                        if skips >= self._max_skips:
                            logger.critical(
                                "%s: skip budget %d exhausted (schedule too broken) -> escalating "
                                "(R7)",
                                unit.name,
                                self._max_skips,
                            )
                            self._on_escalate()
                            return
                        logger.critical(
                            "%s: item %d render-poisoned after %d crashes -> skipping slot (%s)",
                            unit.name,
                            index,
                            poison[index],
                            scrubbed,
                        )
                        skip_item(index)
                        skips += 1
                        consecutive = 0
                        poison[index] = 0
                    await self._sleeper.sleep(self._backoff)  # cancellation here propagates (clean)
                    continue
                # non-poison crash, or a poison item on a unit that cannot skip -> the ceiling path
                consecutive += 1
                self._status(
                    unit.name, StationState.CRASHED, restart_count=consecutive, last_error=scrubbed
                )
                logger.warning(
                    "%s: crashed (%s) -> restart %d/%d (R7/§5.4)",
                    unit.name,
                    scrubbed,
                    consecutive,
                    self._max_consecutive,
                )
                if consecutive >= self._max_consecutive:
                    logger.critical(
                        "%s: %d consecutive restarts -> escalating to the systemd tier (R7)",
                        unit.name,
                        consecutive,
                    )
                    self._on_escalate()
                    return
                self._status(
                    unit.name,
                    StationState.RESTARTING,
                    restart_count=consecutive,
                    last_error=scrubbed,
                )
                await self._sleeper.sleep(self._backoff)  # then re-enter run() (known-good, R6/R12)
