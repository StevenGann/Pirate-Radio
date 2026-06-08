# Distilled Design Review — PiRate Radio — **Rev 1**

> **Status:** For panel vote.
> **Source:** Round 1 reviews from all seven agents on `PiRate_Radio_Design_Doc.md`.
> **Manager's note:** This distills the panel's findings into proposed
> resolutions and concrete edits to the design doc. Items are grouped by theme.
> Each carries a **disposition**: `ADOPT` (change the doc), `ACCEPT-AS-IS`
> (no change, rationale recorded), or `USER` (needs the client's decision; my
> recommendation given). Vote is on this whole document.

The Fact Checker verified the doc's technical claims as sound; **no resolution
below is blocked by a factual error.** The one correction (`deepseek-chat`
retires 2026-07-24) is folded into R13.

---

## A. Decisions that need the user (product owner)

These are genuine product/hardware calls the panel cannot make for you. My
recommendation is given; the panel is voting on whether the recommendation is
sound, not overriding your authority.

### R1 — Pin a minimum target Pi model `USER` *(RPi Expert BLOCKER; needed by QA, Field Op, Old Man)*
"Raspberry Pi class hardware" (§1/§4) spans a >50× compute/RAM range; every
feasibility judgment depends on the model.
**Recommendation:** Require **Raspberry Pi 5 (8 GB)** with **active cooling** and
**SSD/USB boot** (not SD) as the minimum for the full 4-station + AI-DJ vision.
Add a "Deployment / Hardware" subsection to §4 pinning model, cooling, official
PSU (27 W Pi 5), powered USB hub for the dongles, and SSD boot.

### R2 — Decide the role of the **local LLM** `USER` *(RPi Expert BLOCKER; Devil's Advocate objection)*
Ollama `llama3.1` (8B, ~5–6 GB RAM resident, ~2–5 tok/s CPU-only on a Pi 5) cannot
generate patter in real time for 4 contending stations. As written (§9.3/§11/§12)
it is presented as a peer "always-available floor," which is misleading.
**Recommendation:** Reframe the failover floor honestly: **local Piper is the
always-available *voice* floor; the always-available *DJ-brain* floor is
`NullDJ` / pre-rendered generic patter, not a local LLM.** If local LLM is
desired at all, default it to a small model (`llama3.2:3b` / `phi3:mini` /
`qwen2.5:3b`) and document that local-LLM-only mode runs at reduced (sparse)
patter cadence. Cloud-LLM-primary is the intended happy path.

### R3 — Resolve content root: shared vs per-station `USER` *(§16a open; raised by Senior Dev, Old Man, QA)*
Unresolved in §16a; it determines catalog ownership and the scope of the
repeat-window dedup (`repeat_window_minutes`).
**Recommendation:** **Per-station libraries** (as currently drafted) for v1 —
simplest, keeps dedup scope local. A shared root can be added later behind the
same catalog interface. Resolve before Phase 0.

### R4 — Scope of the Control API in v1 `USER` *(Old Man MAJOR; §2 vs §15 contradiction)*
§2 lists "a control surface" as a **non-goal**; §15 declares a full FastAPI REST
plane **"in scope."** This is a direct self-contradiction.
**Recommendation:** **Defer the HTTP control plane out of v1** (the roadmap
already puts it last, Phase 6). For v1, expose read-only status via a **CLI
subcommand** over the already-persisted JSON, and rely on logs for the rest.
Remove the contradiction by marking §15 explicitly as **post-v1**. (If you want
it in v1, see R12 for the envelope/auth requirements it must then meet.)

---

## B. Resilience & operations (adopt)

### R5 — Atomic, durable state writes `ADOPT` *(Field Operator BLOCKER)*
§14 ("flat JSON, deliberately simple") is silent on *how* files are written; a
brownout mid-write corrupts the broadcast day.
**Resolution:** Mandate **write-temp → `fsync` → `os.replace()` (atomic rename)
→ `fsync` parent dir** for all state (catalog, daily schedule, resume state), and
keep a `.bak` last-known-good. Add this as a stated rule in §14.

### R6 — Corruption recovery, no crash-loop `ADOPT` *(Field Operator MAJOR)*
A truncated state file must not turn the supervisor's restart into a crash-loop.
**Resolution:** On load, parse + Pydantic-validate; on failure fall back to
`.bak`, else regenerate. Never crash-loop on bad persisted state. Add to §6/§14.

