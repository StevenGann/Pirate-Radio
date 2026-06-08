# P3-8 — producer wiring (the Phase-3 capstone): `build_dj_context` + ranked text→TTS + floors

Strict spec-driven TDD: tests authored from the adopted Phase-3 plan §4.6 / §6 → confirmed RED →
full focused panel (QA + Senior Dev + DA) reviewed the TESTS → folded the must-fixes → implemented
GREEN → gate → commit. **Completes Phase 3.**

## Panel review of the tests (focused: QA + Senior Dev + Devil's Advocate)

**Tally: QA AYE, Senior Dev AYE-conditional (a hard blocker), DA NAY → REVISE.** Both correct:

- **Senior Dev CRITICAL — empty-sentinel ValidationError bypasses R11.** The Rev-1 §4.6 sketch
  defaulted the Producer to `persona=""`/`station_name=""`, but `DjContext.persona`/`station_name`
  are `min_length=1`, so `build_dj_context("", "")` on a defaulted-args **patter** item raises
  `pydantic.ValidationError` (NOT a `ProviderError`) → crashes past the R11 backstop, breaking the
  C3-redux back-compat tests. Fixed at the boundary (not by try/excepting ValidationError into the
  backstop, which would mask programming errors): the Producer now defaults persona/station to
  **non-empty sentinels** (`_DEFAULT_PERSONA="PiRate Radio DJ"`, `_STATION="PiRate Radio"`),
  keeping the `DjContext` R16 invariant strong. (In the floor case the context is consumed only by
  NullDJ→"", so the sentinel never reaches a real prompt.)
- **DA — the CRITICAL regression test checked `segs[0]`, not the segment COUNT.** A decode-AND-patter
  double-segment bug would pass. Added `assert len(segs) == 1` + an outro variant. Plus: a negative
  WARNING assertion (a successful patter must NOT log "template fallback"), and a **block_transition
  context-threaded-through-the-producer** test (the richest, most-droppable `next_block`+`boundary_at`
  branch was only unit-tested at `build_dj_context`, never through the wiring) via `ScriptedDJ.calls`.
- **Capstone integration** (DA noted): a track + a patter item through `run_once` with a real ranked
  DJ chain — track decodes (DJ untouched), patter uses the DJ, both reach the sink.

The three `run_once` integration tests apply the P2-6 determinism pattern (patch `normalize_to`→
identity + `to_thread`→inline + `maxsize==len(items)`) so the instant `VirtualSleeper` doesn't race
the real worker hop into spurious backstops; real loudness/offload stay covered by the P2-6 tests.

## Implementation

- `pipeline/producer.py`: `build_dj_context` (PURE — item+station → `DjContext`); `Producer` gains
  defaulted `text_generator`/persona/station args (None → `RankedTextGenerator([NullDJ()])`;
  None persona/station → non-empty sentinels); `_render` **decodes every `TrackItem`** (the song
  never becomes patter — §7-Q8/DA CRITICAL), routes the three pure-patter items through the grounded
  DJ→TTS path, degrades empty patter to the Phase-1 template **+ a WARNING** (Field-Op), and keeps
  the R11 backstop catch **unchanged**.
- `pipeline/__init__.py`: `run_once` threads `text_generator`/persona/station/tagline to the
  Producer (all defaulted — the ~13 existing call sites + `test_run_once_old_signature_still_works`
  stay green, C3 redux).

## Gate

ruff + ruff-format + mypy `--strict` clean (38 files); **566 tests** (+24; 3 network smokes + 2
hardware deselected), 98.65% coverage; `pipeline/producer.py` 100%, `pipeline/__init__.py` 100%.

## Phase 3 status

**P3-1 … P3-8 all COMPLETE.** The AI DJ ships: grounded LLM patter (Claude/DeepSeek/Ollama),
ranked provider failover (LLM + TTS, skip-on-Fatal, total floor), ElevenLabs cloud TTS, the boot
seam, and the producer wiring — all behind the unchanged Phase-1 Protocols, fakes-only on the CI
path (R21). Next: the README Phase-3 prerequisites section + the full-team Phase-3 deep-dive
code-quality + documentation review (overnight mandate finale).
