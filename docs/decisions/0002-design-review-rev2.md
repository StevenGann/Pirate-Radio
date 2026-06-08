# Distilled Design Review — PiRate Radio — **Rev 2**

> **Status:** For panel vote.
> **Supersedes:** Rev 1 (`0001-design-review-rev1.md`), which was adopted 7–0.
> **Why a Rev 2:** The client answered the four `USER` items (R1–R4). Two
> recommendations were **overruled** and one rested on a **misunderstanding the
> panel shared** (the "local" LLM). Those answers change the resolutions that
> depended on them. Everything in Rev 1 **not** listed below stands unchanged and
> remains adopted (R5–R21 except R8 amendment, plus the §G accept-as-is items).

---

## Client decisions (now binding)

### D1 — Hardware target *(was R1; recommendation OVERRULED — constraints relaxed)*
**Decision:** Target **Raspberry Pi 5 (4 GB)**. Must run **acceptably on a Pi 3**;
**Pi 4 (4 GB) is the baseline**. The design must **not** require Pi 5 8 GB.
**Consequence:** The "require 8 GB" assumption is dropped. This is only feasible
because of D2 (LLM inference is off-box). The **binding on-Pi compute** is now
ffmpeg decode + loudness + **Piper TTS**, ×N stations — *not* LLM inference.
**New feasibility item for the RPi Expert (F1):** validate the Pi 3 expectation.
Pi 3 = 1 GB RAM / 4× A53 @1.2 GHz; 4 concurrent Piper + ffmpeg streams in 1 GB is
the open question. Recommend stating a realistic **stations-per-model guideline**
(e.g. "1–2 stations on Pi 3, 4 stations wants Pi 4 4 GB+") rather than a hard
single floor. Active cooling and SSD/USB boot remain **recommended** for 24/7 (SD
wear is still real on Pi 3/4), and a powered USB hub for the dongles still
applies. Add a "Deployment / Hardware" subsection to §4 with the model guideline,
not an 8 GB requirement.