### R7 — Whole-process autostart & supervision `ADOPT` *(Field Operator MAJOR; Devil's Advocate)*
The in-process supervisor (§5.4) restarts only `asyncio` tasks — it cannot
recover a process segfault or a host reboot, and an in-process supervisor
**cannot catch a native SIGSEGV** (a crash there takes all 4 stations down).
**Resolution:** Ship a **`systemd` unit** (`Restart=on-failure`, `RestartSec`,
`After=sound.target network-online.target`, optional `WatchdogSec`). Document the
two-tier model: systemd owns the *process*, the in-process supervisor owns
*tasks*. Add a deployment note to §5.4/§14.

### R8 — Logging: separate from state; drop the query API `ADOPT` *(Old Man MAJOR×2; Devil's Advocate; RPi Expert; Field Operator)*
Strong consensus. "Flat JSON for everything" (§14) wrongly lumps **logs** in with
durable state, and the `GET /logs` query endpoint (§15) reinvents
`journalctl`/`grep`/`jq` while creating SD-wear and an unbounded append-only file.
**Resolution:**
- Keep **flat JSON for state** (catalog/schedule/resume) — endorsed.
- **Logs go to stdout/journald** (off-box shipping available); **remove the
  `GET /logs` endpoint** and the requirement that logs be a queryable JSON store.
- If structured queryable logs are later wanted, use **SQLite** (stdlib, single
  file, indexed) — not a hand-rolled JSON scanner.
- Route any high-frequency transient writes to `tmpfs`; document log
  rotation/retention. Update §14/§15.

### R9 — Timezone-aware clock; define DST/clock-step behavior `ADOPT` *(Field Operator MAJOR; QA)*
§6 uses naive `datetime`; a wall-clock schedule mis-seeks at the DST fold (spring
gap / fall repeat) and on NTP step after a boot with no RTC.
**Resolution:** Use **timezone-aware datetimes** throughout; define explicit
behavior at the DST fold and on clock-set jumps. Note Caliope's timezone and
whether it has an RTC (minor `USER` input). Add to §6.

### R10 — Stable USB audio device naming `ADOPT` *(RPi Expert MAJOR)*
Four identical cheap USB dongles enumerate with identical PortAudio name strings
and reorder across reboots — Station 2 could grab Station 4's transmitter/freq.
**Resolution:** Require **stable ALSA names via udev rules keyed on physical USB
port path**; config references those, not raw indices. §12 validation must fail
fast if 4 distinct physical ports can't be resolved. Add to §10/§12.

---

## C. Correctness of the broadcast model (adopt)

### R11 — Make "never dead air" real, and define the `find_now` gap path `ADOPT` *(Devil's Advocate objection; Senior Dev BLOCKER)*
A depth-1–2 buffer hides latency only while sufficient prior audio is playing —
**not** at cold start / post-crash resume landing on a `block_transition`, nor
across a run of short items. And `find_now` returns `(None, 0.0)` for exactly the
`transition_silence` gaps the scheduler itself creates (§8.4), with no defined
player behavior.
**Resolution:**
- Add a **guaranteed pre-rendered backstop** (canned bumper / silence asset) that
  plays the instant a buffer refill misses its deadline. Then "never dead air" is
  honest: *backstopped by canned audio.*
- State a **worst-case refill budget** and use a **deeper/warm buffer at block
  boundaries**.
- **Define the `None` / gap path** in `find_now`: play the residual gap as
  silence and advance to the next item's `planned_start` (or return next-item +
  wait rather than `None`). Update §5.3/§6/§8.4.

### R12 — Bound schedule drift in v1 (or stop persisting estimates) `ADOPT` *(Devil's Advocate objection; Senior Dev)*
`planned_start` is computed from **estimated** TTS lengths, persisted, and trusted
by `find_now` for the seek offset; soft boundaries never claw drift back until
next-day regen, and the "re-anchor at hourly IDs" fix is deferred (§6). After a
resume, `find_now` can seek to an offset that no longer exists in the actual
(longer) segment.
**Resolution:** Either **pull the hourly re-anchor into v1**, or **re-anchor
`find_now` on the nearest exact-duration track** (don't trust persisted estimated
`planned_start` for patter). Pick one in §6; do not ship unbounded same-direction
drift silently.

### R13 — Subprocess-promotion claim & DeepSeek model name `ADOPT` *(Devil's Advocate objection; Fact Checker correction)*
- The "promote player to subprocess later without restructuring" claim (§5.4/§17)
  is optimistic — it crosses the shared in-process queue, clients, catalog, and
  device handle. **Resolution:** Downgrade the claim to "expect a real refactor
  if the native lib proves unstable," **or** add a thin Phase-1 subprocess-player
  spike to prove the boundary. Keep the clean station interface either way.
