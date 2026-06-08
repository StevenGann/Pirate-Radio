# P2-5 — `dj/tts.py` `PiperTTS` + `EspeakTTS` (local voice, R22)

Strict spec-driven TDD: tests authored from the adopted Phase-2 plan §4.4 → confirmed RED
→ focused panel reviewed the tests → adopted → GREEN → gate → commit. Mirrors the P2-3
subprocess/hardware split.

## Panel review of the tests (focused: QA + Devil's Advocate)

**Round 1 — QA NAY, DA NAY → 2 NAY → revise.** Convergent findings (the suite regressed below
the P2-3 bar):
- **`_map_tts_error` / `_map_tts_exception` never tested directly** — only transitively (every
  synthesize test monkeypatched `_run_to_buffer`, bypassing the maps). Added dedicated pure
  tests: fatal keywords (parametrized), unknown→Unavailable, empty-stderr→Unavailable+exit,
  multiline last-line-wins (both directions), and all three exception rows.
- **No espeak argv+timeout spy** — only piper had the patched-`subprocess.run` spy. Added the
  espeak twin (asserts `-v/-s/-p/-w`, `--stdin`, `input=` text on stdin, forwarded timeout).
- **WAV golden tolerance `1e-4` hid a wrong divisor** (DA *demonstrated* `/32767`=0.50002 passes
  at 1e-4) → tightened to `1e-7` (16384/32768==0.5 exact).
- **`framerate<=0` and espeak-empty-text** untested → added (the framerate test patches the
  WAV fmt-chunk rate field to 0).
- **Resample test was bypassable** (silence + duration) → now feeds a non-silent 0.5-DC WAV and
  asserts frame-count `round(in*48000/22050)±1` + RMS>0.4, so a rebuild-silence impl fails.

**Round 2 — QA AYE, DA AYE → 2 AYE / 0 NAY → ADOPTED.**

During GREEN, added two nonzero-exit tests (patched `subprocess.run` returns returncode≠0) to
cover the real `_run_to_buffer` classification branch; pragma'd the unreachable `ch<1` WAV guard.

## Implementation

- `dj/tts.py`: pure `wav_bytes_to_buffer` (s16 → float32 /32768; structural garbage / non-s16 /
  bad rate → ProviderFatal), `build_piper_argv` (speed → `--length_scale=1/speed`, guarded) and
  `build_espeak_argv` (`-s round(175*speed)`, `-p pitch`, `--stdin`), `_map_tts_error`
  (last-line-wins: voice/model/not-found → Fatal, else Unavailable) and `_map_tts_exception`
  (missing binary → Fatal, timeout/other → Unavailable). `PiperTTS` (requires explicit binary,
  H16) + `EspeakTTS` (PATH fallback) `synthesize`: empty text → 0s silence at station rate;
  text on stdin; render via `asyncio.to_thread` (R21); output `to_rate`-resampled to the station
  rate (H5); H14 timeout. Only the literal `subprocess.run` is `# pragma: no cover` (R20).

## Gate

ruff + ruff-format + mypy clean (32 files); **364 tests** (+2 hardware smokes), 98.74%
coverage; dj/tts.py 100%.
