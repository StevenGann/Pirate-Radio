"""RED tests for ``pirate_radio.supervisor`` — Phase 4 plan §C / P4-3 (R7 tier-2).

The in-process supervisor restarts a crashed station to known-good state (re-entering ``run()``),
with **sibling isolation**, backoff via the injected ``Sleeper``, **advance-past-poison keyed on
the producer-tagged item INDEX** (per-index counting; a render-poison item is skipped after K
crashes; a **bounded skip budget** prevents an all-poison schedule from skipping forever), a
**consecutive-restart ceiling → injected ``on_escalate``** (never a real exit), and
**multi-pattern secret-scrubbed** crash logs. A poison unit that cannot be skipped escalates via
the ceiling (never an infinite loop). Native SIGSEGV is the systemd tier's job (R7), not here.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from pirate_radio.errors import PoisonItemError
from pirate_radio.pipeline.timing import VirtualSleeper
from pirate_radio.supervisor import Supervisable, Supervisor, scrub_secrets


class _Unit:
    """Crashes a scripted number of times, then runs to completion."""

    def __init__(self, name: str, *, crashes: int = 0, exc: Exception | None = None) -> None:
        self.name = name
        self._remaining = crashes
        self._exc = exc or RuntimeError("boom")
        self.runs = 0

    async def run(self) -> None:
        self.runs += 1
        if self._remaining > 0:
            self._remaining -= 1
            raise self._exc


class _PoisonUnit:
    """Raises ``PoisonItemError`` for the first not-yet-skipped index (in order) until all are
    skipped — then ``run()`` completes. Models a render-poison schedule (skip by exc index)."""

    def __init__(self, name: str, *, indices: list[int]) -> None:
        self.name = name
        self._indices = indices
        self._skipped: set[int] = set()
        self.runs = 0

    async def run(self) -> None:
        self.runs += 1
        for idx in self._indices:
            if idx not in self._skipped:
                raise PoisonItemError(idx, RuntimeError("decoder segfault surfaced"))

    def skip_item(self, index: int) -> None:
        self._skipped.add(index)


class _NoSkipPoisonUnit:
    """A poison unit WITHOUT a ``skip_item`` method (the Protocol permits this)."""

    def __init__(self, name: str, *, index: int) -> None:
        self.name = name
        self._index = index
        self.runs = 0

    async def run(self) -> None:
        self.runs += 1
        raise PoisonItemError(self._index, RuntimeError("unskippable poison"))


def _supervisor(**kw) -> Supervisor:
    calls: list[str] = []
    kw.setdefault("on_escalate", lambda: calls.append("escalate"))
    kw.setdefault("backoff_seconds", 1.0)
    sup = Supervisor(sleeper=VirtualSleeper(), **kw)
    sup._escalations = calls  # type: ignore[attr-defined]  # test handle
    return sup


# ---- Protocol ------------------------------------------------------------------------------
def test_unit_satisfies_supervisable() -> None:
    assert isinstance(_Unit("s"), Supervisable)
    assert isinstance(_NoSkipPoisonUnit("s", index=0), Supervisable)  # skip_item NOT required


# ---- restart-to-known-good -----------------------------------------------------------------
async def test_restarts_a_crashing_unit_until_it_succeeds() -> None:
    unit = _Unit("s", crashes=2)
    await _supervisor(max_consecutive_restarts=5).run([unit])
    assert unit.runs == 3


async def test_backoff_sleeps_between_restarts() -> None:
    unit = _Unit("s", crashes=2)
    sleeper = VirtualSleeper()
    await Supervisor(
        sleeper=sleeper, backoff_seconds=2.5, max_consecutive_restarts=5, on_escalate=lambda: None
    ).run([unit])
    assert sleeper.slept == [2.5, 2.5]


async def test_emits_crashed_and_restarting_status_to_the_registry() -> None:
    # deep-dive: a crashing station must show CRASHED/RESTARTING in the registry (not stale ON_AIR),
    # with the restart count + the SCRUBBED cause, so "N/N ON AIR" reflects reality.
    from pirate_radio.status import StationState

    seen: list[tuple[str, StationState, int, str | None]] = []
    unit = _Unit("Pi0", crashes=1, exc=RuntimeError("Bearer sk-leak boom"))
    await Supervisor(
        sleeper=VirtualSleeper(),
        on_escalate=lambda: None,
        max_consecutive_restarts=5,
        on_status=lambda s: seen.append((s.name, s.state, s.restart_count, s.last_error)),
    ).run([unit])
    states = [s for _, s, _, _ in seen]
    assert StationState.CRASHED in states and StationState.RESTARTING in states
    assert all("sk-leak" not in (err or "") for *_, err in seen)  # H22: secret scrubbed in status


# ---- sibling isolation (incl. true concurrency) --------------------------------------------
async def test_sibling_isolation_one_crash_does_not_touch_others() -> None:
    crasher = _Unit("crasher", crashes=1)
    healthy = _Unit("healthy", crashes=0)
    await _supervisor(max_consecutive_restarts=5).run([crasher, healthy])
    assert crasher.runs == 2 and healthy.runs == 1


async def test_units_run_concurrently_not_serially() -> None:
    # QA: prove the supervisor runs units CONCURRENTLY (a serial impl would deadlock here).
    a_started = asyncio.Event()
    b_started = asyncio.Event()

    class _Rendezvous:
        def __init__(self, name: str, mine: asyncio.Event, theirs: asyncio.Event) -> None:
            self.name, self._mine, self._theirs = name, mine, theirs

        async def run(self) -> None:
            self._mine.set()
            await asyncio.wait_for(self._theirs.wait(), 2.0)  # needs the sibling to be running too

    await _supervisor(max_consecutive_restarts=5).run(
        [_Rendezvous("a", a_started, b_started), _Rendezvous("b", b_started, a_started)]
    )
    assert a_started.is_set() and b_started.is_set()  # both ran at the same time


# ---- advance-past-poison: per-index counting + recovery -----------------------------------
async def test_poison_item_skipped_after_threshold_then_recovers(caplog) -> None:
    unit = _PoisonUnit("s", indices=[2])
    sup = _supervisor(poison_threshold=3, max_consecutive_restarts=99, max_skips=10)
    with caplog.at_level(logging.CRITICAL):
        await sup.run([unit])
    assert 2 in unit._skipped and unit.runs == 4 and not sup._escalations
    # the skip is logged CRITICAL, naming the index (operator visibility, §C)
    assert any(r.levelname == "CRITICAL" and "2" in r.getMessage() for r in caplog.records)


async def test_poison_counting_is_per_index_not_global() -> None:
    # DA G1: a GLOBAL crash counter would skip index 5 prematurely; per-index counting must not.
    # index 2 crashes to threshold (skipped); index 5 has only crashed fewer times (NOT skipped).
    unit = _PoisonUnit("s", indices=[2, 5])
    sup = _supervisor(poison_threshold=3, max_consecutive_restarts=99, max_skips=10)
    # stop early by capping skips so we can inspect mid-flight is hard; instead use a threshold
    # high enough that 5 never reaches it within the run: after 2 is skipped, 5 starts crashing.
    # With indices=[2,5]: runs 1-3 crash on 2 (poison[2]=3 -> skip 2). Then runs 4-6 crash on 5
    # (poison[5]=3 -> skip 5). run 7 completes. A GLOBAL counter would skip after 3 TOTAL -> wrongly
    # skip whatever index was current at crash 3 and never count 5 independently.
    await sup.run([unit])
    assert unit._skipped == {2, 5}  # both reached their OWN per-index threshold
    assert unit.runs == 7  # 3 (idx2) + 3 (idx5) + 1 success — proves independent per-index counts


# ---- poison without skip_item -> escalates via the ceiling (NEVER infinite-loops) ----------
async def test_unskippable_poison_escalates_via_ceiling() -> None:
    unit = _NoSkipPoisonUnit("s", index=0)  # poison forever, cannot be skipped
    sup = _supervisor(poison_threshold=3, max_consecutive_restarts=4, max_skips=10)
    await sup.run([unit])
    assert sup._escalations == ["escalate"] and unit.runs == 4  # bounded, then escalate


# ---- bounded skip budget -> an all-poison schedule escalates, never skips forever ----------
async def test_skip_budget_exhaustion_escalates() -> None:
    # DA G4: every index is poison; without a budget the supervisor would skip forever (a slow
    # all-backstop loop, no alarm). The skip budget caps it -> escalate to systemd.
    unit = _PoisonUnit("s", indices=[0, 1, 2, 3, 4, 5])
    sup = _supervisor(poison_threshold=1, max_consecutive_restarts=99, max_skips=3)
    await sup.run([unit])
    assert sup._escalations == ["escalate"]  # skip budget (3) exhausted -> escalate
    assert len(unit._skipped) <= 3  # never skipped past the budget


# ---- ceiling -> escalate (injected, never a real exit) -------------------------------------
async def test_consecutive_restart_ceiling_escalates() -> None:
    unit = _Unit("s", crashes=100)
    sup = _supervisor(max_consecutive_restarts=3)
    await sup.run([unit])
    assert sup._escalations == ["escalate"] and unit.runs == 3


async def test_inprocess_escalation_does_not_cancel_sibling_tasks() -> None:
    # The in-process escalation must not itself cancel healthy siblings. (In PROD on_escalate is a
    # process exit, which IS global by design — that's the systemd hand-off, not tested here.)
    crasher = _Unit("crasher", crashes=100)
    healthy = _Unit("healthy", crashes=0)
    sup = _supervisor(max_consecutive_restarts=2)
    await sup.run([crasher, healthy])
    assert sup._escalations == ["escalate"] and healthy.runs == 1


# ---- secret-scrub (multi-pattern) ---------------------------------------------------------
@pytest.mark.parametrize(
    "leak",
    [
        "auth failed: Bearer sk-SUPERSECRET-123 rejected",
        "401 from https://api:SUPERSECRET@host/x",
        "header xi-api-key: SUPERSECRET denied",
        'body {"api_key": "SUPERSECRET"}',
        "raw token sk-SUPERSECRET-abc not authorized",
    ],
)
def test_scrub_secrets_redacts_known_shapes(leak: str) -> None:
    assert "SUPERSECRET" not in scrub_secrets(leak)


async def test_crash_log_scrubs_secret_and_keeps_station_name(caplog) -> None:
    unit = _Unit("PiRate-7", crashes=1, exc=RuntimeError("auth: Bearer sk-SUPERSECRET-9 nope"))
    with caplog.at_level(logging.WARNING):
        await _supervisor(max_consecutive_restarts=5).run([unit])
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "SUPERSECRET" not in joined  # redacted
    assert "PiRate-7" in joined  # the station name survives (operator visibility)


# ---- cooperative shutdown: CancelledError never swallowed (run OR backoff) -----------------
async def test_cancellation_during_run_is_not_a_crash() -> None:
    class _CancelUnit:
        name = "c"

        async def run(self) -> None:
            raise asyncio.CancelledError

    sup = _supervisor(max_consecutive_restarts=5)
    with pytest.raises(asyncio.CancelledError):
        await sup.run([_CancelUnit()])
    assert not sup._escalations


async def test_cancellation_during_backoff_propagates() -> None:
    # DA G7: cancellation arriving while awaiting the backoff sleep must propagate (clean shutdown),
    # not be swallowed by the crash-handling except.
    class _CancelSleeper:
        def __init__(self) -> None:
            self.slept: list[float] = []

        async def sleep(self, seconds: float) -> None:
            raise asyncio.CancelledError

    unit = _Unit("s", crashes=5)
    sup = Supervisor(
        sleeper=_CancelSleeper(),
        backoff_seconds=1.0,
        max_consecutive_restarts=9,
        on_escalate=lambda: None,
    )
    with pytest.raises(asyncio.CancelledError):
        await sup.run([unit])


# ---- on_escalate is terminal: not swallowed back into the loop -----------------------------
async def test_escalation_stops_supervising_the_unit() -> None:
    # after escalation the supervisor must STOP restarting the unit (return), so even a no-op
    # on_escalate cannot leave an in-process loop. Prod on_escalate uses os._exit (immediate,
    # bypassing asyncio.gather's BaseException->CancelledError quirk), documented on the class.
    unit = _Unit("s", crashes=100)
    sup = _supervisor(max_consecutive_restarts=2)
    await sup.run([unit])
    assert unit.runs == 2 and sup._escalations == ["escalate"]  # stopped, did not loop on


async def test_on_escalate_exception_is_not_swallowed() -> None:
    # DA G8: if on_escalate raises (a real exception), it must propagate — never be caught and
    # turned back into a restart loop.
    def _boom() -> None:
        raise RuntimeError("escalation handler failed")

    unit = _Unit("s", crashes=100)
    sup = Supervisor(
        sleeper=VirtualSleeper(), backoff_seconds=1.0, max_consecutive_restarts=2, on_escalate=_boom
    )
    with pytest.raises(RuntimeError, match="escalation handler"):
        await sup.run([unit])
