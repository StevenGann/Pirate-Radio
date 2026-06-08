# 0034 — Phase 4 plan (multi-station) — Rev 2 ADOPTED (6 AYE / 1 NAY) + amendments

The seven-agent panel re-voted on Phase-4 plan Rev 2 (which folded the entire `0033` Rev-1 brief).
**Tally: 6 AYE (Senior Dev, Old Man, RPi Expert, Fact Checker, QA, Field Operator) / 1 NAY
(Devil's Advocate) → ADOPTS** under the ≤1-NAY charter. Fact Checker re-verified every NEW Rev-2
claim against code + reality (`sounddevice` wheel ships no PortAudio; generator patter constants
5/8/10 s; `run_once` `maxsize`; `DEFAULT_SAMPLE_RATE`=48000 float32; systemd targets/`StartLimit*`)
— no corrections.

## The DA's NAY was substantive and convergent — folded as Rev-2 amendments

All six other voters confirmed their Rev-1 conditions RESOLVED. The DA found three real refinements,
each **convergent with an AYE voter's condition**, so rather than ship-and-defer they were folded
into the adopted plan before implementation:

1. **C2 advance-past-poison was keyed on the wrong quantity (DA, correctness).** The Rev-2 wording
   keyed the "K identical-offset crashes" detector on the clock-derived `find_now` resume offset —
   which advances in wall-clock on every restart, so it would **never trip**. Fix: the producer
   **tags the propagated exception with the crashing schedule-item INDEX** (`PoisonItemError(index,
   cause)` / `last_attempted_index`); advance-past-poison keys on the **item index**. Test: same
   poison item across restarts with advancing wall-clock still trips the skip after K. (§C, P4-3.)
2. **RAM clamp silently re-opened C1 (DA + Senior + Old Man).** `_ram_bounded_depth` clamping depth
   *below* `worst_consecutive_patter + 1` means the buffer can't pre-render the cluster → C1 regresses
   behind a mere WARNING (the "confession not a fix" `0033` rejected). Fix: it is now a **FAIL-FAST
   boot `ConfigError`** (0033 option a), against a **FIXED byte budget** (`_LOOKAHEAD_RAM_BUDGET_BYTES`
   sized for 4 GB/4 stations — not a `psutil`-free fraction, which Old Man/RPi flagged as
   unreproducible-per-boot and an extra dep). (§A, P4-6.)
3. **C1 residual recurs every midnight, not just cold start (DA).** The generator opens every day with
   `block_transition`→`station_id` (patter-only, no masking track), so each midnight cold-started a
   cluster-sized backstop loop. Fix: **day-roll prewarm** — the coordinator renders the new day's
   opening cluster DURING the outgoing day's final item, so the splice finds a warm buffer. The ONLY
   irreducible residual is true daemon cold start (one opening-cluster render → R11 backstop + WARNING).
   `StationStatus.state` distinguishes `on_air` from `airing_backstop` (Field-Op). (§A, §E, P4-6.)

Tunable constants set per Old Man/RPi: fixed RAM budget ≈40% of *total* 4 GB (no `psutil`);
`stagger_step ≈ 2 s × station_index`.

## Confirmed-resolved Rev-1 conditions (the six AYEs)

- **Senior:** `recent_tracks` real-churn framing; `item_kind` as its own increment (P4-5b, 8 sites);
  Q1 decode+slice-then-`run_once`; "single fixed global format" wording. + the C1 depth fix is sound.
- **Old Man:** Q8 ceiling→exit no per-cause; Q6 minimal `StationStatus` no DTO/HTTP; Q5 pure fn +
  named constants; Q2 file-then-event; R6 through the restart path. (+ fixed-budget amendment above.)
- **RPi:** `libportaudio2` apt prereq; `WatchdogSec` dropped (Type=simple + Restart=on-failure);
  `After=network-online+time-sync` + boot-device/LAN tolerance; udev **port-path** keying + PortAudio↔
  ALSA bridge tested; RAM-aware + staggered budget; persistent stream + blocksize/latency + xrun-glitch
  + dedicated sink executor + lifecycle close.
- **Fact Checker:** every new claim verified, no corrections.
- **QA:** in-flight-aired-in-full positive assertion; gap-silence sample-count; R21 no-module-scope
  import guard; injected escalation seam; recent_tracks semantics pinned; §A budget fns all pure/testable.
- **Field Operator:** `WatchdogSec` footgun gone; `StationStatus` + periodic "N/N ON AIR" summary;
  operator log vocabulary (asserted gates); first-boot runbook + udev verify; `--regenerate` semantics;
  systemd `StartLimit*` + `time-sync.target`.

## Gate

Plan adopted; no code yet. Implementation: P4-1 (`SoundDeviceSink`) → P4-2 (udev resolver) →
P4-3 (supervisor + status) → P4-4 (daily slice) → P4-5 (station) → P4-5b (`item_kind` removal) →
P4-6 (coordinator + budget) → P4-7 (midnight) → P4-8 (systemd + entrypoint) → P4-9 (housekeeping +
deep-dive), each strict spec-driven TDD with a focused-panel TEST review.

## Next

Begin P4-1 (`audio/sink.py` `SoundDeviceSink`) tests-first.
