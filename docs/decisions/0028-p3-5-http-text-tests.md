# P3-5 — `dj/_http.py` + `dj/text.py` (Claude/DeepSeek/Ollama network backends, R15/R21/R23)

Strict spec-driven TDD: tests authored from the adopted Phase-3 plan §4.2 / §4.2a / §5 → confirmed
RED → full focused panel (QA + Senior Dev + DA) reviewed the TESTS → folded the must-fixes →
implemented GREEN → gate → commit. The network LLM layer; secrets + R21 live here.

## First task (Fact-Checker gate): the `anthropic` pin

Verified against PyPI **2026-06-08**: current is `anthropic 0.107.1` (still `0.x`, `<1` holds);
`httpx 0.28.1`. Pinned `anthropic>=0.107,<1` + `httpx>=0.27,<1` in `pyproject.toml`; the `model`
id is a required config field (no hardcoded default → model retirement is a config edit). Both
ship clean on arm64 cp311/cp312 (`anthropic` pure-Python + native `jiter`/`pydantic-core` prebuilt
wheels). The `PLACEHOLDER` is resolved; RED was unblocked.

## Panel review of the tests (focused: QA + Senior Dev + Devil's Advocate)

**Tally: QA AYE, Senior Dev AYE, DA NAY → 1 NAY (adopts under the charter); the DA's principled
gaps were folded in — one was a REAL latent bug.**

DA's blocking gaps (all folded):
1. **REAL BUG — `parse_claude_response` crashed on `text=None`.** `"".join(getattr(b,"text","") ...)`
   raises an *uncaught* `TypeError` if a content block's `.text` is `None`, escaping the
   `ProviderError` net → crashing the producer (defeating §9.3). Fixed: coerce `... or ""`; pinned
   by `test_parse_claude_none_text_block_is_fatal_not_typeerror`.
2. **`content: None` (present-but-null) unpinned** for DeepSeek/Ollama — a tool-call/content-filter
   null would `None.strip()`. The impl already catches `AttributeError`, but it was untested; added
   `test_parse_{openai_chat,ollama}_null_content_is_fatal_not_attributeerror`.
3. **H28 grep guard was string-split (missed top-level imports after the first class/def, and
   `from x import`/`import x as`).** Rewrote `test_no_top_level_network_imports` to walk the
   **`ast` module body** — robust and correctly allows lazy/`TYPE_CHECKING` imports.
4. **R21 import-guard was a weak pop-then-assert-absent.** Replaced with a **positive** guard that
   patches `builtins.__import__` to RAISE if the faked patter path imports `anthropic`/`httpx`
   (`test_no_sdk_imported_during_faked_run`) — proves the negative directly.
5. **H22 secret hygiene unpinned at the backend layer** (the actual leak site). Added
   `test_{claudedj,deepseekdj}_error_never_contains_api_key` (sentinel key absent from the raised
   error). Plus `map_claude` precedence (`test_map_claude_ratelimit_name_beats_4xx_status`) and
   `post_json` verbatim header/body forwarding.

QA's symmetry notes (Ollama None-context→Fatal, Ollama empty-completion, Claude ProviderError
re-raise) folded for completeness — `text.py` pure logic now fully covered.

## Implementation

- `dj/_http.py` (NEW, leaf): `map_http_status`/`map_httpx_exception` (PURE, R15) + `post_json`
  (lazy httpx, the only `pragma: no cover` = the literal network lines). The mappers live here so
  `dj/tts.py` imports them without a `tts → text` sibling import (Senior CRITICAL, P3-6 uses this).
- `dj/text.py` (NEW): PURE parsers (`parse_claude_response` None-safe / `parse_openai_chat_response`
  / `parse_ollama_response`), PURE `map_claude_exception` (by-name, rate-limit-first precedence),
  and `ClaudeDJ` (sync SDK via `asyncio.to_thread`, R23) / `DeepSeekDJ` / `OllamaDJ` (native-async
  via `post_json`). DeepSeek URL `…/chat/completions` (no `/v1/`). Lazy network imports (R21).
- `tests/dj/test_network_smokes.py`: env-gated `@pytest.mark.network` live smokes (excluded from CI).

## Gate

ruff + ruff-format + mypy `--strict` clean (37 files); **507 tests** (+54), 3 network smokes skip;
98.69% coverage; `dj/_http.py` 100%, `dj/text.py` 98% (only the `_blocking_call` network seam
uncovered — covered by the network smoke, excluded from the floor); real-offload proven via
`threading.get_ident()`; positive `__import__` guard + ast import guard prove R21.

## Next

P3-6: `ElevenLabsTTS` (mirror Piper, D5) + cloud-credential preflight (0010 cloud half) +
Ollama endpoint shape validation, tests-first.
