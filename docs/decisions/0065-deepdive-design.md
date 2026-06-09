# 0065 — Deep-dive cycle 1 of 4: DESIGN review + reconciliation

The first of four sequential dimension-specific deep-dives (design → architecture → code quality →
documentation). A six-persona panel (Senior Dev, Old Man, Devil's Advocate, Field Operator, RPi
Expert, Fact Checker) reviewed the system **DESIGN** — `PiRate_Radio_Design_Doc.md`, the §21 Review
Resolutions, and the design decisions — judged against the shipped system (phases 0–6).

## Panel result: CONFIRM ×3, DISPUTE ×3 → remediated → re-poll

- **CONFIRM (round 1):** Old Man (design lean; control API / `/logs` over-scope are client-authorized
  and well-fenced; recommended cutting `/logs`), Field Operator (operability designed-in; gaps are
  doc-completeness + the undefined DST policy), RPi Expert (Pi assumptions sound for the pinned
  target; gaps are the missing §A appendix + thermal/power as stated principles).
- **DISPUTE (round 1):** Senior Dev, Devil's Advocate, Fact Checker.

**Root cause (convergent):** the *implementation* is correct — it followed the §21 resolutions and made
panel-ratified deviations — but the design **document** had drifted out of sync with both the shipped
system and several of its own binding §21 resolutions. The dissents were design-doc-accuracy failures,
not architecture defects.

## Remediation — `PiRate_Radio_Design_Doc.md` reconciled to as-built (doc-only)

**HIGH / CRITICAL:**
- **§6 drift over-claim** (Senior HIGH-1): removed "never compounds past an hour / hourly station-ID
  re-anchor"; §6 now states the real bound (player advances by actual length; `find_now` rebuilds
  from estimates; `anchor()` re-anchors once per day-slice; drift bounded by the next same-day
  regeneration; a mid-day resume seek is approximate to accumulated estimate error).
- **§8.6 midnight splice** (DA CRITICAL): corrected to state the cross-day splice is NOT seamless —
  schedule prewarm only; the boundary is backstop-covered (audible-as-bumper), carved out of R11's
  warm-buffer guarantee.
- **§21/R8′** (Fact-Checker HIGH): amended to the ratified in-memory ring deviation (was
  journald/SQLite-or-nothing).
- **Item-level poison policy** (DA HIGH): added to §9.3/§14 — any render exception is backstopped
  in-band and the item advances; covers a missing/corrupt content file at render time.
- **DST-fold + time-sync** (Field-Op HIGH, DA HIGH): §6 "Clock assumptions & DST policy" added —
  startup gated on `time-sync.target`; fall-back hour not re-aired, spring gap skipped.
- **§4.1 Deployment/Hardware** (Field-Op HIGH, RPi MEDIUM): added the D1 stations-per-Pi-model table +
  24/7 requirements (active cooling, SSD boot, PSU, powered hub) + the RF-legality acknowledgment.
- **Appendix A — look-ahead RAM budget** (RPi HIGH): added (was referenced as governing but absent).
- **§17 thermal risk row** (RPi HIGH): added (sustained load → throttle → backstop; mitigation =
  cooling + stagger).

**MEDIUM:** removed the stale `bumper` ItemKind (§13/§3); removed the deleted
`max_requests_per_minute` from §12/§13; applied the R13 subprocess downgrade to §5.4/§17; corrected
§15 `/skip` to skip-at-next-boundary; updated §11 Protocol signatures + R15 contract; rewrote §13 to
the shipped typed/discriminated-union shapes; softened "invents no facts" (§9.2/§9.3); added a §19
"actual tree is src/pirate_radio/" pointer; added the §7 runtime catalog/schedule coherence note.

## Carry-forward (non-blocking)

- **Storage-exhaustion free-space precondition** (DA MEDIUM): no startup/pre-regen free-space check;
  disk-full is mitigated operationally (journal vacuum, `df`) per the first-boot runbook. A code-level
  precondition check is a small feature for a later pass.
- Old Man's standing recommendation to **cut `GET /logs`** (journald already serves it): not adopted —
  the bounded RAM ring was ratified 7/7 in P6-6 (0062) as a documented R8′ deviation with a real
  use (quick "what is this process doing now" over the tunnel); left as shipped, now accurately
  described in the design.

## Outcome

The design DOCUMENT now accurately describes the as-built system and honors every §21 resolution. The
underlying design was found sound by all six reviewers (the core broadcast-time / look-ahead / Protocol
thesis required no rework); the dissents were doc-accuracy issues, now closed. No code changed this
cycle (gate unchanged: 872 tests, 97.49%).
