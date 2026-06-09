"""In-process supervision — R7 tier-2 (§5.4 "let it crash").

Each station runs as an ``asyncio`` task; on a crash the supervisor restarts it to KNOWN-GOOD state
(re-entering ``run()``, which reloads/re-anchors from disk — R6/R12) with **sibling isolation** (one
crash never cancels another) and a backoff via the injected ``Sleeper`` (virtual-time-testable). The
**consecutive-restart ceiling** escalates flapping via the injected ``on_escalate``, then **stops
supervising that unit** (returns — a no-op handler can never leave an in-process loop). In prod
``on_escalate`` must be TERMINAL: use ``os._exit(...)`` (immediate, so systemd tier-1 restarts the
whole process) — NOT ``sys.exit()``, whose ``SystemExit`` ``asyncio.gather`` would convert to
``CancelledError`` and swallow. A native SIGSEGV cannot be caught here — that is explicitly the
systemd tier's job (R7). (Render-poison is handled IN-BAND by the producer — backstop + a
station-tagged CRITICAL — so a poison item never escapes to the supervisor; there is no skip path.)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from typing import Protocol, runtime_checkable

from pirate_radio.pipeline.timing import Sleeper
from pirate_radio.scrub import scrub_secrets  # canonical home is pirate_radio.scrub
from pirate_radio.status import StationState, StationStatus

__all__ = ["Supervisable", "Supervisor"]

logger = logging.getLogger(__name__)

_DEFAULT_BACKOFF_SECONDS = 5.0
_DEFAULT_MAX_CONSECUTIVE_RESTARTS = 5  # flapping -> escalate to systemd


@runtime_checkable
class Supervisable(Protocol):
    """A supervised unit: a ``name`` + an awaitable ``run()``."""

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
        on_status: Callable[[StationStatus], None] | None = None,
    ) -> None:
        self._sleeper = sleeper
        self._on_escalate = on_escalate
        self._backoff = backoff_seconds
        self._max_consecutive = max_consecutive_restarts
        self._on_status = on_status  # the coordinator registry: stamp CRASHED/RESTARTING here

    def _status(self, name: str, state: StationState, **kw: object) -> None:
        if self._on_status is not None:
            self._on_status(StationStatus(name=name, state=state, **kw))  # type: ignore[arg-type]

    async def run(self, units: Sequence[Supervisable]) -> None:
        """Supervise every unit concurrently; a crash/escalation in one never cancels a sibling."""
        await asyncio.gather(*(self._supervise(unit) for unit in units))

    async def _supervise(self, unit: Supervisable) -> None:
        consecutive = 0
        while True:
            try:
                await unit.run()
                return  # ran to completion (clean shutdown / end of work)
            except asyncio.CancelledError:
                raise  # cooperative shutdown — never a crash, never swallowed
            except Exception as exc:  # noqa: BLE001 — any crash -> restart-to-known-good (R7/§5.4)
                scrubbed = scrub_secrets(str(exc))
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
