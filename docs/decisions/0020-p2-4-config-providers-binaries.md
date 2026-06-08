# P2-4 — typed `tts_providers` (R16) + `audio/binaries.py` preflight (A1/H15/H16/H20)

Strict spec-driven TDD: tests authored from the adopted Phase-2 plan §4.5 + amendment A1
→ confirmed RED → focused panel reviewed the tests → adopted → GREEN → gate → commit.

## Panel review of the tests (focused: QA + Senior Dev + Devil's Advocate)

**Round 1 — QA AYE, Senior NAY, DA NAY → 2 NAY → revise.** Convergent findings:
- **The A1 wiring test could pass for the wrong reason** (DA/QA): with `shutil.which` unpatched
  it could raise on *missing ffmpeg* rather than because preflight ran the piper check. Fixed:
  patch `which` so ffmpeg passes, assert the SAME config loads under `preflight=False` and is
  rejected under `preflight=True` (`match="piper"`) — the delta proves causation.
- **Mouse-collision `match` too loose** (DA): `match="piper"` → `match="mouse"` (pins H16).
- **`_typed_providers` stash wouldn't survive `model_copy`** (DA/Senior): switch from
  `object.__setattr__` to Pydantic `PrivateAttr` (copy-safe + mypy-clean); added
  `test_typed_provider_survives_model_copy`.
- **H20 separation needs a positive negative-test** (DA): added
  `test_preflight_false_skips_binary_checks_even_when_absent` (`which→None` + `preflight=False`
  loads).
- **Remedy assertions were circular** (DA): preflight tests now match the PRODUCTION remedy
  (`apt install ffmpeg` / `apt install espeak-ng`), not echoed test strings.
- Plus: `resolve_binary` non-exec test given the name arg (Senior); elevenlabs-typed test;
  explicit-`ffmpeg_binary` branch; caplog "preflight ok".

**`preflight=True` default kept** (Senior raised it): A1's purpose is fail-fast-at-boot
**by default** — a `False` default reintroduces the wire-it-yourself gap A1 closed. The
existing bare `load_config(...)` calls (absent/malformed file) short-circuit at read/JSON-parse
before preflight; only valid-config tests reach it and route through `_load(preflight=False)`.

**Round 2 — QA AYE, Senior AYE, DA AYE → 3 AYE / 0 NAY → ADOPTED.**

## Implementation

- `config.py`: typed `PiperProviderConfig` (binary optional — H16 no PATH fallback; voices_dir
  required) / `EspeakProviderConfig` / `ElevenLabsProviderConfig`; `DaemonConfig` gains
  `ffmpeg_binary`, `decode_timeout_seconds`/`tts_timeout_seconds` (H14, gt=0). The
  `_typed_tts_providers` model_validator keeps the A3 unknown-key check and parses each inner
  dict into its typed model (R16; typo'd inner key → ConfigError), stashing into a
  `PrivateAttr` (copy-safe). `provider(key)` returns the typed union; espeak with no block →
  default `EspeakProviderConfig()` (H15, no KeyError).
- `audio/binaries.py`: `resolve_binary` (explicit must exist+executable, else PATH; remedy in
  every error) and `preflight_binaries` (ffmpeg always; piper requires an explicit binary +
  per-station `voices_dir/{voice}.onnx`; espeak via PATH; logs "preflight ok").
- `load_config(..., preflight: bool = True)`: A1 wiring — after `_validate_config`, a
  function-level import of `preflight_binaries` (avoids the binaries↔config import cycle) runs
  the boot check. `_validate_config` stays binary-free (H20).

## Gate

ruff + ruff-format + mypy clean (31 files); **334 tests** (+1 hardware smoke), 98.63%
coverage; binaries.py 98%, config.py 99%.
