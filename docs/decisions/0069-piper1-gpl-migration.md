# 0069 — Migrate Piper TTS to the maintained piper1-gpl fork

The original `rhasspy/piper` is **archived**. The user asked whether we use the maintained fork
(`OHF-Voice/piper1-gpl`) and chose to migrate to it. Strict spec-driven TDD (tests updated to the new
contract → RED → implement → GREEN → gate), with a focused panel on this correctness-heart increment
(it changes the live broadcast TTS invocation).

## What changed vs. the original (verified against the fork's argparse source)

`piper1-gpl` is `pip install piper-tts`, run as **`python3 -m piper`** (no console script —
`pyproject.toml` has no `[project.scripts]`). Its argparse **kept backward-compatible aliases**, which
makes our flag logic compatible:

- `-m`/`--model` accepts a **path to the `.onnx`** (not just a voice name) → our `voices_dir/{voice}.onnx` works.
- `--output_file` and `--length_scale` exist as aliases → our `--output_file`/`--length_scale` argv is unchanged.
- text is read from **stdin** when no positional/`--input-file` is given → our `input=text` subprocess feed works.
- the companion `{voice}.onnx.json` is auto-discovered next to the model (no `-c` needed).

The only real difference is the **invocation**: a Python module, not a standalone binary.

## Implementation

- **`config.PiperProviderConfig`**: replaced `binary: Path | None` with **`python: Path | None`** (the
  interpreter whose venv has `piper-tts`; `None` → the daemon's own `sys.executable`, where
  `pip install piper-tts` naturally lands). This **retires the H16 footgun** entirely — there is no
  PATH binary to confuse with Debian's unrelated `piper` mouse tool.
- **`dj/tts.build_piper_argv(python, ...)`**: emits `[python, "-m", "piper", --model, --output_file,
  --length_scale]`; flags + stdin feed unchanged. `PiperTTS` defaults `python` to `sys.executable`;
  the old "binary required → ProviderFatal" guard is removed (no binary needed).
- **`audio/binaries.py`**: the boot preflight now verifies the `piper` module imports under the
  configured interpreter (`subprocess.run([python, "-c", "import piper"])`) instead of resolving a
  binary; `_PIPER_TTS_URL` retargeted to the fork; every remedy says `pip install piper-tts`.
- **Docs/config**: README + first-boot updated (pip install into the venv, `python -m
  piper.download_voices`, no binary path, `python` override only for a separate venv);
  `config.example.json` `piper` block drops `binary`.

## Tests (updated to the new contract; RED→GREEN verified)

`test_tts.py` (argv is `python -m piper …`; `python` defaults to `sys.executable`; missing-interpreter
→ Fatal; real-subprocess argv/timeout spy asserts `argv[:3] == [python, "-m", "piper"]`),
`test_binaries.py` (`piper` not importable → ConfigError naming the fork; an unrunnable interpreter →
ConfigError "cannot run"; missing `.onnx` *and* missing companion `.onnx.json` are each fatal at boot;
voice-model + all-present paths stub the import probe), `test_build.py` + `test_config.py` (provider
uses `python`/no binary).

## Focused panel (correctness-heart increment)

AYE ×3 (Devil's Advocate, Senior Dev, QA). Remediations folded in before commit:
- **DA (MEDIUM):** a missing companion `.onnx.json` passed boot but misclassified at first synth as a
  retryable error → the boot preflight now checks both `.onnx` and `.onnx.json`, and `dj/tts`'s
  fatal-keyword set was widened (`voice`/`model`/`not found`/`no such file`/`onnx`) so a bad voice
  fails over immediately instead of retrying.
- **QA:** the `_preflight_piper_module` exception arm (`FileNotFoundError`/`SubprocessError`) was
  uncovered → added `test_preflight_piper_interpreter_unrunnable_points_at_the_fork`.
- **Senior Dev / docs:** the second README config excerpt still showed the retired `binary` key
  (operator-breaking under `extra="forbid"`) → fixed.

## Notes

- A missing `piper-tts` module surfaces at runtime as a non-zero exit (not `FileNotFoundError`), which
  failover would treat as retryable — but the **boot preflight fail-fasts** on it first (the H16/A1
  philosophy: fail at boot, not 3am), so it never reaches the broadcast.
- piper1-gpl's README notes the per-call `python -m piper` path "is slow (loads the model each call)"
  and suggests its HTTP server for high throughput. v1 keeps the per-call subprocess model (matches
  our look-ahead + stagger budget); a persistent piper server is a possible future optimization.

## Gate

ruff + ruff-format + mypy `--strict` clean (64 source files); **883 tests**, 97.63% coverage;
`config.example.json` valid.