### D2 — LLM providers *(was R2; premise CORRECTED)*
**Decision:** The "local" LLM means a **networked Ollama *server*** on the LAN —
**not** inference running on the Pi. **Support all three backends: Claude,
DeepSeek Platform, and Ollama.**
**Consequence:** The RPi Expert's local-LLM BLOCKER (RAM / ~2–5 tok/s on-Pi) is
**moot** — there is no on-Pi LLM. The failover chain is **all network providers**:
`Claude → DeepSeek → Ollama(server)`, ranked per §12. The on-Pi local floor is
only **Piper (voice)**; the ultimate DJ-brain fallback when *every* network
provider (including the Ollama server) is unreachable is **NullDJ / pre-rendered
patter** (§9.3 unchanged). Rewrite §9.3/§11/§12 to describe Ollama as a
**self-hosted network provider**, not an on-device floor. **DeepSeek is in v1**
(this overrides Rev 1 R22's "defer DeepSeek").

### D3 — Content root *(was R3; recommendation ACCEPTED)*
**Decision:** **Per-station libraries** (as drafted). Resolve §16a accordingly;
shared root remains a later option behind the same catalog interface. No change
from Rev 1's recommendation.

### D4 — Control API in v1 *(was R4; recommendation OVERRULED — API is IN v1)*
**Decision:** The **FastAPI REST control plane is in v1.**
**Consequence:**
- **§2 must be updated:** remove "control surface" from the v1 non-goals; keep
  only "a *polished web UI* / browser console" as the non-goal. §15 stays in v1.
- The Senior Dev's envelope concern (Rev 1 R12-API / R4) is now **active v1
  work**: §15 must ship with a **consistent response/error envelope, documented
  status codes (incl. 404 for unknown `{name}`), and bearer-token auth** bound to
  the homelab network.
- QA: the surface is testable with FastAPI `TestClient`; add API tests to the v1
  plan (assert the bearer-gated surface).
- **Roadmap (§20):** the API moves from "Phase 6 / later" into the v1 phase set.
  Recommend it lands **after** the MVP vertical slice (current Phase 1) so the
  core broadcast loop is proven first, but it is no longer post-v1.

---

## Amended resolution

### R8′ — Logging & the `GET /logs` endpoint *(amends Rev 1 R8 to fit D4)*
Rev 1 R8 removed `GET /logs` and routed logs to journald. With the API now in v1
(D4), the panel's underlying concern was never "no log access" — it was **"don't
hand-roll a flat-JSON log scanner with SD-wear and unbounded growth."** Reconciled
resolution:
- **State** (catalog/schedule/resume) stays **flat JSON** with atomic writes (R5).
- **Logs** are written to **journald/stdout** (rotation + retention handled by the
  platform; off-box shipping available); high-frequency transient writes go to
  `tmpfs`. SD-wear concern resolved.
- A **`GET /logs` endpoint may exist in v1**, but it must be backed by **journald
  query or a SQLite store (indexed)** — **never** a linear scan of an append-only
  JSON file. This satisfies both the client (queryable logs via the API) and the
  panel (no wear-heavy, unindexed, unbounded JSON log store).

---

## What carries over from Rev 1 unchanged (still adopted)

- **R5** atomic durable writes · **R6** corruption recovery / no crash-loop ·
  **R7** systemd two-tier supervision (still needed; D1 doesn't change this) ·
  **R9** tz-aware clock / DST · **R10** stable USB device naming via udev (still
  applies on every model and even on an x86 box) · **R11** never-dead-air canned
  backstop + defined `find_now` gap path · **R12** bound schedule drift ·
  **R13** subprocess-claim downgrade + DeepSeek model-name caveat ·
  **R14** `AudioBuffer` model · **R15** Protocol error taxonomy ·
  **R16/R17** discriminated unions + `schema_version` · **R18** injectable clock ·
  **R19** seedable scheduler · **R20** thin hardware seam + coverage-denominator
  fix · **R21** virtual-time pipeline/failover tests.
- **R22 (amended):** drop `pydub`; pick **one** loudness path (`pyloudnorm`);
  offline-tagging stays a Phase-5 standalone tool. **NOT dropped:** the LLM trio
  (Claude/DeepSeek/Ollama all in v1 per D2). **TTS:** Piper (primary) + espeak
  (fallback) in v1; **ElevenLabs** (cloud TTS) may still be deferred behind the
  Protocol unless the client wants it in v1 — *flagged as a minor open item.*
- **§G accept-as-is:** broadcast-time model, Protocol backends + phased roadmap,
  fail-fast Pydantic config + secrets-via-env (with `EnvironmentFile=`/SOPS boot
  delivery), reactive quota handling (+ spend-cap caveat), grounding-wording
  softening, and the **RF-legality acknowledgment** (deployer owns it).

---

## Updated concrete edits to the design doc (if Rev 2 adopted)

§4 new Deployment/Hardware with a **stations-per-Pi-model guideline** (D1/F1),
cooling/SSD/hub *recommended* not required; §9.3/§11/§12 reframe **Ollama as a
network provider** and keep Claude+DeepSeek+Ollama as the ranked LLM trio (D2);
§16a → per-station (D3); **§2** drop control-surface non-goal + **§15** stays in
v1 with envelope/status-codes/bearer-auth + **§20** API into the v1 phase set
(D4); §14/§15 logging reconciled per **R8′**; plus all carried-over Rev 1 edits
(R5–R7, R9–R22, §G).

---

## Vote — Round 2 (2026-06-07)

Per charter: **≤ 1 NAY → adopted**; **≥ 2 NAY → Rev 3.**

| Agent | Vote | One-line reason |
|---|---|---|
| Senior Dev | **AYE** | D4 promotes the REST envelope/status-code/bearer-auth to v1 work; R14–R17 carry over; no regression. |
| Old Man | **AYE** | Decisions faithfully reflected; the two overrules are the client's call and their complexity is tightly bounded. |
| Raspberry Pi Expert | **AYE** | D2 retracts the on-Pi LLM blocker; D1 relaxed to a guideline; provided the F1 stations-per-model numbers. |
| Fact Checker | **AYE** | No new unverified claims; on-Pi LLM figures correctly retired; F1 properly hedged as unvalidated recommendation. |
| Devil's Advocate | **AYE** | None of the five regressed; network-Ollama floor now honest; one eyes-open item → R23 (below). |
| QA Engineer | **AYE** | R18–R21 intact; v1 API + R8′ fully testable in-process via TestClient + dependency_overrides + in-memory SQLite. |
| Field Operator | **AYE** | D1/D2/D4 + R8′ preserve all resilience items; LAN-Ollama failure bounded by the R11 canned backstop. |

**Tally: 7 AYE / 0 NAY → ADOPTED (Round 2).**

### F1 — stations-per-Pi-model guideline (from the RPi Expert)
- **Pi 3 (1 GB):** 1 station realistically (2 only with a low-quality voice +
  staggered patter). RAM is the wall. → "demo / single-station" tier.
- **Pi 4 4 GB:** the **4-station baseline**, with medium-quality Piper voices,
  staggered patter (jitter the top-of-hour IDs), and active cooling for 24/7.
- **Pi 5 4 GB:** comfortable 4 stations with headroom — **recommended target.**
- *Caveat:* estimates pending a Phase-1 load test (measure Piper RTF + peak
  concurrent RSS per model on real hardware before treating as a guarantee).

### R23 — Non-blocking API/log handlers *(new, from Devil's Advocate; non-controversial, folded in)*
The FastAPI control plane (D4) runs in the **same asyncio event loop** that feeds
the audio device (§5.2). A sync path-operation, or any blocking call inside an
`async` handler (e.g. a synchronous `sqlite3` log query, or synchronous schedule
file I/O), **blocks the loop and starves the player → dead air**, which R11's
backstop cannot fully cover (a blocked loop can't run the backstop's own `await`
either). **Resolution:** add a stated rule to §15/§5.2 — **all API and log-query
handlers must be non-blocking; offload any synchronous I/O via `asyncio.to_thread`**
(consistent with §5.2's existing CPU-offload rule). Code-review-gate enforced.

---

## Post-adoption client clarifications (2026-06-07)

These resolve the three minor open items left after Rev 2. **No new vote was
called:** both substantive items fall inside already-ratified patterns (D5 is one
more backend behind the existing `TTSEngine` Protocol — the same basis on which
the panel accepted DeepSeek; D6 *reduces* scope). Recorded as binding and folded
into the design doc §21.1.

- **D5 — ElevenLabs is in v1 (core feature).** Supersedes Rev 2 R22's "ElevenLabs
  may be deferred." Ships as a ranked TTS provider alongside Piper (local floor) +
  espeak, behind the `TTSEngine` Protocol and the per-station `tts` list (§11/§12).
  No structural change; the failover/grounding/loudness paths already cover it.
- **D6 — Use system time, assumed correct.** Daemon uses the **system local
  timezone** and **trusts the OS clock**: drop the RTC-absence and NTP/clock-step
  defensive work implied by Rev 1/Rev 2 R9. Datetimes stay **tz-aware** so DST is
  handled by `zoneinfo`; the only residual policy is DST-fold behavior (R9).
- **F1 numbers** remain pre-load-test estimates (client: noted).

Affected agents (Field Operator: clock/timezone; Old Man/Senior Dev: ElevenLabs
no longer deferred) will absorb D5/D6 at their next briefing.
