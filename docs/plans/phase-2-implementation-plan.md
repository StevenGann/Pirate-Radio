# Phase 2 Implementation Plan — Local Voice (Piper TTS · Real Decode · Loudness) — **Rev 2**

> **Status:** Rev 2 — revised after seven-agent panel review of Rev 1 (2 AYE / 5 NAY → *revise*). Every panel-adopted item folded in; all nine Rev-1 open questions are now **DECIDED** (see §7 Resolutions, no longer "open questions"). For the panel: strict spec-driven TDD (RED tests authored from spec → panel-reviewed → GREEN).
> **Builds on:** Phase 0 (`config.py`, `clock.py`, `errors.py`, `persistence.py`, `catalog/`, `schedule/`, `audio_devices.py`) and Phase 1 (`audio/buffer.py`, `audio/decode.py` Protocol+`FakeDecoder`, `dj/protocols.py`, `dj/fakes.py`, `pipeline/{producer,player,buffer,segment,timing}.py`) — all adopted and merged. This plan **does not re-plan** Phases 0–1; every signature below is wired to the real APIs read at authoring time.
> **Governing authority:** `PiRate_Radio_Design_Doc.md` §21 *Review Resolutions* and `docs/decisions/0001`–`0012`. Where this plan and §21 disagree, **§21 governs.** §21.6 **R22 (amended)** is the spine of this phase.

The roadmap (§20) defines Phase 2 as: *"Local voice — **Piper TTS, real intros/outros, loudness normalization, transition silence in the player.**"* The guiding principle (§20 close): each capability drops in **behind an unchanged Protocol** (`Decoder`, `TTSEngine`) without rewiring the look-ahead core proven in Phase 1.

This phase converts three Phase-1 stubs into real local-binary backends and adds the one new pure-compute module the design has pointed at since §10: **loudness normalization**.

### What changed Rev 1 → Rev 2 (panel-facing diff)

| # | Rev-1 defect (panel) | Rev-2 fix |
|---|---|---|
| C1 | `pyloudnorm>=0.1.1,<0.2` is **UNSATISFIABLE** | `pyloudnorm>=0.2.0,<0.3`; `scipy>=1.15,<2` |
| C2 | pyloudnorm short-buffer behavior mis-described everywhere | Corrected: **RAISES `ValueError`** for sub-400 ms non-silent; **RETURNS `-inf`** for ≥400 ms silent; the 0.4–0.8 s band can return `-inf` for *audible* speech. Drives the Q4 pad-then-measure fix. |
| C3 | P2-6 didn't thread `loudness_target_lufs` through `run_once` | `run_once` (`pipeline/__init__.py`) **and** the `Producer(...)` call updated in the **same** increment; both files listed; else `TypeError`. |
| C4 | §4.6 wrong: claimed player builds silence from a hardcoded default | **Corrected:** player builds transition silence from `self._backstop` today. Correct invariant = **ONE station-level (rate, channels)** for backstop + every segment + silence, **asserted at construction**; desync regression test is a P2-6 gate. |
| H4 | Short-patter "passthrough" violates §10 | **Pad-then-measure** (§7-Q4): pad to ≥400 ms with trailing silence, measure padded, apply gain to ORIGINAL. True passthrough only for empty/digitally-silent. |
| H9 | Claimed "§21 supports deferral of ElevenLabs" | **Retracted.** §21.6/R22 *amended by D5* puts ElevenLabs **in v1 as a core feature**. We acknowledge D5 and request **explicit panel ratification** to *sequence* it into Phase 3 on merit (cloud + needs `dj/failover.py` + ranked providers). |
| H20 | Binary preflight folded into `_validate_config` would break the whole config suite | **Separate `preflight_binaries(config)`**; `_validate_config` stays binary-free. |
| H17 | Gain clamp logged at DEBUG | **WARNING**, naming track + measured LUFS. |
| various | "view"/"zero-copy" comments misleading; `pragma: no cover` over-broad; speed math inside the subprocess | All fixed below. |

---

## 1. Scope & Non-Goals

### 1.1 In scope (Phase 2)

| Area | Module(s) | What ships |
|---|---|---|
| Loudness normalization (NEW) | `audio/loudness.py` | `pyloudnorm`-backed EBU-R128 measure + normalize-to-target; pure NumPy math; **pad-then-measure** for short patter; `ge=-40,le=0` config bound |
| Resampler (NEW) | `audio/resample.py` | `to_rate` via `scipy.signal.resample_poly` (pure, unit-tested); identity no-op when rates equal |
| Real decode | `audio/decode.py` (extend) | `FfmpegDecoder` — argv build, subprocess via `asyncio.to_thread`, stdout raw **f32le** → `AudioBuffer` at station rate; ffmpeg-side resample (`-ar`) + channel policy; timeout; pure PCM-parser + error-map split out |
| Real local TTS | `dj/tts.py` (NEW) | `PiperTTS` (primary, §11/D2 floor) + `EspeakTTS` (fallback) — pure argv + stdlib-`wave` parser + error-map; stdin text; timeout; resample to station rate via `to_rate` |
| Loudness wiring | `pipeline/producer.py` (extend) + `pipeline/__init__.py` (extend) | normalize **every** rendered segment to `loudness_target_lufs`, wrapped in `asyncio.to_thread`; threaded through `run_once` |
| Binary discovery + preflight | `audio/binaries.py` (NEW) | resolve ffmpeg/piper/espeak; **separate** `preflight_binaries(config)` (NOT in `_validate_config`) |
| Config | `config.py` (extend) | `loudness_target_lufs` `ge=-40,le=0`; `ffmpeg_binary`; typed `PiperProviderConfig`/`EspeakProviderConfig`; timeouts |
| Transition silence | *(shipped Phase 1)* | Confirm + **enforce** the single station-level (rate, channels) invariant (C4/H5) |

### 1.2 Non-goals (deferred to Phase 3+)

- **ElevenLabs cloud TTS — sequencing override, requires panel ratification (H9/§9-Q-D5).** **D5 mandates ElevenLabs in v1 as a core feature**, behind the same Protocol (§21.6). Rev 1 wrongly claimed §21 supports deferral; it does not. We are **not** disputing D5. We request the panel ratify *sequencing* `ElevenLabsTTS` into **Phase 3** strictly on engineering-dependency merit: it is **cloud** (so it needs the TTS-credential env preflight, the cloud half of 0010), and it is meaningless without the **ranked-provider failover wrapper** (`dj/failover.py`, R7/R15) it sits behind — which is itself Phase 3. Shipping it in Phase 2 without failover would mean a single cloud provider with no fallback, which contradicts the local-first floor (D2). The `ElevenLabsTTSConfig` discriminated-union arm already exists (Phase 0); Phase 2 does not touch it. **If the panel declines the sequencing override, ElevenLabs + a minimal failover wrapper move into Phase 2.**
- **Ranked provider failover wrapper** (`dj/failover.py`). Phase 2 ships *single* engines behind the Protocol; the producer keeps the Phase-1 "any `ProviderError` → R11 backstop" catch.
- **AI/LLM patter** (`dj/text.py` real impls, grounded `DjContext`, `dj/prompts.py`). Phase 2 speaks the Phase-1 template `announcement_text()` through a *real* voice. `NullDJ` stays the brain.
- **Streaming/chunked decode + running-R128 reconciliation (H7).** Phase 2 decodes the **whole track into one buffer** and measures R128 over the whole buffer. Streaming is deferred (the H7/H21 RAM trigger is **stereo** — see §7-Q1).
- **`SoundDeviceSink` real output** — unchanged from Phase 1.
- **Multi-station / supervisor / control API / midnight regen daemon** — Phases 4/6.

---

## 2. §21 Resolutions: implemented vs deferred in Phase 2

| Resolution | Phase 2? | How / why |
|---|---|---|
| **R22 (amended)** drop pydub; direct ffmpeg; one loudness path = `pyloudnorm`; Piper+espeak in v1 | **Implement (core)** | `FfmpegDecoder` (no pydub), `audio/loudness.py` (pyloudnorm only), `dj/tts.py` |
| **R14** one `AudioBuffer` shape | **Honor** | every decoded/synthesized buffer normalized to `(frames, channels)` float32 at the **station** rate (C4/H5) before leaving its module |
| **R15** Protocol error contract | **Implement (mapping)** | missing binary / nonzero exit / unparseable output / timeout → typed `ProviderError` subtype per the §3.4 classification table |
| **R16** no bare dicts in the model layer | **Implement** | `tts_providers` inner dicts promoted to typed `PiperProviderConfig`/`EspeakProviderConfig` |
| **R20** thin hardware seam + coverage honesty | **Implement** | only the literal `subprocess.run(...)` is `pragma: no cover`; FileNotFoundError/TimeoutExpired/returncode mapping lives in **pure** helpers, unit-tested by monkeypatching `subprocess.run` to raise |
| **R21/R23** blocking native calls via `asyncio.to_thread` | **Implement** | every subprocess invocation hops to a thread; **`normalize_to` is also wrapped in `asyncio.to_thread`** in the producer (§7-Q9) |
| **D5** ElevenLabs in v1 (core feature) | **Sequencing override → Phase 3, pending panel ratification** | acknowledged; justification on dependency merit only (§1.2) |
| **H5** shared station (rate, channels) | **Critical** | decode/TTS resample to it; backstop + every segment + silence share it; **asserted at construction** (C4) |
| **H7/H21** whole-track buffer now; streaming later | **Honor + note** | whole-buffer decode + whole-buffer R128 this phase; **stereo** is the streaming trigger |
| **H8** numpy/scipy aarch64 | **Honor** | scipy ships `manylinux aarch64` cp311/cp312 wheels; prose pin, no `platform_machine` marker (0010 declined it) |
| **0010 MEDIUM** `loudness_target_lufs` unbounded | **Implement** | `ge=-40.0, le=0.0` |
| **0010** TTS-credential / binary preflight | **Implement (binary half)** in **separate** `preflight_binaries` | cloud-credential half stays with ElevenLabs in Phase 3 |

