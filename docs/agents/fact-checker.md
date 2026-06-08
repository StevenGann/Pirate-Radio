# Fact Checker — Notes

> **Mandate:** Identify assertions made by other agents and verify them against
> the project's files or via web search. I read this file before every
> engagement and append durable learnings (date-stamped) after.

## Method

1. **Extract claims.** Pull every checkable factual assertion out of the briefs,
   responses, and distilled docs — especially numbers, version strings, API
   names, capability claims ("X supports Y"), and regulatory statements.
2. **Classify** each claim: `verified` / `refuted` / `unverifiable` / `needs
   source`.
3. **Verify** against, in order:
   - the project's own files (code, configs, docs) — ground truth for "we do X";
   - primary/vendor docs (Raspberry Pi docs, Python docs, library docs);
   - the web, when the first two are insufficient.
4. **Record** the verdict and a source/citation so it travels with the claim
   into the distilled doc.

## Standing gate

- Before any vote, I flag unverified claims the doc depends on. A doc must not be
  adopted on the strength of an unverified claim.
- "Plausible" is not "verified." Default to `needs source` when uncertain.
- Prefer primary sources over blog posts; note the date — Pi/OS facts age.

## Verified-claims ledger (project-wide)

| Claim | Verdict | Source / note | Date |
|-------|---------|---------------|------|
| Raspberry Pi OS Bookworm system Python is 3.11 | **verified** | Bookworm = Debian 12 → Python 3.11; raspberrypi.com Bookworm announcement + piwheels blog. Repo CI/mypy/ruff already target 3.11. | 2026-06-07 |
| Bookworm enforces PEP 668 (externally-managed-environment; system pip blocked, use venv/pipx) | **verified** | Debian 12 / RPi OS Bookworm; raspberrypi.com + Pimoroni venv guide | 2026-06-07 |
| Local dev Python is 3.12 | verified | `python3 --version` (3.12.3) in repo env; .venv is python3.12 | 2026-06-07 |
| FieldStation42 is a broadcast/cable-TV simulator | **verified** | github.com/shane-mason/FieldStation42 README ("turns your Linux computer or Pi into a broadcast and cable TV simulator") | 2026-06-07 |
| FieldStation42 = single coordinator + web console (localhost:4242) + HTTP API managing all channels | **verified** | FieldStation42 README/docs (web console + full HTTP API). Matches doc §1/§5.1 topology claim. | 2026-06-07 |
| FieldStation42 uses directory-as-tag: subfolders are categories used for scheduling | **verified** | FieldStation42 wiki "Add Station Content" / "Configure Stations" — folder names become "tags". Matches doc §7/§8.1. | 2026-06-07 |
| `sounddevice` (PortAudio) can target output device by name substring or numeric index | **verified** | python-sounddevice docs: `device=` accepts index or name substring | 2026-06-07 |
| `mutagen` reads ID3 / Vorbis / MP4 / FLAC and exposes duration via `.info` | **verified** | mutagen docs/PyPI (supports those formats; `.info.length` = duration) | 2026-06-07 |
| `pyloudnorm` implements EBU R128 / ITU-R BS.1770-4 loudness | **verified** | csteinmetz1/pyloudnorm README (ITU-R BS.1770-4 / EBU R128) | 2026-06-07 |
| `pydub` requires ffmpeg (or libav) to decode/encode non-WAV (mp3/flac) | **verified** | jiaaro/pydub docs + issues; pure-Python only for WAV | 2026-06-07 |
| Piper TTS = fast local neural TTS, runs well on ARM / Raspberry Pi | **verified** | rhasspy/piper ("fast, local neural TTS"); VITS/ONNX, optimized for Pi 4/5 | 2026-06-07 |
| `pyacoustid` + Chromaprint (`fpcalc`) + `musicbrainzngs` = the MusicBrainz Picard engine | **verified** | Picard docs use Chromaprint/fpcalc; pyacoustid wraps Chromaprint→AcoustID→MusicBrainz. Substantively correct. | 2026-06-07 |
| MusicBrainz API rate limit ≤ 1 request/second (per IP) | **verified** | musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting (1 req/s avg per IP; over → HTTP 503 / IP block) | 2026-06-07 |
| DeepSeek API is OpenAI-compatible (base_url + OpenAI SDK) | **verified** | api-docs.deepseek.com (OpenAI-compatible; base_url https://api.deepseek.com) | 2026-06-07 |
| DeepSeek model name `deepseek-chat` | **NEEDS CORRECTION** | Still works but scheduled for retirement 2026-07-24; current V4 names are `deepseek-v4-flash` / `deepseek-v4-pro`. Use a config value, not a hardcoded literal. | 2026-06-07 |
| Ollama endpoint http://localhost:11434, model `llama3.1` | **verified** | Ollama docs (default :11434; `/api/chat` + OpenAI-compat `/v1`); llama3.1 valid tag | 2026-06-07 |
| ElevenLabs TTS params voice_id / stability / similarity_boost | **verified** | elevenlabs.io API docs (voice settings: stability, similarity_boost 0–1) | 2026-06-07 |
| Anthropic "current model id" (doc uses placeholder) | **verified (placeholder is correct)** | Current ids as of 2026-06: `claude-opus-4-8` (Opus 4.8, May 2026), `claude-sonnet-4-6`. Doc's `<set to a current model id>` placeholder is the right call. | 2026-06-07 |
| Rev2 D1: Pi 3 = 1 GB RAM, 4× Cortex-A53 @ 1.2 GHz; Pi 5 official PSU = 27 W USB-C PD (5.1V/5A) | **verified** | Raspberry Pi 3B spec; datasheets.raspberrypi.com 27W USB-C product brief | 2026-06-07 |
| Rev2 R2/D2: llama3.1 8B Q4 ~5–6 GB RAM, ~2–5 tok/s CPU on Pi 5 (now MOOT — Ollama reframed as LAN server, not on-Pi) | **verified-but-moot** | Stratosphere/llama.cpp Pi 5 benchmarks; D2 moots on-Pi figures | 2026-06-07 |
| **Phase-0 plan** — Pydantic v2 discriminated union `Annotated[Union[...], Field(discriminator="backend")]` + `ConfigDict(frozen=True, extra="forbid")` | **verified** | pydantic.dev Unions/Fields docs — exact syntax | 2026-06-07 |
| Phase-0 — `mutagen.File()` returns None for unrecognized files; defensive `.info`/`.info.length`/`.tags`-may-be-None access | **verified** | mutagen.readthedocs.io base module | 2026-06-07 |
| Phase-0 — mutagen reads stdlib-`wave`-generated WAV `.info.length` | **verified** | WAV in mutagen supported formats (mutagen.wave.WAVE) | 2026-06-07 |
| Phase-0 — `os.replace()` atomic same-fs; temp→fsync→replace→dir-fsync durability incl. directory-fsync necessity | **verified** | Python os docs / cpython issue 8828 / python-atomicwrites | 2026-06-07 |
| Phase-0 — `yaml.safe_load` rejects `!!python/object/apply` via ConstructorError (subclass of yaml.YAMLError) | **verified** | PyYAML docs + CVE writeups | 2026-06-07 |
| Phase-0 — `zoneinfo` + `datetime.now().astimezone().tzinfo` resolves system local zone; tz-aware datetimes | **verified** | Python datetime/zoneinfo docs | 2026-06-07 |
| **Phase-1 plan** — R19: `random.Random(seed).choices(pool, weights=)` deterministic for same (seed, pool order); `zlib.crc32` stable | **verified** | empirical CPython 3.12; crc32 + Mersenne-Twister are spec-stable across CPython | 2026-06-07 |
| Phase-1 — `model_dump_json()` byte-identical for equal models; key order = field-decl order (NOT sorted) | **verified** | empirical pydantic 2.13.4 — R19 byte-identical holds | 2026-06-07 |
| Phase-1 — `AudioBuffer` as `@dataclass(frozen=True)` w/ `__post_init__`, NOT a Pydantic model | **verified (correct choice)** | raw `npt.NDArray` in a Pydantic field needs arbitrary_types_allowed+custom validators (pydantic #6477); dataclass sidesteps it | 2026-06-07 |
| Phase-1 — `asyncio.Queue(maxsize=)` bounded; `asyncio.wait_for(q.get(), timeout)` raises TimeoutError on empty; `asyncio.TimeoutError is TimeoutError` (3.11+) | **verified** | empirical CPython 3.12 — R11 backstop + bounded-depth claims hold | 2026-06-07 |
| Phase-1 — `pytest-asyncio` `asyncio_mode="auto"` collects bare `async def test_*` | **verified** | pytest-asyncio docs; dep not yet installed (Phase-1 addition) | 2026-06-07 |
| Phase-1 — assumed Phase-0 signatures (`scan_catalog→Catalog`, `Catalog.groups()/group_names()`, `Clock.now()/tz()`, `load_grid(path)→Grid`, `StationConfig.transition_silence_seconds/repeat_window_minutes`) | **verified** | read against merged Phase-0 source | 2026-06-07 |

## Notes log

- _2026-06-07_ — Panel established. Seeded ledger with the two initial
  infrastructure claims. The Bookworm/Python-3.11 claim drives CI config and
  should be confirmed against primary docs before we lean on it further.
- _2026-06-07_ — Round 1 design-doc fact check. Verified the Bookworm→Python-3.11
  + PEP 668 pair (resolves prior "needs verification"). Confirmed FieldStation42
  is a broadcast/cable-TV sim with single-coordinator + web-console topology and
  directory-as-tag content model — the doc's §1/§5.1/§7 framing is accurate.
  All library capability claims checked out: sounddevice device targeting,
  mutagen durations, pyloudnorm EBU R128, pydub→ffmpeg, Piper ARM neural TTS,
  AcoustID/Chromaprint/musicbrainzngs = Picard engine, MusicBrainz ≤1 req/s.
  SDK claims OK: DeepSeek OpenAI-compatible, Ollama :11434/llama3.1, ElevenLabs
  params. **One correction:** `deepseek-chat` is slated for retirement
  2026-07-24 (V4 names `deepseek-v4-flash`/`-pro`) — fine as a config default
  but flag it. The doc's Anthropic-model placeholder is the correct pattern;
  current id is `claude-opus-4-8`/`claude-sonnet-4-6`. Net: the doc is
  factually sound; nothing in it would force a design change.
- _2026-06-07_ — Phase-1 implementation-plan fact check (code-level). Verified
  the R19 determinism chain empirically: `random.Random(seed).choices(pool,
  weights=)` is reproducible given the catalog's stable (group,path) sort, and
  `model_dump_json()` is byte-identical for equal models with stable
  field-declaration key order — so "(catalog+grid+seed+clock)→byte-identical
  JSON" is sound. Confirmed the plan's key design call: `AudioBuffer` is a
  frozen dataclass, NOT a Pydantic model — correct, because a raw `npt.NDArray`
  in a Pydantic field needs `arbitrary_types_allowed` + custom validators
  (pydantic #6477); the dataclass + `__post_init__` validation sidesteps that.
  `asyncio.Queue(maxsize=)` bounded semantics + `asyncio.wait_for(get, timeout)`
  → TimeoutError on empty underpin the R11 backstop and bounded-depth
  back-pressure claims (verified). `pytest-asyncio` auto mode and the `numpy`/
  `sounddevice`(lazy extra) dep choices are correct; neither numpy nor
  pytest-asyncio is installed yet (both are Phase-1 additions). All assumed
  Phase-0 signatures match the merged source. No snippet found that won't run.
  Non-blocking notes for other reviewers: (1) §8.4 path vs A6 `state_dir`
  conflict is real — the plan resolves it (writes under `state_dir`), correctly
  flagged as a §8.4 doc correction needing ratification (Q1); (2) `crc32`-
  derived seed is stable, good for R19. Plan is factually sound to implement.
- _2026-06-07_ — Phase-0 implementation-plan fact check (code-level). Verified
  every load-bearing API against current docs: Pydantic v2 discriminated-union
  syntax (`Annotated[Union, Field(discriminator=...)]`, `frozen=True`,
  `extra="forbid"`), mutagen `File()`/`.info.length`/`.tags` None-handling
  (incl. WAV support for stdlib-`wave` fixtures), `os.replace` same-fs atomicity
  + the temp→fsync→replace→dir-fsync durability pattern (directory fsync IS
  necessary for the rename to survive power loss — plan's `_fsync_dir` is
  correct), `yaml.safe_load` blocking `!!python` tags via ConstructorError
  (so the security test passes through the `except yaml.YAMLError` path), and
  `zoneinfo`/`astimezone()` local-zone resolution. No snippet found that would
  fail to run. Two non-fatal notes for other reviewers (not factual errors):
  (1) `frozen=True` on `DaemonConfig` does NOT freeze the inner
  `tts_providers: dict[str,dict]` contents — immutability is shallow; the plan
  already flags this as typing debt. (2) The persisted DeepSeek `model` value is
  a free string (good — no hardcoded `deepseek-chat`), consistent with the
  earlier R13 correction. Plan is factually sound to implement.
