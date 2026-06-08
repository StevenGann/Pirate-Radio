"""The Sleeper seam (P2 / R21): an injectable clock-wait.

Production wires ``RealSleeper`` (``asyncio.sleep``); tests wire ``VirtualSleeper``,
which records the requested waits and returns after a single event-loop yield — so the
pipeline's refill-deadline logic is exercised in virtual time, with zero wall-clock
sleeps in the test suite (R21).
"""

from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable


@runtime_checkable
class Sleeper(Protocol):
    """Awaitable wait of ``seconds``. The pipeline's only time-advancing dependency."""

    async def sleep(self, seconds: float) -> None: ...


class RealSleeper:
    """Production sleeper: a genuine ``asyncio.sleep``."""

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class VirtualSleeper:
    """Test sleeper: records each requested wait and yields once (never wall-clock, R21).

    The single ``await asyncio.sleep(0)`` is load-bearing — it hands control back to the
    event loop so a concurrently-scheduled producer can make progress while the player
    "waits", instead of the player starving it and firing spurious backstops.
    """

    def __init__(self) -> None:
        self.slept: list[float] = []

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        await asyncio.sleep(0)  # yield, do not burn wall-clock