---

## 3. Dependencies, Config Models & Error Classification

### 3.1 New Python runtime dependencies (CRITICAL pins corrected)

```toml
# pyproject.toml [project].dependencies — ADD:
"pyloudnorm>=0.2.0,<0.3",   # EBU R128 (ITU-R BS.1770) loudness; the ONE loudness path (R22).
                            #   Rev-1 pinned >=0.1.1,<0.2 which is UNSATISFIABLE (0.1.x never
                            #   shipped the API we use; PyPI floor for current API is 0.2.0).
"scipy>=1.15,<2",           # pyloudnorm K-weighting filter (scipy.signal) + our resampler.
                            #   1.15 is the current stable line with aarch64 cp311/cp312 wheels.
```

**`soundfile` is DROPPED** (Rev 1 listed it). Piper and espeak both emit canonical PCM WAV; we parse with the **stdlib `wave`** module in a pure, synthetic-byte-tested parser. One fewer system dependency (libsndfile), zero loss of capability for the two binaries we drive.

**aarch64 (H8):** `numpy` (already in tree), `scipy`, and `pyloudnorm` (pure-Python) all resolve on `manylinux_2_*_aarch64` for cp311/cp312. **Prose pin** in README/pyproject; **no `platform_machine` marker** — 0010 declined it (would strip the package from x86_64 dev/CI).

### 3.2 System binaries (NOT pip-installed)

ffmpeg, piper-TTS, espeak-ng are **system binaries**. Three resolution sources:

| Binary | Config source | Default if absent | Special handling |
|---|---|---|---|
| `ffmpeg` | NEW `DaemonConfig.ffmpeg_binary: Path \| None` | `shutil.which("ffmpeg")` | — |
| `piper` | `tts_providers["piper"].binary` (+ `voices_dir`) | **NONE — no PATH fallback** | **H16:** Debian's `piper` package is an unrelated *mouse-emulation* tool. We do **not** `shutil.which("piper")`. Require an explicit `binary` path; if absent, `ConfigError` instructing the operator to set it (and pointing at the piper-TTS release URL). |
| `espeak` | `tts_providers["espeak"].binary` (optional) | `shutil.which("espeak-ng")` then `"espeak"` | espeak-ng's binary name is unambiguous, so PATH fallback is safe here. |

### 3.3 Typed provider configs (R16) — H15

`tts_providers` is currently `dict[str, dict[str, object]]`. Phase 2 is the first reader of the inner keys, so we promote them to typed, **string-keyed** models via a `model_validator` (keeping the keyed-dict shape the existing A3 backend-key check relies on):

```python
# config.py — NEW typed provider models (R16)
class PiperProviderConfig(BaseModel):
    model_config = _FROZEN
    binary: Path | None = None          # H16: NO PATH fallback; preflight requires this or fails
    voices_dir: Path                    # required: where {voice}.onnx lives (FAST storage — H15)

class EspeakProviderConfig(BaseModel):
    model_config = _FROZEN
    binary: Path | None = None          # PATH fallback to espeak-ng / espeak is safe

class ElevenLabsProviderConfig(BaseModel):   # exists; Phase-3 reader
    model_config = _FROZEN
    api_key_env: str

# DaemonConfig.tts_providers becomes a typed, string-keyed union, validated per key.
# H15: a station that uses espeak but has NO tts_providers.espeak block must NOT KeyError —
# it defaults to EspeakProviderConfig() (PATH lookup). The model_validator below fills it in.
class DaemonConfig(BaseModel):
    model_config = _FROZEN
    llm: LLMConfig
    tts_providers: dict[str, dict[str, object]] = Field(default_factory=dict)  # raw on the wire
    ffmpeg_binary: Path | None = None
    decode_timeout_seconds: float = Field(default=120.0, gt=0)   # H14
    tts_timeout_seconds: float = Field(default=30.0, gt=0)       # H14
    state_dir: Path
    stations: tuple[StationConfig, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _typed_tts_providers(self) -> DaemonConfig:
        # A3 (kept): unknown backend keys still rejected. NEW: parse each known inner dict
        # into its typed model so binaries.py reads attributes, not bare dicts (R16).
        unknown = sorted(set(self.tts_providers) - _KNOWN_TTS_BACKENDS)
        if unknown:
            raise ConfigError(
                f"unknown tts_providers backend key(s): {unknown}; "
                f"known: {sorted(_KNOWN_TTS_BACKENDS)}"
            )
        # parse-and-stash typed views (a private attr; the raw dict stays for serialization)
        parsed: dict[str, object] = {}
        for key, raw in self.tts_providers.items():
            model = {"piper": PiperProviderConfig,
                     "espeak": EspeakProviderConfig,
                     "elevenlabs": ElevenLabsProviderConfig}[key]
            try:
                parsed[key] = model.model_validate(raw)
            except Exception as exc:
                raise ConfigError(f"tts_providers.{key}: {exc}") from exc
        object.__setattr__(self, "_typed_providers", parsed)   # frozen-safe stash
        return self

    def provider(self, key: str) -> object:
        """Typed provider config for `key`; espeak defaults to PATH-lookup config (H15)."""
        parsed: dict[str, object] = getattr(self, "_typed_providers", {})
        if key in parsed:
            return parsed[key]
        if key == "espeak":
            return EspeakProviderConfig()           # H15: no block -> PATH default, NOT KeyError
        raise ConfigError(f"no tts_providers block for backend {key!r}")
```

> The existing A3 tests (`test_unknown_tts_provider_backend_rejected`, `test_known_tts_provider_backend_accepted`) still pass: the unknown-key check is unchanged, and the known `elevenlabs` block parses cleanly into `ElevenLabsProviderConfig`.

### 3.4 Error-classification table (documented + unit-tested per row — H18)

Centralized in the pure `map_*_error` helpers so Phase-3 failover can tighten it in one place.

| Condition | Mapped to | Rationale |
|---|---|---|
| Missing binary (`FileNotFoundError`) | **`ProviderFatal`** | Misconfiguration, not transient; retrying the same provider never helps. |
| Bad item decode (ffmpeg "invalid data"/"no such file"/"does not contain") | **`ProviderFatal`** | The *file* is bad; the producer backstops the item. |
| Bad voice/model (piper/espeak "voice"/"model"/"not found") | **`ProviderFatal`** | Config error, terminal for this provider. |
| Truncated/un-parseable PCM/WAV; empty stdout; WAV framerate ≤ 0 | **`ProviderFatal`** | Output is structurally invalid; a retry yields the same garbage. |
| `TimeoutExpired` | **`ProviderUnavailable`** | Transient (load spike, slow disk); retryable. |
| Transient I/O / signal / unknown nonzero exit / unknown stderr | **`ProviderUnavailable`** | **Retryable is the safe default** when we can't classify. |

> **Critical (C2):** missing-binary maps to **`ProviderFatal`** here even though Rev-1's sketch wrapped `FileNotFoundError` as `ProviderUnavailable`. Rev 2 corrects it to `ProviderFatal` to match this table (a missing binary is a permanent misconfiguration).

---

## 4. Per-Module Low-Level Design

All models frozen, fully typed, no bare dicts (R16), `from __future__ import annotations`, files <400 lines. The recurring pattern:

> **Split pure logic from the subprocess.** (1) a **pure, synchronous, fully-unit-tested** core — argv build, PCM/WAV → `AudioBuffer`, loudness math, error mapping from a captured `(returncode, stderr)` or a caught exception type; and (2) a **thin async shell** — `asyncio.to_thread(subprocess.run, …)`. The **only** `pragma: no cover` line is the literal `subprocess.run(...)` call (R20). All FileNotFoundError/TimeoutExpired/returncode→ProviderError mapping is in pure helpers, tested by monkeypatching `subprocess.run` to raise.

### 4.1 `audio/loudness.py` (NEW) — pyloudnorm EBU-R128 (R22), **pad-then-measure**

