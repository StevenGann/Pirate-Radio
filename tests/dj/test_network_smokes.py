"""Live network smokes for the Phase-3 LLM backends (§5, P3-5) — ``@pytest.mark.network``.

EXCLUDED from CI (the gate runs ``-m "not hardware and not network"``) and from the coverage
floor. These are the ONLY tests that hit a real provider; each is gated behind its credential
env var so a missing key SKIPS rather than fails. They exist to validate the live wire shape on
a real deployment — never on the CI/fakes path (R21). Run explicitly with ``pytest -m network``.
"""

from __future__ import annotations

import os

import pytest

from pirate_radio.dj.context import BlockContext, DjContext
from pirate_radio.dj.text import ClaudeDJ, DeepSeekDJ, OllamaDJ

pytestmark = pytest.mark.network


def _ctx() -> DjContext:
    return DjContext(
        kind="station_id",
        persona="A warm, concise late-night host.",
        station_name="PiRate One",
        current_block=BlockContext(name="Late Night"),
    )


async def test_claude_live_patter() -> None:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    model = os.environ.get("PIRATE_SMOKE_CLAUDE_MODEL", "").strip()
    if not key or not model:
        pytest.skip("set ANTHROPIC_API_KEY + PIRATE_SMOKE_CLAUDE_MODEL to run the Claude smoke")
    out = await ClaudeDJ(model=model, api_key=key).patter(_ctx())
    assert out.strip()


async def test_deepseek_live_patter() -> None:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    model = os.environ.get("PIRATE_SMOKE_DEEPSEEK_MODEL", "").strip()
    if not key or not model:
        pytest.skip("set DEEPSEEK_API_KEY + PIRATE_SMOKE_DEEPSEEK_MODEL to run the DeepSeek smoke")
    out = await DeepSeekDJ(model=model, api_key=key).patter(_ctx())
    assert out.strip()


async def test_ollama_live_patter() -> None:
    endpoint = os.environ.get("PIRATE_SMOKE_OLLAMA_ENDPOINT", "").strip()
    model = os.environ.get("PIRATE_SMOKE_OLLAMA_MODEL", "").strip()
    if not endpoint or not model:
        pytest.skip(
            "set PIRATE_SMOKE_OLLAMA_ENDPOINT + PIRATE_SMOKE_OLLAMA_MODEL to run the Ollama smoke"
        )
    out = await OllamaDJ(model=model, endpoint=endpoint).patter(_ctx())
    assert out.strip()
