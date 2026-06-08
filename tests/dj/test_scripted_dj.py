"""RED tests for P3-3 — Protocol narrowing + the ``ScriptedDJ`` fake (Phase 3 plan §3.3 / §6).

Tests first (strict spec-driven TDD): the Phase-1 ``TextGenerator.patter`` signature is
narrowed from ``context: object | None`` to ``context: DjContext | None`` (the seam the Phase-1
docstring reserved — R16). ``NullDJ`` keeps its floor behaviour (returns ``""``); a new
``ScriptedDJ`` (the text-side analogue of ``StubTTS``/``FailingTTS``) returns canned patter or
raises a seeded ``ProviderError``, and records calls for failover order-spy tests. Because
``runtime_checkable`` Protocols check method NAMES, not signatures, ``isinstance`` keeps passing
— the narrowing is a static (mypy) tightening only.
"""

from __future__ import annotations

import pytest

from pirate_radio.dj.context import BlockContext, DjContext
from pirate_radio.dj.fakes import NullDJ, ScriptedDJ
from pirate_radio.dj.protocols import TextGenerator
from pirate_radio.errors import ProviderError, ProviderFatal, ProviderUnavailable


def _ctx(kind: str = "intro") -> DjContext:
    return DjContext(kind=kind, persona="P", station_name="S", current_block=BlockContext(name="B"))


# ---- Protocol satisfaction (runtime_checkable checks names, survives the narrowing) --------
def test_nulldj_and_scripteddj_satisfy_text_generator() -> None:
    assert isinstance(NullDJ(), TextGenerator)
    assert isinstance(ScriptedDJ(), TextGenerator)


# ---- NullDJ floor unchanged, now accepts a real DjContext ---------------------------------
async def test_nulldj_returns_empty_for_any_kind() -> None:
    assert await NullDJ().patter("station_id", None) == ""
    assert await NullDJ().patter("intro", _ctx()) == ""  # accepts a real DjContext


# ---- ScriptedDJ: canned constant text -----------------------------------------------------
async def test_scripteddj_returns_constant_text_for_any_kind() -> None:
    dj = ScriptedDJ(text="hi there")
    assert await dj.patter("intro", _ctx()) == "hi there"
    assert await dj.patter("station_id", _ctx("station_id")) == "hi there"


# ---- ScriptedDJ: per-kind canned text overrides the constant ------------------------------
async def test_scripteddj_per_kind_text_overrides_default() -> None:
    dj = ScriptedDJ(text="default", by_kind={"intro": "intro line"})
    assert await dj.patter("intro", _ctx()) == "intro line"
    assert await dj.patter("outro", _ctx("outro")) == "default"  # unlisted kind -> default


# ---- ScriptedDJ: seeded error (folds the old FailingDJ) ------------------------------------
async def test_scripteddj_raises_seeded_error() -> None:
    dj = ScriptedDJ(error=ProviderFatal("bad key"))
    with pytest.raises(ProviderFatal):
        await dj.patter("intro", _ctx())


async def test_scripteddj_raises_base_providererror_subtype() -> None:
    dj = ScriptedDJ(error=ProviderUnavailable("down"))
    with pytest.raises(ProviderError):  # the chain catches the BASE class, not a leaf
        await dj.patter("intro", _ctx())


# ---- ScriptedDJ: error precedence (DA) — error wins over text AND by_kind ------------------
async def test_scripteddj_error_wins_over_text() -> None:
    dj = ScriptedDJ(text="hi", error=ProviderFatal("boom"))
    with pytest.raises(ProviderFatal):  # faithfully folds FailingDJ: error dominates
        await dj.patter("intro", _ctx())


async def test_scripteddj_error_wins_over_by_kind() -> None:
    dj = ScriptedDJ(by_kind={"intro": "x"}, error=ProviderUnavailable("boom"))
    with pytest.raises(ProviderUnavailable):
        await dj.patter("intro", _ctx())


# ---- ScriptedDJ records calls (order-spy support for failover tests) -----------------------
async def test_scripteddj_records_kind_and_context_in_order() -> None:
    # DA: pin BOTH tuple elements — the spy must capture WHICH context each call received
    # (failover/producer tests assert the propagated DjContext), not just the kind.
    dj = ScriptedDJ(text="x")
    c1, c2 = _ctx("intro"), _ctx("outro")
    await dj.patter("intro", c1)
    await dj.patter("outro", c2)
    assert dj.calls == [("intro", c1), ("outro", c2)]  # identity-equal contexts, in order


async def test_scripteddj_records_the_attempt_before_raising() -> None:
    # DA: record-then-raise — a FAILED provider must still appear in the spy so failover
    # diagnostics can see every attempt, not only the successful one.
    dj = ScriptedDJ(error=ProviderFatal("boom"))
    ctx = _ctx()
    with pytest.raises(ProviderFatal):
        await dj.patter("intro", ctx)
    assert dj.calls == [("intro", ctx)]


async def test_scripteddj_default_text_is_empty() -> None:
    assert await ScriptedDJ().patter("intro", _ctx()) == ""
