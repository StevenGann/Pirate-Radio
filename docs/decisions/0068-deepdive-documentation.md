# 0068 — Deep-dive cycle 4 of 4: DOCUMENTATION review + remediation

The final dimension-specific deep-dive. A five-reviewer panel — Fact Checker, Field Operator, Senior
Dev, Old Man (personas) + the specialized **doc-updater** — reviewed documentation accuracy,
completeness, navigability, and code-doc honesty. Crucially, cycles 2–3 had changed code *after* the
cycle-1 design-doc reconciliation, so this pass hunted for fresh drift.

## Panel result: CONFIRM ×3, DISPUTE ×2 → remediated

- **CONFIRM:** Senior Dev (one HIGH: the generator header lied), Old Man (lean in shape, leaky in
  detail — root-caused the debt as hand-copied volatile facts), doc-updater (operator docs excellent;
  flagged the missing developer CODEMAP).
- **DISPUTE:** Fact Checker (README freshness cluster), Field Operator (a `state_dir` CRITICAL).

## Remediation (doc + comment only — no behavior change)

**CRITICAL (Field-Op) — `state_dir` contradiction reconciled.** `config.example.json` set
`state_dir` to `/mnt/ssd/...` while `first-boot.md`/`config-reference.md` insisted it MUST equal the
unit's `StateDirectory` (`/var/lib/pirate-radio`), and the off-SD goal was asserted but never
reconciled. **Chosen model:** keep `StateDirectory=pirate-radio` (systemd auto-creates
`/var/lib/pirate-radio` 0700); set the example `state_dir` to `/var/lib/pirate-radio`; off-SD is
achieved by the §0 SSD/USB-boot recommendation (or, if booting from SD, fstab-mounting `/var/lib` on
the SSD). All four artifacts (unit, example, first-boot, config-reference) now agree.

**HIGH — README freshness (Fact-Checker / Old Man / doc-updater):**
- Removed the `max_requests_per_minute` reference (the field was deleted in 0064; config is fail-fast
  on unknown keys, so documenting it would break a deploy).
- Rewrote the stale "Phase-4 entrypoint / logging not yet shipped" paragraph (logging ships via
  `configure_logging` + `--log-level` → journald).
- **De-pinned the volatile facts** (the durable fix Old Man pressed for): the README no longer
  hand-copies an exact test count or a decision-range endpoint — it points at "run `pytest`" + the
  80% floor, and at the `docs/decisions/` directory.

**HIGH — code-comment / design lies (Senior Dev / Fact-Checker):**
- `generator.py` module header said "near each top-of-hour" — the pre-cycle-3 bug behavior; corrected
  to "at the first item of each new clock-hour" (matching the truthful inline comment + the code).
- Design doc §8.4 step 4 + §3 glossary corrected to the same; `lookahead.py` "top-of-hour" phrasing →
  "clock-hour/block boundary".

**MEDIUM — design doc + structure:**
- Deleted the stale `ItemKind` alias from §13 (removed in 0040); fixed the §A constant name
  (`LOOKAHEAD_RAM_BUDGET_BYTES`, public); updated §15 closing prose (loopback default + bearer auth
  shipped); sub-numbered the §8.4 list so the code's `§8.4.N` cross-refs resolve; replaced the stale
  §19 module tree with a pointer to the new CODEMAP.
- **Added `docs/CODEMAP.md`** (doc-updater HIGH): a concise developer area-map of the 64-file tree
  (subsystem → key modules → entry points → seams) — the missing "start reading here" for a new dev.
- **Froze `docs/BUILD-LOG.md`** (Old Man / doc-updater): added a "historical build journal — NOT
  maintained, see README + docs/decisions/" header and deleted the orphaned contradictory trailing
  section (it cited 195/101 tests). It is no longer a third hand-maintained copy of status.

**LOW:** documented `--log-level` in first-boot; added a README "Documentation" index + "Related"
cross-link footers to the ops runbooks; noted the mid-hour-slot-boundary second-station-ID edge in
grids.md (0067 carry-forward).

## Outcome

The operator documentation was found strong by all reviewers; the dissents were doc-freshness drift
(concentrated in README, the design-doc prose, and one code comment) plus a real `state_dir` example
contradiction — all now reconciled to the current code, with the volatile facts de-pinned so they
can't silently re-rot. Gate unchanged (doc/comment only): **881 tests**, 97.63% coverage,
ruff/ruff-format/mypy `--strict` clean (64 source files).