- **`deepseek-chat`** retires 2026-07-24 → give the config example the same
  "set to a current model id" caveat already on the Anthropic entry. (§12)

---

## D. Code architecture & data models (adopt)

### R14 — Define `AudioBuffer` as a first-class model `ADOPT` *(Senior Dev BLOCKER)*
It flows through all three Protocols (§11) and the whole pipeline but is never
modeled; sample rate/channels/dtype are unspecified, so music/TTS rate mismatch
surfaces only at runtime.
**Resolution:** Add `AudioBuffer` to §13 with explicit `samples` (NumPy),
`sample_rate`, `channels`; require every pipeline stage to produce a normalized
buffer shape.

### R15 — Protocols must specify an error contract `ADOPT` *(Senior Dev BLOCKER)*
Failover (§9.3) can't distinguish retryable from fatal errors without a defined
exception taxonomy; today a backend may raise anything.
**Resolution:** Define a small hierarchy in the Protocol module
(`ProviderError` → `ProviderUnavailable` / `ProviderQuotaExceeded` /
`ProviderFatal`); failover retries only the retryable branch. Add Protocol
docstrings stating units, threading (which methods must go via
`asyncio.to_thread`), and idempotency. (§11)

### R16 — Replace bare `dict`s with discriminated unions `ADOPT` *(Senior Dev MAJOR)*
`dj_context: dict`, `tts: list[dict]`, `llm: dict`, `tts_providers: dict` (§13)
defeat the fail-fast validation §12 promises — a typo'd ElevenLabs param sails
through and fails mid-broadcast.
**Resolution:** Model backend params as **discriminated unions keyed on
`backend`** (`PiperTTSConfig | ElevenLabsTTSConfig | EspeakTTSConfig`, etc.); type
`dj_context` as a real model. (§12/§13)

### R17 — `ScheduleItem` as a discriminated union on `kind` `ADOPT` *(Senior Dev MAJOR)*
One model with `kind` + five mutually-exclusive optionals lets invalid states
exist (`kind="track", track=None`; a `station_id` carrying a `track`).
**Resolution:** Model as a discriminated union on `kind` so each variant carries
only its valid fields; add a `schema_version` to persisted `DailySchedule` so a
format change can't silently mis-load a resume. (§13/§14)

---

## E. Testability (adopt — these are design constraints, cheap now)

### R18 — Injectable clock everywhere `ADOPT` *(QA BLOCKER; Field Op)*
`find_now` already takes `now` (§6), but the station loop and midnight regen
(§8.6) must too. Mandate a `Clock`/`now()` dependency; never call `datetime.now()`
internally. Enables deterministic DST/rollover/gap tests.

### R19 — Seedable scheduler `ADOPT` *(QA BLOCKER)*
§8.4 selection is randomized with no seam. Inject `random.Random`/seed; require
**(catalog + grid + seed + clock) → byte-identical persisted `<date>.json`**. The
persisted artifact is the assertion target. (`USER`-ish nuance: seed derived
per-day from the date, or config-driven? Recommend date-derived for stable-but-
varying days.)

### R20 — Thin hardware seam + coverage-denominator fix `ADOPT` *(QA MAJOR×2)*
Only the literal `sounddevice` call in `SoundDeviceSink` is `@pytest.mark.hardware`;
decode/loudness/buffer/timing stay pure and off-device. **Fix the existing CI
hazard:** `--cov-fail-under=80` runs package-wide while CI runs `-m "not
hardware"`, so hardware-only lines inflate the denominator — keep that code
minimal and `pragma: no cover`, and audit the uncovered-lines report, not just the
percentage. Ship in-repo fakes (`FakeTTS`, `ScriptedDJ`, `FailingTTS`/`FailingDJ`,
`FakeAudioSink`).

### R21 — Virtual-time pipeline & failover tests `ADOPT` *(QA MAJOR/MINOR)*
Test the producer/consumer (§5.3) with `asyncio` + fakes + injected clock —
assert bounded queue depth, ordering, and stall-isolation, no real audio or
`sleep`. Test the failover chain with fakes only — zero network, no real SDK
import on the test path.

---

## F. Scope / dependency trimming (adopt)

### R22 — Trim the v1 dependency set `ADOPT` *(Old Man MINOR×3; RPi Expert)*
- **Providers:** ship **one cloud + one local floor per axis** for v1 — Claude +
  Ollama(small)/NullDJ, and Piper + espeak. Defer **DeepSeek** and **ElevenLabs**
  behind the same Protocols (zero core rework). (§11/§12/§18)
