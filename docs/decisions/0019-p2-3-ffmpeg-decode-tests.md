# P2-3 — `audio/decode.py` `FfmpegDecoder` (real decode, R22)

Strict spec-driven TDD: tests authored from the adopted Phase-2 plan §4.3 → confirmed RED
→ focused panel reviewed the tests → adopted → GREEN → gate → commit. First increment with
the subprocess / hardware split.

## Panel review of the tests (focused: QA + Senior Dev + Devil's Advocate)

**Round 1 — QA NAY, Senior AYE, DA NAY → 2 NAY → revise.** Convergent finding: the tests
covered the pure helpers well but left the **orchestration seam** gameable —
- argv/timeout were never asserted (the monkeypatched `_run` ignored its argument, so a
  hardcoded/wrong-argv impl, or one that dropped the timeout, would pass);
- the `asyncio.to_thread` offload (R21/R23) was unpinned (a sync-on-loop impl would pass →
  dead-air risk on the Pi).

**Revisions folded in:**
- `test_decode_builds_argv_and_forwards_timeout_to_subprocess` — patches the REAL
  `subprocess.run` (exercising `_run` + `to_thread` end-to-end) and asserts the argv (binary,
  path, `-ar 44100`, `-ac 2`, `-f f32le`) + kwargs (`timeout==77.0`, `capture_output=True`,
  `check=False`), all at non-default settings so a literal-default impl can't sneak through.
- `test_decode_offloads_subprocess_to_a_worker_thread` — records `threading.get_ident()` in
  `_run`, asserts it differs from the test thread.
- `test_decode_path_with_spaces_stays_one_argv_element` — argv-as-list, no shell-split.
- `test_decode_non_utf8_stderr_is_replaced_not_crashed` — `b"\xff..."` stderr → ProviderFatal
  (no `UnicodeDecodeError` escaping).
- timeout test hardened with `TimeoutExpired(..., output=b"\x01\x02\x03")` (ragged partial)
  → still ProviderUnavailable (partial PCM never parsed); last-line-negative map case.

**Round 2 — QA AYE, Senior AYE, DA AYE → 3 AYE / 0 NAY → ADOPTED.**

During GREEN I caught one more real-logic gap (decode.py:119, the generic
`map_subprocess_exception` fallback) and added `test_other_subprocess_exception_maps_to_unavailable`.

## Implementation

- `audio/decode.py` (extended): pure `build_ffmpeg_argv` (f32le @ station rate/channels,
  ffmpeg-side `-ar`), `parse_pcm_f32le` (frame-alignment guards raise ProviderFatal BEFORE
  `np.frombuffer` so no bare ValueError escapes the producer), `map_ffmpeg_error`
  (last-line-wins; recognised decode failure = Fatal, else Unavailable), and
  `map_subprocess_exception` (missing binary = Fatal, timeout/other = Unavailable). The
  `FfmpegDecoder.decode` orchestrates via `asyncio.to_thread(self._run, ...)`; only the
  literal `subprocess.run` in `_run` is `# pragma: no cover` (R20). Whole-track f32 buffer
  at the station rate (H5/H7); H14 timeout (default 120s).

## Gate

ruff + ruff-format + mypy clean; **314 tests** (+1 hardware-marked smoke, excluded from CI),
98.68% coverage; decode.py 99% (only the Protocol stub + the pragma'd subprocess.run line).