```python
"""EBU R128 / ITU-R BS.1770 loudness normalization (§10, R22).

ONE loudness path: pyloudnorm (pure-Python, unit-testable). Measures integrated
loudness (LUFS) of an AudioBuffer and returns a NEW buffer gained to a target LUFS.
Immutable: never mutates the input (coding-style rule).

pyloudnorm 0.2.x short-buffer behavior (CORRECTED from Rev 1):
  * < 400 ms NON-silent  -> integrated_loudness RAISES ValueError (block too short to gate).
  * >= 400 ms but BELOW the -70 LUFS absolute gate (digital/near silence) -> RETURNS -inf.
  * The 0.4-0.8 s band can RETURN -inf even for AUDIBLE speech (only ~1-3 gating blocks,
    most dropped by the relative gate) -> we must not treat -inf as 'leave unchanged' for
    audible patter. Hence PAD-THEN-MEASURE below.

H7/H21 note: measures over the WHOLE buffer (Phase 2 decodes whole tracks). Streaming /
running-loudness reconciliation is the named Phase-3 refinement, triggered by STEREO.
"""
from __future__ import annotations

import logging
import warnings

import numpy as np
import pyloudnorm as pyln

from pirate_radio.audio.buffer import AudioBuffer

logger = logging.getLogger(__name__)

# ITU-R BS.1770 integrated loudness gates on 400 ms blocks (75% overlap). A buffer shorter
# than one block cannot be measured. We pad SHORT-BUT-AUDIBLE buffers up to this minimum
# with TRAILING SILENCE, measure the padded buffer, then gain the ORIGINAL.
_MIN_BLOCK_SECONDS = 0.4
# A hair over one block to guarantee >= 1 full gating block after the 75% overlap windowing.
_PAD_TARGET_SECONDS = 0.45

# Clamp applied gain so a near-silent buffer can't be amplified into clipping/noise.
_MAX_GAIN_DB = 30.0


def _integrated(samples: np.ndarray, sample_rate: int) -> float:
    """Raw pyloudnorm integrated loudness. Wrapped so the SINGLE pyloudnorm call site is
    here, with warnings suppressed (it emits a UserWarning for clipped/quiet input)."""
    meter = pyln.Meter(sample_rate)                       # BS.1770-4 K-weighting at this rate
    # astype(float64) ALWAYS COPIES (Rev-1 'zero-copy view' comment was WRONG) -> pyloudnorm
    # cannot mutate our float32 input through this array. Immutability holds.
    f64 = samples.astype(np.float64, copy=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return float(meter.integrated_loudness(f64))


def measure_lufs(buf: AudioBuffer) -> float | None:
    """Integrated loudness in LUFS, or None if the buffer is too short OR digital silence.

    Pads SHORT (< 400 ms) audible buffers with trailing silence to ~450 ms before measuring
    (so BS.1770 has >= 1 gating block). Returns None ONLY for empty / truly-silent buffers
    (measured -inf even after padding)."""
    if buf.frames == 0:
        return None
    samples = buf.samples
    if buf.duration_seconds < _MIN_BLOCK_SECONDS:
        pad_frames = int(round(_PAD_TARGET_SECONDS * buf.sample_rate)) - buf.frames
        if pad_frames > 0:
            silence = np.zeros((pad_frames, buf.channels), dtype=np.float32)
            samples = np.concatenate([buf.samples, silence], axis=0)   # NEW array; original intact
    loudness = _integrated(samples, buf.sample_rate)
    if not np.isfinite(loudness):                         # -inf: digital/near silence (gated out)
        return None
    return loudness


def normalize_to(buf: AudioBuffer, *, target_lufs: float,
                 track_label: str = "<unknown>") -> AudioBuffer:
    """Return a NEW AudioBuffer gained so its integrated loudness ~= target_lufs.

    Measurement uses pad-then-measure (short audible patter is padded for gating); the gain
    is applied to the ORIGINAL buffer (padding never reaches the output). TRUE passthrough
    only for empty / digitally-silent buffers (measure_lufs -> None). Never raises, never NaN.
    The §10 'tracks AND TTS at a common target' rule holds for everything audible."""
    measured = measure_lufs(buf)
    if measured is None:
        logger.debug("loudness: empty/silent buffer (%.3fs, %s) -> passthrough",
                     buf.duration_seconds, track_label)
        return buf
    raw_gain_db = target_lufs - measured
    gain_db = float(np.clip(raw_gain_db, -_MAX_GAIN_DB, _MAX_GAIN_DB))
    if gain_db != raw_gain_db:
        logger.warning(                                  # H17: WARNING, names track + LUFS
            "loudness: gain clamp engaged for %s (measured %.1f LUFS, target %.1f, "
            "wanted %+.1f dB, clamped to %+.1f dB) -- check for a mis-tagged/quiet file",
            track_label, measured, target_lufs, raw_gain_db, gain_db)
    gain_lin = np.float32(10.0 ** (gain_db / 20.0))
    gained = (buf.samples * gain_lin).astype(np.float32)  # NEW array (immutability)
    np.clip(gained, -1.0, 1.0, out=gained)                # H16: guard inter-sample overs
    return AudioBuffer(gained, buf.sample_rate, buf.channels)
```

**Panel bite-points:**
- **Pad-then-measure (Q4/H4)** replaces Rev-1's raw passthrough, which violated §10 for the 0.4–0.8 s audible-patter band. Pad with *trailing silence* to ~450 ms, measure the padded buffer (R128's absolute −70 LUFS gate drops the silence tail so it doesn't bias the measurement low), apply the gain to the **original**. True passthrough survives only for empty / digitally-silent buffers.
- **Immutability comment corrected:** `astype(float64, copy=True)` **always copies** (Rev-1 said "zero-copy view" — wrong). The float32 input is never reachable by pyloudnorm. Element-wise immutability is asserted in tests.
- **Gain clamp at WARNING (H17)**, naming the track + measured LUFS, so an operator can spot a mis-tagged quiet file.
- The single pyloudnorm call site is `_integrated`, wrapped in `warnings.catch_warnings()` (H-row 11).

### 4.2 `audio/resample.py` (NEW) — `to_rate` via scipy (Q2)

```python
"""Sample-rate conversion (pure, unit-tested). ONE resampler in the codebase (Q2):
scipy.signal.resample_poly. Decode resamples ffmpeg-side (-ar); TTS WAVs come back at the
voice's native rate (~22.05 kHz) and are converted here. No second ffmpeg subprocess."""
from __future__ import annotations

from math import gcd

import numpy as np
from scipy.signal import resample_poly

from pirate_radio.audio.buffer import AudioBuffer


def to_rate(buf: AudioBuffer, target_rate: int) -> AudioBuffer:
    """Return a NEW AudioBuffer resampled to target_rate (per-channel polyphase).
    Identity no-op (returns the SAME object) when already at target_rate."""
    if target_rate <= 0:
        raise ValueError(f"target_rate must be > 0, got {target_rate}")
    if buf.sample_rate == target_rate:
        return buf                                       # no-op identity (test: `is buf`)
    g = gcd(buf.sample_rate, target_rate)
    up, down = target_rate // g, buf.sample_rate // g
    out = resample_poly(buf.samples, up, down, axis=0).astype(np.float32)
    return AudioBuffer(np.ascontiguousarray(out), target_rate, buf.channels)
```

Output frame count is `round(in_frames * target/source)` ± 1 (polyphase edge). Tested both polarities (up and down), mono and stereo, plus the `is buf` no-op identity.

### 4.3 `audio/decode.py` (extend) — `FfmpegDecoder` (R22, no pydub), timeout (H14)

```python
# appended to audio/decode.py
from __future__ import annotations

import asyncio
import logging
import subprocess

import numpy as np

from pirate_radio.audio.buffer import DEFAULT_SAMPLE_RATE, AudioBuffer
from pirate_radio.catalog.models import Track
from pirate_radio.errors import ProviderError, ProviderFatal, ProviderUnavailable

logger = logging.getLogger(__name__)


def build_ffmpeg_argv(binary: str, src: str, *, sample_rate: int, channels: int) -> list[str]:
    """PURE: ffmpeg command line. Decode `src` -> raw f32le on stdout, resampled to
    sample_rate and down/upmixed to channels (ffmpeg-side, Q2)."""
    return [
        binary,
        "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", src,
        "-vn",                       # drop any cover-art video stream
        "-ar", str(sample_rate),     # H5: resample ffmpeg-side (Q2)
        "-ac", str(channels),        # channel policy (Q6: mono v1)
        "-f", "f32le",               # raw 32-bit float LE -> maps 1:1 to float32 (Q1)
        "-",                         # stdout
    ]


def parse_pcm_f32le(raw: bytes, *, sample_rate: int, channels: int) -> AudioBuffer:
    """PURE: interleaved f32le bytes -> AudioBuffer (frames, channels).

    H8(C2)/error-table: guards run BEFORE np.frombuffer so a malformed stream raises
    ProviderFatal (a bare ValueError would escape the producer's `except ProviderError`
    and crash the task -> dead air). Empty stdout / non-frame-aligned -> ProviderFatal."""
    if channels < 1:
        raise ProviderFatal(f"decode: channels must be >= 1, got {channels}")
    bytes_per_frame = 4 * channels                       # f32 = 4 bytes/sample
    if len(raw) == 0:
        raise ProviderFatal("decode: ffmpeg produced empty PCM (0 bytes)")
    if len(raw) % 4 != 0:                                # not even whole float32 samples
        raise ProviderFatal(f"decode: PCM byte length {len(raw)} not a multiple of 4")
    if len(raw) % bytes_per_frame != 0:                  # whole samples but not whole frames
        raise ProviderFatal(
            f"decode: PCM byte length {len(raw)} not divisible by frame size "
            f"{bytes_per_frame} (channels={channels})")
    flat = np.frombuffer(raw, dtype="<f4")               # only NOW is this safe
    samples = np.ascontiguousarray(flat.reshape(-1, channels), dtype=np.float32)
    return AudioBuffer(samples, sample_rate, channels)


def map_ffmpeg_error(returncode: int, stderr: str) -> ProviderError:
    """PURE: (returncode, stderr) -> typed ProviderError per the §3.4 table. Unit-tested
    with empty / single-line / multi-line stderr."""
    lines = stderr.strip().splitlines()
    msg = lines[-1] if lines else f"exit {returncode}"
    lowered = msg.lower()
    if any(s in lowered for s in ("no such file", "invalid data", "does not contain")):
        return ProviderFatal(f"ffmpeg cannot decode file: {msg}")
    return ProviderUnavailable(f"ffmpeg failed (exit {returncode}): {msg}")   # retryable default


def map_subprocess_exception(binary: str, exc: Exception) -> ProviderError:
    """PURE: a caught subprocess exception -> typed ProviderError (§3.4). Unit-tested by
    constructing the exceptions directly (no real binary)."""
    if isinstance(exc, FileNotFoundError):
        return ProviderFatal(f"ffmpeg binary not found: {binary}")            # §3.4: Fatal
    if isinstance(exc, subprocess.TimeoutExpired):
        return ProviderUnavailable(f"ffmpeg timed out after {exc.timeout}s")  # §3.4: Unavailable
    return ProviderUnavailable(f"ffmpeg subprocess error: {exc}")


class FfmpegDecoder:
    """Real decode (R22). Whole-track buffer at the station rate (H5/H7)."""

    def __init__(self, *, binary: str = "ffmpeg",
                 sample_rate: int = DEFAULT_SAMPLE_RATE, channels: int = 1,
                 timeout_seconds: float = 120.0) -> None:        # H14
        self._binary = binary
        self._sample_rate = sample_rate
        self._channels = channels
        self._timeout = timeout_seconds

    async def decode(self, track: Track) -> AudioBuffer:
        argv = build_ffmpeg_argv(self._binary, str(track.path),
                                 sample_rate=self._sample_rate, channels=self._channels)
        try:
            proc = await asyncio.to_thread(self._run, argv)      # R21: blocking -> thread
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise map_subprocess_exception(self._binary, exc) from exc
        if proc.returncode != 0:
            raise map_ffmpeg_error(proc.returncode, proc.stderr.decode("utf-8", "replace"))
        return parse_pcm_f32le(proc.stdout, sample_rate=self._sample_rate,
                               channels=self._channels)

    def _run(self, argv: list[str]) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(  # pragma: no cover  (R20: the ONLY hardware-bound line)
            argv, capture_output=True, check=False, timeout=self._timeout)
```

