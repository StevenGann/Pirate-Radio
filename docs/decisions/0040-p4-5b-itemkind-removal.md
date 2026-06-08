# P4-5b — `item_kind` Protocol-param removal + mypy-2.1 gate repair

A small, behavior-preserving cleanup carried in the adopted Phase-4 plan, plus repair of six
pre-existing `mypy --strict` errors surfaced by a stricter mypy in the venv.

## `item_kind` removal (the planned cleanup)

`TextGenerator.patter(item_kind: str, context: DjContext | None)` carried the item kind as a
separate positional even though `context.kind` (R16) already holds it — a redundancy that could
drift. Dropped the parameter; the kind is now read from `context.kind` everywhere.

- **Source (7 sites):** `dj/protocols.py` (Protocol def), `dj/failover.py` (`RankedTextGenerator.
  patter` def + the `_ranked_call` lambda), `dj/text.py` (`ClaudeDJ`/`DeepSeekDJ`/`OllamaDJ` defs —
  bodies already used `context` only), `dj/fakes.py` (`NullDJ`; `ScriptedDJ` now derives
  `kind = context.kind if context else ""` for its `by_kind` lookup and its `(kind, context)` call
  record), `pipeline/producer.py` (`self._dj.patter(ctx)`).
- **Behavior-preserving:** in every `ScriptedDJ` `by_kind`/`calls` test the old `item_kind` already
  equalled the context's kind, so deriving from `context.kind` changes no assertion. `runtime_
  checkable` Protocols match method NAMES, so all `isinstance(..., TextGenerator)` checks still pass.
- **Tests:** all `.patter("<kind>", ctx)` call sites collapsed to `.patter(ctx)` across the dj/ and
  pipeline/ suites; three test-local fake `patter` defs narrowed to the one-arg signature.

## mypy-2.1 gate repair (pre-existing, not from this refactor)

The venv's mypy (2.1.0) is stricter than the version under which the P4-1…P4-4 gates ran and now
follows into httpx/mutagen; `mypy --strict src/` reported **six pre-existing errors** (confirmed
present at the P4-5 commit via `git stash`). Fixed minimally and faithfully:

- `dj/text.py` `parse_openai_chat_response` / `parse_ollama_response`: param `dict` →
  `dict[str, Any]` (supplies the missing type args); the extracted `text` annotated `: str` so the
  declared return is not `Any` — the `.strip()` still runs on the raw value, so a `None` content
  still raises `AttributeError` and is caught (no behavior change).
- `dj/_http.py` `post_json`: `return resp.json()` (`Any`) → `cast("dict[str, object]", …)` matching
  the declared return type (the cast line is the network `pragma: no cover`).
- `catalog/metadata.py`: `mutagen.File(path)` → `# type: ignore[attr-defined]` (mutagen re-exports
  `File` lazily; the existing `mutagen.*` override covers missing-imports, not attr-export).

These are the only mypy-version-bump fixes; no logic changed.

## Gate

ruff + ruff-format + mypy `--strict` clean (43 source files); **640 tests**, 98.64% coverage.

## Next

P4-6: `coordinator.py` (shared services, §A look-ahead depth/RAM fail-fast/stagger budget,
StationStatus registry + periodic "N/N ON AIR" summary, actual-rate guarantee, sink_factory seam).
