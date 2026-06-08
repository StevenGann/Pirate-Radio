# Senior Dev — Notes

> **Mandate:** Code smells, robust architecture, clean API design, solid
> documentation and comments. I read this file before every engagement and
> append durable learnings (date-stamped) after.

## Standing principles

- **Architecture serves change.** Favor clear module boundaries and dependency
  inversion so the design absorbs new requirements without rewrites.
- **APIs are contracts.** Small, intention-revealing surfaces; consistent naming;
  predictable error behavior; no leaking of internal/hardware details to callers.
- **Comments explain *why*, not *what*.** The code says what; comments capture
  intent, trade-offs, and gotchas. Public surfaces get docstrings.
- **Hunt code smells:** long functions, deep nesting, primitive obsession, shotgun
  surgery, feature envy, god objects, duplicated logic, leaky abstractions.
- **Immutability by default** (per project coding style): return new objects,
  don't mutate.
- **Many small focused files** over few large ones (200–400 lines typical).

## Watch-list for this project

- Keep hardware access behind interfaces; application logic should not import
  `RPi.GPIO`/audio libs directly. (Aligns with QA Engineer on testability.)
- A consistent result/error envelope across module boundaries.
- Document the public API as it emerges; don't let docs lag the code.

## Open questions

- Shared vs per-station content root (§16a) — affects catalog ownership and the
  repeat-window/dedup logic. Unresolved in the doc.

## Durable architectural positions

- **Protocols must specify their error contract, not just their return type.**
  `TTSEngine`/`TextGenerator`/`AudioSink` (§11) are the seams the failover layer
  is built on; failover can only work if backends raise a defined exception
  taxonomy (retryable provider error vs. fatal). Position: define a small
  exception hierarchy (e.g. `ProviderError` → `ProviderUnavailable` /
  `ProviderQuotaExceeded` / `ProviderFatal`) in the Protocol module and make it
  part of the contract.
- **`AudioBuffer` is a first-class data model and must be in §13.** It flows
  through every Protocol and the whole pipeline; sample rate / channels / dtype
  must be pinned or normalization (§10) and the sink are underspecified.
- **No untyped `dict` in the Pydantic model layer.** `dj_context`, `tts:
  list[dict]`, `llm: dict`, `tts_providers: dict` (§13) defeat fail-fast config
  validation. Backend params should be discriminated unions keyed on `backend`.
- **`ScheduleItem` should be a discriminated union on `kind`**, not one grab-bag
  model with five mutually-exclusive optionals. Invalid states should be
  unrepresentable.
- **The REST control API (§15) needs a documented response/error envelope** and
  status-code contract before it ships (aligns with global API-envelope rule).

## Notes log

- _2026-06-07_ — Panel established. Awaiting design document. No architecture
  decisions made yet.
- _2026-06-07_ — Round 1 review of PiRate_Radio_Design_Doc.md. Strong overall
  decomposition (coordinator/supervisor/station, producer/consumer pipeline,
  Protocol-backed backends, two-layer grid/schedule). Flagged five durable
  positions (see above): Protocol error contracts, missing `AudioBuffer` model,
  untyped dicts in the Pydantic layer, `ScheduleItem` god-model, and the
  undocumented REST envelope. Also noted `find_now` returns `None` on the
  transition-silence gaps it itself creates, with no documented player behavior
  for the `None` case. No code exists yet, so all of this is cheap to fix now.