**Why f32le over s16le (Q1, decided):** s16le would need `/32768.0` and lose the dtype guarantee on the round trip; f32le is exactly the `AudioBuffer` dtype, so the parser is `frombuffer + reshape` with no scaling. **Cost arithmetic (H21):** mono f32 at 48 k for a 4-min track ≈ `48000 × 240 × 4 ≈ 44 MB`. **Transient peak** during decode: `parse` copies the f32 buffer (`ascontiguousarray`), and `normalize_to` allocates a third (`astype(float64)` inside the meter + the gained float32 out) — so a single track momentarily touches **≈3×** its size (~130 MB) before intermediates are freed. We **`del raw`** after `parse_pcm_f32le` returns and let `normalize_to`'s float64 fall out of scope. Against the **Pi-4 4 GB floor (D1)** at look-ahead depth 1–2 mono, this is comfortable. **STEREO doubles every figure and is the H7/H21 streaming trigger** (§7-Q1). The `# pragma: no cover` now sits on the literal `subprocess.run(...)` *only* (Rev 1 covered the whole method including the FileNotFoundError mapping — H6).

> **H12 / R11 against the real decoder:** a missing/corrupt file → `ProviderFatal` → the producer's `except ProviderError` → backstop, not a crash. P2-3 acceptance test.

### 4.4 `dj/tts.py` (NEW) — `PiperTTS` + `EspeakTTS` (R22), timeout (H14), pure speed math (H7-item)

```python
"""Local TTS engines (R22): PiperTTS (primary, §11/D2 floor) + EspeakTTS (fallback).

Each: build argv (PURE, incl. speed/pitch MATH), feed text on stdin, read WAV output, parse
(stdlib wave, PURE), resample to the station rate via to_rate (H5). The subprocess.run call
is the ONLY hardware line (R20). Errors -> ProviderError per the §3.4 table. ElevenLabs
(cloud, D5) is Phase 3 with failover -- see §1.2 (sequencing override, panel ratification)."""
from __future__ import annotations

import asyncio
import io
import logging
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

from pirate_radio.audio.buffer import DEFAULT_SAMPLE_RATE, AudioBuffer
from pirate_radio.audio.resample import to_rate
from pirate_radio.config import (
    EspeakProviderConfig, EspeakTTSConfig, PiperProviderConfig, PiperTTSConfig,
)
from pirate_radio.errors import ProviderError, ProviderFatal, ProviderUnavailable

logger = logging.getLogger(__name__)


def wav_bytes_to_buffer(raw: bytes) -> AudioBuffer:
    """PURE: canonical PCM-WAV bytes -> AudioBuffer at the WAV's own rate (caller resamples).
    Committed golden test pins struct.pack endianness. ProviderFatal on structural garbage."""
    try:
        with wave.open(io.BytesIO(raw), "rb") as w:
            ch, width, rate, nframes = (
                w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes())
            pcm = w.readframes(nframes)
    except (wave.Error, EOFError) as exc:
        raise ProviderFatal(f"tts: unreadable WAV ({exc})") from exc
    if rate <= 0:                                         # §3.4: structurally invalid -> Fatal
        raise ProviderFatal(f"tts: WAV framerate must be > 0, got {rate}")
    if width != 2:                                        # piper/espeak emit s16; guard others
        raise ProviderFatal(f"tts: unexpected WAV sample width {width} bytes (expected 2)")
    if ch < 1:
        raise ProviderFatal(f"tts: WAV channels must be >= 1, got {ch}")
    ints = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / np.float32(32768.0)
    samples = np.ascontiguousarray(ints.reshape(-1, ch), dtype=np.float32)
    return AudioBuffer(samples, rate, ch)


def build_piper_argv(binary: str, model: Path, out_path: str, *, speed: float) -> list[str]:
    """PURE incl. speed math (H7-item): piper --length_scale = 1/speed. Guard speed > 0."""
    if speed <= 0:
        raise ProviderFatal(f"piper: speed must be > 0, got {speed}")
    return [
        binary, "--model", str(model), "--output_file", out_path,
        "--length_scale", repr(1.0 / speed),             # speed MATH is here, unit-tested
    ]


def build_espeak_argv(binary: str, cfg: EspeakTTSConfig, out_path: str) -> list[str]:
    """PURE incl. speed math: espeak -s = round(175 * speed) wpm. Guard speed > 0."""
    if cfg.speed <= 0:
        raise ProviderFatal(f"espeak: speed must be > 0, got {cfg.speed}")
    return [
        binary, "-v", cfg.voice,
        "-s", str(round(175 * cfg.speed)),               # ~175 wpm default; speed MATH here
        "-p", str(cfg.pitch),                            # 0..99
        "-w", out_path,
        "--stdin",
    ]


def _map_tts_error(engine: str, returncode: int, stderr: bytes) -> ProviderError:
    """PURE: (engine, returncode, stderr) -> typed ProviderError (§3.4). Empty/multiline tested."""
    lines = stderr.decode("utf-8", "replace").strip().splitlines()
    tail = lines[-1] if lines else f"exit {returncode}"
    lowered = tail.lower()
    if any(s in lowered for s in ("voice", "model", "not found")):
        return ProviderFatal(f"{engine} bad voice/model: {tail}")            # §3.4: Fatal
    return ProviderUnavailable(f"{engine} failed (exit {returncode}): {tail}")  # retryable default


def _map_tts_exception(engine: str, binary: str, exc: Exception) -> ProviderError:
    """PURE: caught subprocess exception -> typed ProviderError (§3.4)."""
    if isinstance(exc, FileNotFoundError):
        return ProviderFatal(f"{engine} binary not found: {binary}")          # §3.4: Fatal
    if isinstance(exc, subprocess.TimeoutExpired):
        return ProviderUnavailable(f"{engine} timed out after {exc.timeout}s")
    return ProviderUnavailable(f"{engine} subprocess error: {exc}")


class PiperTTS:
    def __init__(self, *, cfg: PiperTTSConfig, provider: PiperProviderConfig,
                 sample_rate: int = DEFAULT_SAMPLE_RATE,
                 timeout_seconds: float = 30.0) -> None:     # H14
        if provider.binary is None:                          # H16: no PATH fallback for piper
            raise ProviderFatal(
                "piper: tts_providers.piper.binary is required (Debian 'piper' is an "
                "unrelated mouse tool; set the explicit piper-TTS path)")
        self._cfg = cfg
        self._binary = str(provider.binary)
        self._model = provider.voices_dir / f"{cfg.voice}.onnx"   # §12 voices_dir + voice
        self._sample_rate = sample_rate
        self._timeout = timeout_seconds

    async def synthesize(self, text: str) -> AudioBuffer:
        if not text.strip():
            return AudioBuffer.silence(seconds=0.0, sample_rate=self._sample_rate)
        try:
            buf = await asyncio.to_thread(self._run_to_buffer, text)   # R21
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise _map_tts_exception("piper", self._binary, exc) from exc
        return to_rate(buf, self._sample_rate)                          # H5

    def _run_to_buffer(self, text: str) -> AudioBuffer:
        with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:        # H15: per-call, unique
            argv = build_piper_argv(self._binary, self._model, tmp.name, speed=self._cfg.speed)
            proc = subprocess.run(  # pragma: no cover  (R20: the ONLY hardware line)
                argv, input=text.encode("utf-8"), capture_output=True,
                check=False, timeout=self._timeout)
            if proc.returncode != 0:
                raise _map_tts_error("piper", proc.returncode, proc.stderr)
            return wav_bytes_to_buffer(Path(tmp.name).read_bytes())


class EspeakTTS:
    def __init__(self, *, cfg: EspeakTTSConfig, provider: EspeakProviderConfig,
                 sample_rate: int = DEFAULT_SAMPLE_RATE,
                 timeout_seconds: float = 30.0) -> None:
        self._cfg = cfg
        self._binary = str(provider.binary) if provider.binary else "espeak-ng"
        self._sample_rate = sample_rate
        self._timeout = timeout_seconds

    async def synthesize(self, text: str) -> AudioBuffer:
        if not text.strip():
            return AudioBuffer.silence(seconds=0.0, sample_rate=self._sample_rate)
        try:
            buf = await asyncio.to_thread(self._run_to_buffer, text)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise _map_tts_exception("espeak", self._binary, exc) from exc
        return to_rate(buf, self._sample_rate)

    def _run_to_buffer(self, text: str) -> AudioBuffer:
        with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
            argv = build_espeak_argv(self._binary, self._cfg, tmp.name)
            proc = subprocess.run(  # pragma: no cover  (R20: the ONLY hardware line)
                argv, input=text.encode("utf-8"), capture_output=True,
                check=False, timeout=self._timeout)
            if proc.returncode != 0:
                raise _map_tts_error("espeak", proc.returncode, proc.stderr)
            return wav_bytes_to_buffer(Path(tmp.name).read_bytes())
```

