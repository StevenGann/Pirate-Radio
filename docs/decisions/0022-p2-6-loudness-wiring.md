# P2-6 — loudness wiring + run_once threading (C3) + format-desync (C4) + player logging

Strict spec-driven TDD: tests authored from the adopted Phase-2 plan §4.6/§4.7 + amendments
A1/C3/C4/Q9 → confirmed RED → focused panel reviewed the tests → adopted → GREEN → gate →
commit. **The Phase-2 integration capstone — completes Phase 2.**

## Panel review of the tests (focused: QA + Devil's Advocate)

**Round 1 — QA AYE-conditional, DA NAY → revise.** The convergent BLOCKER: the normalize spy
returned the identity buffer, so it proved `normalize_to` was *called* but NOT that its result
was enqueued — a wired-but-discarded impl would pass (the headline §10 invariant untested).
Plus the desync test didn't prove "nothing aired", and the resume-INFO test was loosely matched
and order-blind.

**Revisions:**
- `test_producer_enqueues_the_normalized_result` — the spy returns a DISTINCT marker buffer;
  asserts every `seg.audio is marker` (the normalize result is what's enqueued, not the raw
  render).
- desync test asserts `sink.played == []` (raised at construction, nothing aired); docstring
  narrowed to "backstop-vs-declared" (decoder/TTS *actual*-rate verification is a Phase-4
  coordinator job — `run_once` only sees the declared ints; tracked here).
- resume test is order-bound (`resume_idx > backstop_idx`) + a negative
  `test_clean_run_logs_no_resume`.
- The no-drop integration test patches `normalize_to`→identity AND `asyncio.to_thread`→inline:
  the to_thread real-time worker-hop vs the instant `VirtualSleeper` was making the player race
  ahead and spuriously backstop (a real virtual-time/real-time composition issue QA flagged).
  Real loudness + the real offload are each covered by dedicated P2-6 tests.

**Round 2 — QA AYE, DA AYE → 2 AYE / 0 NAY → ADOPTED.**

## Implementation

- `pipeline/producer.py`: `Producer` gains `loudness_target_lufs` (default -16.0); `run()`
  normalizes every rendered segment to the target via `asyncio.to_thread(normalize_to, ...)`
  (Q9/R23 — R128 is CPU work, off the loop) before enqueue; the backstop path is never
  re-normalized. `_item_label` provides the H17 clamp-WARNING label.
- `pipeline/__init__.py`: `_assert_station_format` (C4 — backstop vs declared `(sample_rate,
  channels)`, raise before anything airs); `run_once` gains `loudness_target_lufs`,
  `sample_rate`, `channels` (C3 — threaded to the producer; defaults so the existing Phase-1
  call sites stay valid).
- `pipeline/player.py`: logs INFO "normal audio resumed after N backstop gap-fill(s)" when a
  real segment airs after an underrun (operator visibility, H14-row); the underrun itself stays
  a WARNING.
- `README.md`: NEW "Phase 2 runtime prerequisites" — ffmpeg/espeak-ng/piper install (incl. the
  Debian-`piper`-is-a-mouse-tool warning + voices_dir-on-fast-storage), and an annotated
  `config.json` excerpt (tts_providers.piper/espeak, ffmpeg_binary, timeouts, loudness range).

## Carry-forward (Phase 4)

`run_once` verifies the backstop matches the *declared* station format, but cannot verify the
decoder/TTS engines were actually constructed at that rate/channels (it only receives the
declared ints). The coordinator that wires the decoder/TTS/backstop from one config is the
right place to guarantee that — tracked for Phase 4.

## Gate

ruff + ruff-format + mypy clean (32 files); **371 tests** (+2 hardware smokes), 98.76%
coverage; pipeline producer/player/__init__ all 100%.
