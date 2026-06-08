"""RED tests for ``pirate_radio.pipeline.timing`` — the Sleeper seam (P2 / R21).

Tests first. R21 forbids wall-clock sleeps in tests; the ``Sleeper`` Protocol lets the
pipeline depend on an injectable clock-wait so a ``VirtualSleeper`` can record requested
waits and return instantly (a yield, never a real delay).
"""

import asyncio

from pirate_radio.pipeline.timing import RealSleeper, Sleeper, VirtualSleeper


def test_both_sleepers_satisfy_the_protocol() -> None:
    # @runtime_checkable Protocol: both concrete sleepers must satisfy it structurally.
    assert isinstance(RealSleeper(), Sleeper)
    assert isinstance(VirtualSleeper(), Sleeper)


async def test_virtual_sleeper_records_and_returns_without_waiting() -> None:
    # The whole point (R21): "sleeping" 9999s must return promptly and just be recorded.
    vs = VirtualSleeper()
    await vs.sleep(9999.0)
    await vs.sleep(2.5)
    assert vs.slept == [9999.0, 2.5]


async def test_virtual_sleeper_yields_to_the_event_loop() -> None:
    # CONTRACT (load-bearing for the concurrent pipeline): VirtualSleeper.sleep must yield
    # at least once so a concurrently-scheduled task (e.g. the producer) can make progress
    # while the player "waits". A pure no-op would let the player starve the producer and
    # fire spurious backstops. This pins the yield without any wall-clock.
    ran: list[str] = []

    async def sibling() -> None:
        ran.append("sibling")

    task = asyncio.create_task(sibling())
    await VirtualSleeper().sleep(1.0)  # must hand control to the sibling
    assert ran == ["sibling"]
    await task


async def test_real_sleeper_awaits_zero_without_error() -> None:
    # Exercise the real path with a 0s sleep (a yield) so we never burn wall-clock in CI.
    await RealSleeper().sleep(0.0)