**Per-config-param mapping (§12 contract):**
- Piper: `voice` → `voices_dir/{voice}.onnx`; `speed` → `--length_scale = 1/speed` (math in the **pure** `build_piper_argv`, guarded `speed > 0`, unit-tested).
- Espeak: `voice` → `-v`; `speed` → `-s round(175*speed)` (math in **pure** `build_espeak_argv`); `pitch` → `-p` (0–99).
- Both: text on **stdin** (avoids shell-escaping / argv length limits; security-clean).
- **Output rate match:** the `synthesize` empty-text path returns `silence(..., sample_rate=self._sample_rate)` so even the zero-length buffer matches the station rate (C4/H5).

### 4.5 `config.py` (extend) + `audio/binaries.py` (NEW) — **separate** preflight (H20/Q8)

**The `ge=-40, le=0` bound (0010 MEDIUM — lands now):**

```python
# StationConfig
loudness_target_lufs: float = Field(default=-16.0, ge=-40.0, le=0.0)
```
`le=0` rejects the physically-meaningless positive target (0 LUFS = digital full scale; broadcast targets are −14 to −24). `ge=-40` catches a typo'd −160 (Q5).

**Binary preflight — SEPARATE function, NOT folded into `_validate_config` (CRITICAL/H20/Q8):**

The config test suite (`tests/config/test_config.py`) drives **every** test through `load_config → _validate_config`, and `_valid_config` builds a `piper` TTS station. **Folding binary checks into `_validate_config` would make all ~40 config tests require a real piper-TTS binary on PATH — they would all fail.** Confirmed by reading the suite. Therefore preflight lives in its own function the **boot path** calls explicitly, *after* `load_config`:

```python
# audio/binaries.py (NEW)
"""Resolve + preflight the system binaries Phase 2 spawns (ffmpeg, piper, espeak).

Fail FAST AT BOOT (§12 spirit) -- but in a SEPARATE function the daemon entrypoint calls,
NOT inside _validate_config (H20): the config test suite validates piper-station configs
WITHOUT real binaries, so binary checks MUST stay out of load_config. Resolution: explicit
config path -> PATH lookup (piper has NO PATH fallback -- H16). Existence + executable only."""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from pirate_radio.config import (
    DaemonConfig, EspeakProviderConfig, PiperProviderConfig,
)
from pirate_radio.errors import ConfigError

logger = logging.getLogger(__name__)

_PIPER_TTS_URL = "https://github.com/rhasspy/piper/releases"


def resolve_binary(explicit: Path | None, *candidates: str, remedy: str) -> Path:
    """Explicit path (must exist + be executable) else first found PATH candidate.
    `remedy` is appended to the ConfigError so the operator knows the FIX (H13/H19)."""
    if explicit is not None:
        if not explicit.is_file():
            raise ConfigError(f"configured binary not found: {explicit}. {remedy}")
        if not os.access(explicit, os.X_OK):
            raise ConfigError(f"configured binary not executable: {explicit}. {remedy}")
        return explicit
    for name in candidates:
        found = shutil.which(name)
        if found:
            return Path(found)
    raise ConfigError(f"required binary not found on PATH (tried {list(candidates)}). {remedy}")


def preflight_binaries(config: DaemonConfig) -> None:
    """Boot-time check: every binary a configured station actually USES is present.
    Called by the daemon entrypoint AFTER load_config -- NEVER from _validate_config (H20)."""
    # ffmpeg: always needed (every station decodes)
    resolve_binary(config.ffmpeg_binary, "ffmpeg",
                   remedy="Install ffmpeg (e.g. `apt install ffmpeg`) or set ffmpeg_binary.")
    backends_in_use = {tts.backend for s in config.stations for tts in s.tts}
    if "piper" in backends_in_use:
        prov = config.provider("piper")
        assert isinstance(prov, PiperProviderConfig)
        if prov.binary is None:                                  # H16: no PATH fallback
            raise ConfigError(
                "piper is configured but tts_providers.piper.binary is unset. Debian's "
                f"`piper` package is an unrelated mouse tool; download piper-TTS from "
                f"{_PIPER_TTS_URL} and set tts_providers.piper.binary to its path.")
        resolve_binary(prov.binary, remedy=f"Download piper-TTS from {_PIPER_TTS_URL}.")
        # voices_dir/{voice}.onnx existence, per station using piper
        for s in config.stations:
            for tts in s.tts:
                if tts.backend == "piper":
                    onnx = prov.voices_dir / f"{tts.voice}.onnx"
                    if not onnx.is_file():
                        raise ConfigError(
                            f"station '{s.name}': piper voice model not found: {onnx}. "
                            f"Download the voice and place {tts.voice}.onnx in "
                            f"{prov.voices_dir} (keep voices_dir on FAST storage -- H15).")
    if "espeak" in backends_in_use:
        prov = config.provider("espeak")                         # H15: defaults if no block
        assert isinstance(prov, EspeakProviderConfig)
        resolve_binary(prov.binary, "espeak-ng", "espeak",
                       remedy="Install espeak-ng (e.g. `apt install espeak-ng`).")
    logger.info("binary preflight ok: %s", sorted(backends_in_use | {"ffmpeg"}))
```

**Q8 decided: config-load-adjacent (boot), separate function.** Consistent with §12 fail-fast and Phase-0 device/env preflight; the cost (boot needs the binaries) is correct for the deploy target, and the **test suite is unaffected** because `_validate_config` stays binary-free.

### 4.6 Transition silence in the player (§10) — **CORRECTED (C4)**