- **Drop `pydub`** — use the direct ffmpeg subprocess the doc already allows. (§10)
- **Pick one loudness path** — `pyloudnorm` *or* ffmpeg `loudnorm`, not "or".
  Recommend `pyloudnorm` (pure-Python, unit-testable). (§10)
- Offline-tagging stack (pyacoustid/Chromaprint/musicbrainzngs) stays a Phase-5
  standalone tool, **not** a runtime dependency — confirmed correct. (§7/§20)
- `Typer` vs `argparse`: stdlib `argparse` avoids a dependency for a few
  subcommands. Minor; recommend `argparse` unless the CLI grows. (§18)

---

## G. Accepted as-is (no change; rationale recorded)

- **`ACCEPT-AS-IS`** Broadcast-time model unifying cold-start and resume behind one
  `find_now` path (§6) — conceded sound by the Devil's Advocate; elegant.
- **`ACCEPT-AS-IS`** Protocol-based pluggable backends (§11) + phased "stub the core
  first" roadmap (§20) — the right kind of abstraction; serves YAGNI.
- **`ACCEPT-AS-IS`** Fail-fast Pydantic config + grid validation (§8.3/§12) and
  secrets-via-env (§12) — endorsed; pairs with R5–R7 for boot-time delivery
  (`EnvironmentFile=` root-owned 0600, or SOPS/age).
- **`ACCEPT-AS-IS`** Reactive-only quota handling (§14) — fine for a homelab; add a
  one-line caveat that a metered cloud account should set a provider spend cap.
- **`ACCEPT-AS-IS`** Grounding (§9.2) reduces fabrication of metadata facts but can't
  prevent tone/emphasis drift — don't oversell "invents no facts"; soften wording.
- **`ACCEPT-AS-IS`** RF out of scope for *code* (§4) — but **add an explicit
  acknowledgment** that operating four FM transmitters is a licensing/regulatory
  matter (FCC Part 15 limits in the US; equivalents elsewhere) that the **deployer
  owns**. Acknowledgment only, not a code change.

---

## H. Proposed concrete edits to the design doc (summary)

If this Rev is adopted, I will update `PiRate_Radio_Design_Doc.md` as follows:
new **§4 Deployment/Hardware** (R1, R7, R10); rewrite **§9.3** failover floor (R2);
resolve **§16a** (R3) and the **§2/§15** contradiction (R4); add atomic-write +
recovery + systemd to **§14/§5.4** (R5–R8); tz-aware clock + DST to **§6** (R9);
drift resolution in **§6** (R12); subprocess-claim downgrade in **§5.4/§17** and
DeepSeek caveat in **§12** (R13); `AudioBuffer`, Protocol error taxonomy,
discriminated unions, `ScheduleItem` union, `schema_version` in **§11/§13** (R14–R17);
testability constraints noted in **§5.3/§6/§8.4/§8.6/§10/§11** (R18–R21); trimmed
**§18** stack (R22); accepted-as-is wording tweaks in **§4/§9.2/§14** (G).

---

## Vote — Round 1 (2026-06-07)

Per charter: **≤ 1 NAY → adopted**; **≥ 2 NAY → Rev 2.**

| Agent | Vote | One-line reason |
|---|---|---|
| Senior Dev | **AYE** | All six concerns (R4/R11/R12/R14–R17) resolved at or above bar, doc internally coherent. |
| Old Man | **AYE** | R4/R8/R22 adopted faithfully; no speculative generality added; scope and deps trimmed. |
| Raspberry Pi Expert | **AYE** | Pi 5 model pin, local-LLM reframe, udev USB naming, logs-off-SD all captured. |
| Fact Checker | **AYE** | All new technical assertions verify against primary sources; R13 correction accurate. |
| Devil's Advocate | **AYE** | All five principled objections carry committed fixes, not acknowledgments. |
| QA Engineer | **AYE** | R18–R21 captured faithfully and enforceably; testability hardened throughout. |
| Field Operator | **AYE** | R5–R9 + RF acknowledgment adopted as written; design now deployable unattended. |

**Tally: 7 AYE / 0 NAY → ADOPTED (Round 1).**

Next: manager applies the **ADOPT** edits (§H) to `PiRate_Radio_Design_Doc.md`.
The four **USER** items (R1–R4) go to the client for decision before the doc edits
that depend on them are written.
