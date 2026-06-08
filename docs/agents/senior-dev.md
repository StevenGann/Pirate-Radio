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

- _2026-06-07_ — Phase 1 (MVP slice) plan review. Architecture is strong: clean
  pipeline decomposition (timing/segment/buffer/producer/player), R17
  ScheduleItem discriminated union with shared `_ItemBase` (invalid states
  unrepresentable), R14 AudioBuffer as a frozen validated dataclass (correct call
  vs Pydantic — NumPy never JSON-round-trips), R15 ProviderError subtree landed
  base-only with the failover wrapper deferred to Phase 3, `find_now` upgraded to
  a typed `NowPlaying` (R11 gap path explicit, no raw None). Verified signatures
  against merged Phase-0 (Catalog in scanner.py, load_config(path,*,resolver,
  clock), StationConfig fields, persistence *,schema_version, Slot 24:00=
  time(0,0)) — all match. Durable positions:
  - **Top risk — final 24:00 slot boundary.** Generator's elided `_slot_boundary`
    must map `Slot.end == time(0,0)` to NEXT-day midnight, else `boundary-cursor`
    is negative and the last block never fills. Not pinned by a named test. MAJOR.
  - `groups[slot.group]` bare-indexed → KeyError on empty/absent group; config
    cross-checks only TODAY's grid (Q2). Guard with a typed error. MINOR Phase 1.
  - R15 base-only is right scope, but catching *any* ProviderError (incl.
    ProviderFatal) for the backstop blurs the retryable/fatal line; document as
    provisional, Phase-3 failover refines.
  - Q1: A6 state_dir governs §8.4 prose — AYE. Q2: exact-track re-anchor is the
    right v1 commitment; freeze the find_now/NowPlaying contract. Q3: fixed
    config-default budget now; defer measurement spike + warm-buffer to Phase 2.
- _2026-06-07_ — Phase 0 implementation-plan review. Plan faithfully implements
  R5/R6/R17 (atomic persistence + schema_version envelope), R16 discriminated
  unions (TTS+LLM keyed on `backend`, `extra="forbid"`), R18/D6 (injectable
  tz-aware Clock), and R10 (AudioDeviceResolver seam — policy tested in CI,
  udev mechanism deferred to Phase 4). Strong choices: frozen models +
  tuple/frozenset collections, two-phase grid validation, real-mutagen-on-real
  -WAV fixtures over mocks, `yaml.safe_load` only.
  - **R16 carve-out is the one real regression:** `tts_providers: dict[str,
    dict]` sits in `DaemonConfig` (model layer) NOW, and `extra="forbid"` does
    not recurse into dict values — a typo'd credential key passes silently, the
    exact failure R16 exists to stop. Defensible only because it has no Phase-0
    reader; must be modeled when Phase 2 reads it. Not a blocker (narrow, flagged
    openly as plan Q6).
  - **Convention leak:** `load_config` default path calls
    `datetime.now().weekday()` directly — a second `datetime.now()` outside
    `clock.py`, against the plan's own §5 rule. Prefer taking a `Clock`. Minor.
  - **Catalog (Q1):** value object correct; smell is `groups()` recomputing O(n)
    per call — cache a group index at construction, keep frozen.
  - **Grids (Q2):** validate ALL present grid files at boot vs current catalog.
  - **24:00 (Q3):** `time(0,0)` OK for Phase 0 if all-day + wrap cases tested;
    minutes-from-midnight cleaner long-term. Won't block.
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