**What the player actually does today** (Phase 1, read at authoring): the player builds its inter-element transition silence from **`self._backstop`** — it uses the backstop buffer's `sample_rate`/`channels` to construct the silence, *not* a hardcoded `silence(seconds=..., )` default (Rev-1's claim) and *not* the just-played segment (Rev-1's "fix" was also wrong). So the **silence already matches the backstop's format.**

**The real invariant (the single source of truth):** **ONE station-level `(sample_rate, channels)`** shared by **the backstop, every produced segment, and the transition silence.** If the decoder/TTS emit a different rate/channels than the backstop, the sink sees two formats → desync. Rev 2 makes this an explicit, asserted contract:

1. The station wires **one** `(sample_rate, channels)` pair into the `FfmpegDecoder`, every TTS engine, **and** the backstop constructor (all already take these as args).
2. `run_once` / the producer/player **assert at construction** that `backstop.sample_rate`/`backstop.channels` match the decoder's and TTS engines' configured rate/channels.
3. A **P2-6 desync regression test** drives `run_once` with a decoder/TTS at one rate and a backstop at another and asserts it raises at construction (not silently mis-airs).

```python
# pipeline/__init__.py run_once gains the assertion + threads loudness (C3)
def _assert_station_format(*, backstop: AudioBuffer, sample_rate: int, channels: int) -> None:
    if backstop.sample_rate != sample_rate or backstop.channels != channels:
        raise ValueError(
            f"station format desync: backstop is ({backstop.sample_rate}, {backstop.channels}) "
            f"but segments are ({sample_rate}, {channels}) -- H5: one station-level format")
```

The player keeps building silence from `self._backstop`; the assertion guarantees the backstop *is* the station format, so the silence is correct by construction.

### 4.7 `pipeline/producer.py` + `pipeline/__init__.py` — loudness wiring (§10), threaded through `run_once` (C3), `to_thread` (Q9)

§10: *"normalize all elements (tracks **and** TTS) to a common target … applied at the NumPy-buffer stage."* The seam is the producer's `run`, after `_render`.

```python
# producer.py
from pirate_radio.audio.loudness import normalize_to

class Producer:
    def __init__(self, *, items, tts, decoder, buffer, backstop,
                 loudness_target_lufs: float) -> None:        # NEW (le=0, ge=-40)
        ...
        self._target_lufs = loudness_target_lufs

    async def run(self) -> None:
        for item in self._items:
            try:
                audio = await self._render(item)
                label = _item_label(item)                     # for the H17 clamp WARNING
                audio = await asyncio.to_thread(              # Q9/R23: R128 is CPU work
                    normalize_to, audio, target_lufs=self._target_lufs, track_label=label)
            except ProviderError as exc:                      # P7 TODO: Phase-3 Fatal vs retryable
                logger.warning("render failed for %s item (%s) -> backstop (R11/R15)",
                               item.kind, exc)
                audio = self._backstop                        # PRE-normalized once at construction
            await self._buffer.put(RenderedSegment(item=item, audio=audio))
```

```python
# pipeline/__init__.py — run_once MUST thread loudness_target_lufs (C3) or it TypeErrors
async def run_once(*, items, tts, decoder, sink, backstop, sleeper,
                   refill_budget_seconds, loudness_target_lufs: float,   # NEW (C3)
                   sample_rate: int, channels: int,                      # NEW (C4 assert)
                   transition_silence: float = 0.0, maxsize: int = 2) -> None:
    _assert_station_format(backstop=backstop, sample_rate=sample_rate, channels=channels)  # C4
    buffer = LookAheadBuffer(maxsize=maxsize)
    producer = Producer(items=items, tts=tts, decoder=decoder, buffer=buffer,
                        backstop=backstop, loudness_target_lufs=loudness_target_lufs)  # C3
    player = Player(buffer=buffer, sink=sink, sleeper=sleeper, backstop=backstop,
                    refill_budget_seconds=refill_budget_seconds,
                    transition_silence=transition_silence)
    await asyncio.gather(producer.run(), player.run(count=len(items)))
```

**Key decisions:**
- **C3:** `pipeline/__init__.py` (the sole `Producer` caller) **and** the `Producer(...)` call inside it are updated in the **same increment (P2-6)**; both files in the touched-files list. Without this, `run_once` `TypeError`s and every pipeline test breaks.
- **Q9/R23:** `normalize_to` is wrapped in `asyncio.to_thread` **now** — R128 is real CPU work and the producer shares the audio event loop (§5.2/§11). Done pre-emptively, not "measure first," per the ruling.
- **Backstop normalized once at construction** (caller / coordinator), never per-play. The producer's backstop branch does **not** call `normalize_to`. P2-6 spies that `normalize_to` is never invoked on the backstop path (H14-row), and the player logs INFO when it emits a backstop and when normal audio resumes (H14-row).

---

## 5. Testable / Hardware Split (per module)

CI runs `-m "not hardware"` with package `--cov-fail-under=80`, **≥90% on real-logic modules**. The **only** `pragma: no cover` lines are the literal `subprocess.run(...)` calls.

| Module | PURE (unit-tested, no binary, CI) | HARDWARE (`@pytest.mark.hardware` + the one `pragma: no cover` line) |
|---|---|---|
| `audio/loudness.py` | **everything** — `measure_lufs`, `normalize_to`, pad-then-measure, silence→None, clamp WARNING, immutability | *(none)* |
| `audio/resample.py` | `to_rate` (poly math, no-op identity) | *(none)* |
| `audio/decode.py` | `build_ffmpeg_argv`, `parse_pcm_f32le`, `map_ffmpeg_error`, `map_subprocess_exception` | `FfmpegDecoder._run`'s `subprocess.run` — one smoke decode of a tiny real file |
| `dj/tts.py` | `wav_bytes_to_buffer`, `build_piper_argv`, `build_espeak_argv`, `_map_tts_error`, `_map_tts_exception` | `_run_to_buffer`'s `subprocess.run` (piper + espeak) — one smoke each |
| `audio/binaries.py` | `resolve_binary`, `preflight_binaries` (monkeypatch `shutil.which`, `tmp_path` files) | *(none)* |
| `pipeline/producer.py`+`__init__.py` | loudness wiring, `to_thread`, format-desync assert (Fake/Stub) | *(none)* |
| `config.py` | bound, typed providers, H15 default | *(none)* |

### Key test list (folded per increment in §6)

**Loudness — NON-GAMEABLE round-trip (both polarities):**
```python
def test_loud_tone_is_attenuated():
    sr = 48_000; t = np.linspace(0, 2, sr*2, endpoint=False, dtype=np.float32)
    loud = AudioBuffer((0.9*np.sin(2*np.pi*1000*t)).reshape(-1,1), sr, 1)
    pre = measure_lufs(loud)
    out = normalize_to(loud, target_lufs=-23.0)
    assert pre > -23.0                                   # precondition: it WAS louder than target
    assert abs(measure_lufs(out) - (-23.0)) < 0.6       # post ~= target
    assert float(np.max(np.abs(out.samples))) < float(np.max(np.abs(loud.samples)))  # amplitude DOWN

def test_quiet_tone_is_amplified():
    ...                                                  # symmetric: pre < target, amplitude UP, post ~= target
```
Plus: idempotence (twice ≈ once); ±1.0 clip invariant (H16); clamp engages + **WARNING logged naming track + LUFS** (caplog, H17); **input immutable** via `np.testing.assert_array_equal(loud.samples, pre_copy)`.

**Pad-then-measure (Q4/H4 — the corrected edge):**
```python
def test_short_audible_patter_is_normalized_not_passed_through():
    sr = 48_000; t = np.linspace(0, 0.25, int(sr*0.25), endpoint=False, dtype=np.float32)  # 250 ms
    patter = AudioBuffer((0.05*np.sin(2*np.pi*200*t)).reshape(-1,1), sr, 1)               # quiet+short
    out = normalize_to(patter, target_lufs=-16.0, track_label="patter")
    assert out is not patter                              # NOT passthrough -- it was padded+measured+gained
    assert out.frames == patter.frames                   # padding never reaches the output
    assert float(np.max(np.abs(out.samples))) > float(np.max(np.abs(patter.samples)))    # amplified
def test_empty_buffer_is_true_passthrough():
    empty = AudioBuffer.silence(seconds=0.0); assert normalize_to(empty, target_lufs=-16.0) is empty
def test_digital_silence_measures_none():
    assert measure_lufs(AudioBuffer.silence(seconds=1.0)) is None
```

**Decode parser — committed golden + alignment guards (C8):**
```python
def test_parse_pcm_golden_endianness():
    raw = struct.pack("<f", 0.5) * 1                     # one mono sample
    buf = parse_pcm_f32le(raw, sample_rate=48_000, channels=1)
    assert buf.samples.shape == (1, 1) and abs(float(buf.samples[0,0]) - 0.5) < 1e-7
def test_parse_pcm_not_multiple_of_4_raises_fatal():
    with pytest.raises(ProviderFatal):
        parse_pcm_f32le(b"\x00\x00\x00", sample_rate=48_000, channels=2)     # %4 != 0
def test_parse_pcm_whole_samples_but_not_whole_frames_raises_fatal():
    with pytest.raises(ProviderFatal):
        parse_pcm_f32le(struct.pack("<f", 0.1), sample_rate=48_000, channels=2)  # %4==0, %(4*2)!=0
def test_parse_pcm_empty_raises_fatal():
    with pytest.raises(ProviderFatal): parse_pcm_f32le(b"", sample_rate=48_000, channels=1)
```

**Resample:**
```python
def test_resample_22050_to_48000_frame_count_and_rate():
    buf = AudioBuffer(np.zeros((22050,1), np.float32), 22050, 1)
    out = to_rate(buf, 48_000)
    assert out.sample_rate == 48_000 and abs(out.frames - round(22050*48000/22050)) <= 1
def test_resample_noop_returns_same_object():
    buf = AudioBuffer(np.zeros((100,1), np.float32), 48_000, 1); assert to_rate(buf, 48_000) is buf
# + stereo, + downsample 48k->22.05k
```

**TTS argv (incl. speed math) + WAV golden:**
```python
def test_build_piper_argv_length_scale_is_inverse_speed():
    argv = build_piper_argv("/p", Path("/v/en.onnx"), "/tmp/o.wav", speed=2.0)
    assert "--length_scale" in argv and argv[argv.index("--length_scale")+1] == repr(0.5)
def test_build_piper_argv_zero_speed_is_fatal():
    with pytest.raises(ProviderFatal): build_piper_argv("/p", Path("/v.onnx"), "/o", speed=0.0)
def test_build_espeak_argv_speed_scales_wpm():
    cfg = EspeakTTSConfig(backend="espeak", voice="en", speed=2.0, pitch=40)
    argv = build_espeak_argv("espeak-ng", cfg, "/o.wav"); assert "350" in argv  # round(175*2)
def test_wav_golden_round_trip():
    # wave.open(BytesIO) write known s16 frames -> wav_bytes_to_buffer -> assert shape/rate/values
def test_wav_framerate_zero_is_fatal(): ...              # §3.4
```

**Error mapping / exceptions (no real binary):**
```python
def test_map_ffmpeg_error_missing_file_is_fatal(): assert isinstance(map_ffmpeg_error(1,"No such file or directory"), ProviderFatal)
def test_map_ffmpeg_error_unknown_stderr_is_unavailable(): assert isinstance(map_ffmpeg_error(69,"weird"), ProviderUnavailable)
def test_map_ffmpeg_error_empty_stderr(): isinstance(map_ffmpeg_error(1,""), ProviderUnavailable)
def test_map_subprocess_filenotfound_is_fatal(): assert isinstance(map_subprocess_exception("ffmpeg", FileNotFoundError()), ProviderFatal)
def test_map_subprocess_timeout_is_unavailable():
    exc = subprocess.TimeoutExpired(cmd="ffmpeg", timeout=120)
    assert isinstance(map_subprocess_exception("ffmpeg", exc), ProviderUnavailable)
def test_decode_missing_binary_raises_fatal(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    with pytest.raises(ProviderFatal): asyncio.run(FfmpegDecoder(binary="nope").decode(track))
def test_decode_timeout_raises_unavailable(monkeypatch):  # H14 acceptance
    def boom(*a, **k): raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=120)
    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(ProviderUnavailable): asyncio.run(FfmpegDecoder().decode(track))
```

**binaries / preflight:**
```python
def test_resolve_binary_path_miss_names_remedy(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda n: None)
    with pytest.raises(ConfigError, match="apt install ffmpeg"):
        resolve_binary(None, "ffmpeg", remedy="Install ffmpeg (e.g. `apt install ffmpeg`)...")
def test_resolve_binary_non_executable_rejected(tmp_path):
    f = tmp_path/"b"; f.write_text("x"); f.chmod(0o644)
    with pytest.raises(ConfigError, match="not executable"): resolve_binary(f, remedy="...")
def test_preflight_piper_no_binary_names_mouse_collision(...):   # H16
    with pytest.raises(ConfigError, match="mouse tool"): preflight_binaries(cfg_piper_no_binary)
def test_preflight_espeak_without_block_defaults_to_path(...):   # H15: no KeyError
def test_preflight_missing_voice_onnx_rejected(tmp_path): ...
```

**Producer / pipeline (no binary):**
```python
async def test_producer_normalizes_every_segment(): ...      # each enqueued segment ~= target
async def test_producer_backstop_path_not_renormalized(monkeypatch):
    spy = MagicMock(); monkeypatch.setattr(producer_mod, "normalize_to", spy)
    # FailingDecoder -> backstop; assert spy NOT called for that item (H14-row)
async def test_run_once_threads_loudness_target():  ...      # C3: run_once accepts + forwards it
def test_run_once_format_desync_raises():                    # C4
    with pytest.raises(ValueError, match="desync"):
        asyncio.run(run_once(..., backstop=AudioBuffer.silence(seconds=1, sample_rate=22050),
                             sample_rate=48000, channels=1, loudness_target_lufs=-16.0))
async def test_player_logs_backstop_emit_and_resume(caplog): ...   # H14-row
```

**Config:**
```python
def test_loudness_target_positive_rejected(): pytest.raises(ValidationError) ... loudness_target_lufs=5.0
def test_loudness_target_below_minus40_rejected(): ... loudness_target_lufs=-160.0   # Q5
```

**Hardware (excluded from CI floor):** `test_ffmpeg_decodes_real_wav`, `test_piper_speaks`, `test_espeak_speaks` — each a single smoke test asserting a non-silent buffer at the station rate.

---

## 6. Increment Breakdown (dependency-ordered, touched files + acceptance gates)

Each increment: strict TDD (RED → panel-reviewed → GREEN), ruff + ruff-format + mypy `--strict` clean, ≥90% on the real-logic module, ends with a `docs/decisions/00XX-phase2-tests-<area>.md` record.

| Inc | Scope | Touched files | Depends on | Acceptance gate |
|---|---|---|---|---|
| **P2-1** | `audio/loudness.py` + deps + `StationConfig` bound | `audio/loudness.py` (NEW), `pyproject.toml`, `config.py`, `README.md` (aarch64 note) | deps only | Loud tone attenuated / quiet tone amplified, **both polarities**, post ≈ target ±0.6; **pad-then-measure** normalizes 250 ms audible patter (not passthrough); empty/silent → true passthrough/None; ±1.0 clip; **clamp WARNING names track+LUFS** (caplog); **input immutable** (assert_array_equal vs pre-copy); positive/<−40 LUFS config rejected; `pyloudnorm>=0.2.0,<0.3` + `scipy>=1.15,<2` resolve |
| **P2-2** | `audio/resample.py` `to_rate` | `audio/resample.py` (NEW) | numpy/scipy | 22.05k↔48k frame count `round(in*tgt/src)±1`, `sample_rate==tgt`, dtype float32; mono+stereo; **`to_rate(buf, buf.sample_rate) is buf`** |
| **P2-3** | `audio/decode.py` `FfmpegDecoder` (pure parser/argv/error-map/exc-map + thin shell + timeout) | `audio/decode.py` (extend) | P2-2 | **golden** `struct.pack("<f",0.5)→0.5` + endian; `%4!=0` and `%4==0 but %(4*ch)!=0` and empty → `ProviderFatal`; argv has `-ar/-ac/-f f32le/-`; error-map Fatal-vs-Unavailable incl. empty/multiline stderr; **missing-binary→`ProviderFatal`**, **`TimeoutExpired`→`ProviderUnavailable`** (H14); corrupt-file→backstop (H12); **hardware** smoke (not in CI floor); `pragma:no cover` only on `subprocess.run` |
| **P2-4** | `config.py` typed providers (R16/H15) + `audio/binaries.py` separate preflight (H20) | `config.py` (extend), `audio/binaries.py` (NEW) | errors, config | typed inner-key parsing (typo'd inner key/path → `ConfigError`); **`_validate_config` stays binary-free (all existing config tests pass)**; `preflight_binaries` separate; `resolve_binary` PATH-miss + non-executable name the **remedy**; **piper no-PATH-fallback + mouse-collision message (H16)**; **espeak no-block default (H15, no KeyError)**; missing `{voice}.onnx` rejected |
| **P2-5** | `dj/tts.py` `PiperTTS`+`EspeakTTS` (pure builders incl. speed math + WAV parser + error/exc-map + thin shell + timeout) | `dj/tts.py` (NEW) | P2-2, P2-4 | argv maps voice/**speed math** (`length_scale=1/speed`, `-s round(175*speed)`), `speed<=0`→`ProviderFatal`; WAV golden + framerate≤0/width≠2→`ProviderFatal`; resampled to station rate (H5); empty text→0 s silence at station rate; **missing-binary→`ProviderFatal`**, **timeout→`ProviderUnavailable`** (H14); bad-voice→`ProviderFatal`; **hardware** piper+espeak smoke; `pragma:no cover` only on `subprocess.run` |
| **P2-6** | loudness wiring + `run_once` threading (C3) + format-desync assert (C4) + player backstop logging (H14-row) + README prereqs (H19) | `pipeline/producer.py` (extend), **`pipeline/__init__.py` (extend, C3)**, `README.md` (NEW prereqs section) | P2-1, P2-3, P2-5 | every enqueued segment ≈ target (or short-patter padded-normalized); **backstop NOT re-normalized (spy `normalize_to`)**; `normalize_to` wrapped in `asyncio.to_thread` (Q9); ProviderError→backstop intact; **`run_once` accepts+forwards `loudness_target_lufs` (no TypeError); all pipeline tests green**; **format-desync raises at construction (C4 regression test)**; player logs INFO on backstop emit + resume; package `--cov-fail-under=80` holds |

**Parallelism:** P2-1, P2-2, P2-4 are independent (deps/config only) and may land in parallel. P2-3 and P2-5 both need P2-2; P2-5 also needs P2-4. P2-6 is the integration capstone needing P2-1/3/5.

---

## 7. Resolutions (formerly "Open Questions" — now DECIDED)

1. **Q1 — PCM format = `f32le`.** Zero conversion, exact dtype match. Mono f32 ≈ 44 MB / 4-min track (RAM-safe at depth 1–2 on the Pi-4 4 GB floor, D1). Free intermediates: `del raw` after parse; account for the **transient ≈3× peak** (decode + parse copy + normalize float64) ≈130 MB momentarily — still under the floor mono. **STEREO doubles everything and is the H7/H21 streaming-decode trigger.**
2. **Q2 — Resampler = `scipy.signal.resample_poly`** in `audio/resample.py` (pure). Decode rate via ffmpeg `-ar`; TTS + everything else via `to_rate`. **No second ffmpeg subprocess.**
3. **Q3 — WAV parsing = stdlib `wave`; `soundfile` DROPPED** from deps. Piper/espeak emit canonical PCM WAV; the s16/framerate guards cover the structural cases.
4. **Q4 — Short patter = pad-then-measure** (raw passthrough violated §10). Pad short-but-audible buffers with **trailing silence to ≥400 ms** (`_PAD_TARGET_SECONDS=0.45`), measure the **padded** buffer (R128's −70 LUFS gate drops the silence), apply the gain to the **ORIGINAL** buffer. **True passthrough only for empty / digitally-silent** buffers (`measure_lufs → None`).
5. **Q5 — `loudness_target_lufs` `ge=-40.0, le=0.0`.** Keep `_MAX_GAIN_DB=30` but **log at WARNING** when it engages, naming track + measured LUFS.
6. **Q6 — mono v1.** Lock ONE station-level `(sample_rate, channels)` shared by backstop + every segment + transition silence; **assert it** (C4).
7. **Q7 — loudness mandatory (§10); no skip option.**
8. **Q8 — fail-fast at boot in a SEPARATE `preflight_binaries(config)`**, NOT folded into `_validate_config` (the config suite validates piper-station configs without real binaries; folding would break it — confirmed against `tests/config/test_config.py`).
9. **Q9 — `normalize_to` wrapped in `asyncio.to_thread` NOW** in `producer.py` (§5.2/§11/R23).

---

## 8. Risks & Hardening (H-series, continued)

| ID | Risk | Mitigation / disposition |
|---|---|---|
| **H7** *(carry)* | Whole-track decode buffers a full track; f32le doubles vs s16. | Accepted Phase 2 (depth 1–2 mono ≈ 2 buffers/station). **Streaming + running-R128 is the named Phase-3 refinement**, triggered by stereo. |
| **H8** *(carry)* | `scipy` must have aarch64 wheels. | Confirmed `manylinux aarch64` cp311/cp312. Prose pin, no `platform_machine` marker. |
| **H14** *(new)* | A blocking subprocess hangs → producer stalls → buffer starves → backstop loops. | `timeout=` on every `subprocess.run` (`decode_timeout_seconds=120`, `tts_timeout_seconds=30`, config-tunable); `TimeoutExpired → ProviderUnavailable`. **P2-3/P2-5 acceptance gate.** |
| **H15** *(new)* | Piper reloads ~65 MB ONNX per call; on a boot SD that's ≈2.6 s/patter. | **Document: keep `voices_dir` on FAST storage (USB SSD/NVMe), not the boot SD.** Persistent piper process / `piper-tts` PyPI package = Phase-3 optimization. Temp WAVs: `NamedTemporaryFile` (per-call, unique, auto-deleted); test asserts cleanup. |
| **H16** *(new)* | Debian's `piper` package is an unrelated **mouse-emulation** tool; PATH fallback would spawn the wrong binary. | **No `shutil.which("piper")` fallback.** Require explicit `tts_providers.piper.binary`; `ConfigError`/`ProviderFatal` names the collision + piper-TTS release URL. |
| **H17** *(new)* | Near-silent track measures very low LUFS → huge gain → noise. | `_MAX_GAIN_DB=30` clamp + **WARNING** naming track + measured LUFS (Q5). |
| **H18** *(new)* | `_map_*_error` stderr string-matching is brittle across versions → a Fatal misclassified retries forever under failover. | Centralized + unit-tested (§3.4 table); **retryable (`ProviderUnavailable`) is the safe default** for unknown stderr. Tightens in one place when `dj/failover.py` lands (Phase 3). |
| **H19** *(new)* | Boot preflight depends on system binaries → a box without them can't boot a real config. | Scoped to backends a station actually uses; the suite never loads such a config. **NEW README "Phase 2 runtime prerequisites"** section (below). `resolve_binary` `ConfigError`s name the remedy. |
| **H20** *(new)* | Folding binary checks into `_validate_config` breaks the entire config test suite (all tests build piper configs, none provide real binaries). | **Separate `preflight_binaries(config)`** called by the daemon entrypoint after `load_config`; `_validate_config` stays binary-free. Confirmed against `tests/config/test_config.py`. |
| **H21** *(new)* | Transient RAM peak: decode (44 MB) + parse copy + normalize float64 ≈ **3×** momentarily (~130 MB/track mono). | `del raw` after parse; float64 falls out of scope. Acceptable mono on the 4 GB floor; **stereo is the streaming trigger** (ties to H7). Flag to load-test under D1/F1. |

**NEW README section — "Phase 2 runtime prerequisites" (H19/H13):**
- Install commands: `apt install ffmpeg espeak-ng`; **piper-TTS** from the rhasspy/piper releases (NOT `apt install piper` — that is a mouse tool); download a voice and place `{voice}.onnx` in `voices_dir`.
- **Keep `voices_dir` on fast storage** (USB SSD/NVMe), not the boot SD (H15).
- Annotated `config.json` snippet: `tts_providers.piper {binary, voices_dir}`, `tts_providers.espeak {binary}`, `ffmpeg_binary`, `decode_timeout_seconds`, `tts_timeout_seconds`, `loudness_target_lufs` (range −40…0, default −16).

**Carried-forward, unchanged:** producer's "any `ProviderError` → backstop" stays provisional with the 0009-P7 TODO (Phase-3 failover branches `ProviderFatal` vs retryable). H11 backstop-exhaustion and H12 missing-content→backstop now have a real decode path: P2-3 tests a corrupt/missing file → `ProviderError` → backstop, not a crash.

---

## 9. Success Criteria (phase gate)

- [ ] A real file decodes through `FfmpegDecoder` → correctly-shaped `(frames, channels)` float32 `AudioBuffer` at the station rate (hardware smoke + pure parser/golden tests).
- [ ] Piper and espeak each synthesize the Phase-1 template patter → non-silent buffer at the station rate (hardware smoke + pure builder/parser tests); speed math is unit-tested.
- [ ] Every rendered segment (track and patter) is normalized to `loudness_target_lufs`; re-measure within ±0.6 LUFS; **short audible patter is padded-then-normalized (not passed through)**; only empty/silent passes through; correction direction is correct **both polarities**.
- [ ] `loudness_target_lufs` rejects positive **and** < −40 values; ffmpeg/piper/espeak binaries are preflighted **at boot in `preflight_binaries`** (not `_validate_config`) with actionable, remedy-naming `ConfigError`s; **the full existing config suite still passes**.
- [ ] Subprocess timeouts (`decode_timeout_seconds`, `tts_timeout_seconds`) map `TimeoutExpired → ProviderUnavailable`; missing binary → `ProviderFatal`.
- [ ] One station-level `(sample_rate, channels)` for backstop + every segment + transition silence, **asserted at construction**; a desync raises (regression test).
- [ ] `run_once` accepts and forwards `loudness_target_lufs`; no `TypeError`; all pipeline tests green.
- [ ] Package `--cov-fail-under=80`; real-logic modules ≥90%; the **only** `pragma: no cover` lines are the literal `subprocess.run` calls; `-m "not hardware"` green; ruff + ruff-format + mypy `--strict` clean.
- [ ] No real binary on the CI path; all PCM/WAV/loudness/resample/error-mapping logic proven with synthetic inputs (incl. committed golden bytes).
- [ ] **Panel ratification recorded** for the ElevenLabs **sequencing** override (D5 acknowledged; cloud + failover → Phase 3). If declined, ElevenLabs + minimal failover move into this phase.

---

**Files this plan creates or touches** (all absolute):
- NEW: `/home/sydney/GitHub/Pirate-Radio/src/pirate_radio/audio/loudness.py`
- NEW: `/home/sydney/GitHub/Pirate-Radio/src/pirate_radio/audio/resample.py`
- NEW: `/home/sydney/GitHub/Pirate-Radio/src/pirate_radio/audio/binaries.py`
- NEW: `/home/sydney/GitHub/Pirate-Radio/src/pirate_radio/dj/tts.py`
- EXTEND: `/home/sydney/GitHub/Pirate-Radio/src/pirate_radio/audio/decode.py`
- EXTEND: `/home/sydney/GitHub/Pirate-Radio/src/pirate_radio/pipeline/producer.py`
- EXTEND: `/home/sydney/GitHub/Pirate-Radio/src/pirate_radio/pipeline/__init__.py` (C3 — `run_once` loudness/format threading)
- EXTEND: `/home/sydney/GitHub/Pirate-Radio/src/pirate_radio/config.py` (`ge=-40,le=0` bound; typed `PiperProviderConfig`/`EspeakProviderConfig`; `ffmpeg_binary`; timeouts)
- EXTEND: `/home/sydney/GitHub/Pirate-Radio/pyproject.toml` (`pyloudnorm>=0.2.0,<0.3`, `scipy>=1.15,<2`; drop `soundfile`; aarch64 prose pin)
- EXTEND: `/home/sydney/GitHub/Pirate-Radio/README.md` (NEW "Phase 2 runtime prerequisites" — H19)
- Tests under `/home/sydney/GitHub/Pirate-Radio/tests/audio/`, `/tests/dj/`, `/tests/pipeline/`, `/tests/config/` mirroring §5.

---

## Rev 2 — Panel disposition & binding amendments

**Vote (Rev 2):** Old Man AYE, Fact Checker AYE, QA AYE, Field Operator AYE, Senior Dev AYE, RPi Expert AYE, **Devil's Advocate NAY → 6 AYE / 1 NAY → ADOPTED** (charter ≤1 NAY). The DA's dissent carried one genuine CRITICAL and one HIGH that are folded in below as **binding amendments** (must be honored during the increments), plus minor LOWs the per-increment pre-RED reviews will enforce.

### A1 (DA CRITICAL) — `preflight_binaries` must actually be CALLED on the boot path
Rev 2 defined `preflight_binaries(config)` but wired no caller, so the fail-fast (Success Criterion #4) was unreachable — a missing/mis-pathed binary would degrade to silent backstop-forever at first render. **Amendment:** `load_config` gains a keyword `preflight: bool = True`; when true it calls `preflight_binaries(config)` AFTER `_validate_config` returns. This preserves H20's binary-free `_validate_config` (the binary check is a distinct step) while guaranteeing production boots fail fast. The existing config-test suite stays binary-free by routing through its `_load` helper with `preflight=False` (one helper change, not ~40 sites); new preflight tests call `preflight=True` with a monkeypatched `resolve_binary` (or a config naming a nonexistent binary path) and assert `ConfigError`. **Lands in P2-4**; its acceptance gate adds: "`load_config(..., preflight=True)` raises `ConfigError` naming the remedy when a used backend's binary is absent; `preflight=False` (and the existing suite) stay binary-free."

### A2 (DA HIGH / Fact Checker LOW-1) — short-patter normalization must be ASSERTED-TO-TARGET, and the prose mechanism corrected
The pad-then-measure design is kept, but two corrections: (1) the rationale that R128's −70 absolute gate "drops" the trailing silence is **wrong** — for a sub-400ms clip padded to ~0.45s the silence sits *inside* the straddling 400ms gating blocks and **dilutes** their K-weighted power, biasing the measurement ~1–2 LUFS low (so the clip airs ~1–2 LUFS above target). Fix the docstrings/§4.1 accordingly. (2) The P2-1 acceptance gate MUST assert post-normalization **measured LUFS within tolerance** for a real short (~0.3s) clip — not merely "amplitude increased". If the dilution bias exceeds tolerance, mitigate (measure **momentary**/M loudness for sub-block buffers, or pad to a longer window, or accept a *documented, bounded* offset). "Asserted louder" alone is insufficient.

### Minor amendments (LOW — enforced at per-increment pre-RED review)
- **Old Man:** replace bare `assert isinstance(prov, …)` in `preflight_binaries` with an explicit `if not isinstance(...): raise ConfigError(...)` (asserts are stripped under `python -O`). Add a module-load invariant `_PAD_TARGET_SECONDS > _MIN_BLOCK_SECONDS`. Note the `NamedTemporaryFile` read-inside-`with` is Linux-only (fine for the Pi target).
- **Fact Checker:** drop the false "zero-copy"/`ascontiguousarray`-copies claims (a reshape of a contiguous `frombuffer` view does NOT copy; to actually release `proc.stdout` early, force a real copy with `np.array(..., dtype=np.float32)` and `del raw`); the true transient peak is ~4× (raw + float64 measure-copy + gained), still inside the 4GB floor. Remove the unsupported "0.4–0.8s returns -inf for audible speech" claim (the real driver is the sub-400ms `ValueError`).
- **QA:** the elided `test_quiet_tone_is_amplified` / golden test bodies must include the explicit direction + value asserts when authored; add a `to_rate(target_rate<=0)` guard test and a "ffmpeg-only, no TTS preflight" path test.
- **Field Operator:** the player's two `logger.info` backstop-emit / resume calls are spec'd but unsketched — add them in P2-6; author the literal annotated `config.json` block (incl. `ffmpeg_binary`, `decode_timeout_seconds`, `tts_timeout_seconds`, `tts_providers.espeak`) for the README, since design §12's example omits them.

**Process gate:** the ElevenLabs Phase-3 *sequencing* override (D5 puts it in v1; this plan sequences it to Phase 3 because it is a cloud provider meaningless without `dj/failover.py`) is recorded and ratified by this adoption vote — noted in `docs/decisions/0016`.