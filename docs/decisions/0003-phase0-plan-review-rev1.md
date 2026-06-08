# Distilled Review — Phase 0 Implementation Plan — **Rev 1**

> **Status:** For panel vote.
> **Source:** Round 1 reviews from all seven agents on
> `docs/plans/phase-0-implementation-plan.md`.
> **Manager's note:** The Fact Checker verified all code-level API claims (Pydantic
> v2 discriminated unions, mutagen, `os.replace` + parent-dir `fsync` durability,
> `yaml.safe_load`, `zoneinfo`/D6) with **no refutations** — no factual blocker.
> The plan's architecture was called "genuinely strong" by the Devil's Advocate.
> Findings below are amendments, not a redesign. Vote is on this whole document.

---

## A. Open-question resolutions

### Q1 — `Catalog`: frozen value object (no separate cache/service)
**Decision (5–2 lean + synthesis):** `Catalog` is a **frozen value object**. Its
internal representation is the **`group → tuple[Track]` mapping the scanner already
produces**, so `groups()` and per-group access are **dict lookups, not per-call
recomputation** — this removes the Senior Dev/RPi "recompute smell" *without*
building the speculative cached *service* the YAGNI camp (Old Man, QA, Field Op, DA)
warned against. **No mtime-invalidation logic in Phase 0**; mtime-cached rescan is
deferred to Phase 1 (RPi), where the access pattern is known.

### Q2 — Validate **all** present grids at boot (5–1)
**Decision:** At config load, **structurally validate every present grid file**
(tiling, `start<end`, `name`, YAML safety) — **fatal** for all. For the **group →
content-folder** cross-check: **fatal for today's grid**, **warn (not fail) for
other days'** grids that reference a group absent from the *current* catalog (the
"future catalog" wrinkle raised by Old Man / Fact Checker / DA). Ship
`validate_all_grids` wired into the boot path. Rationale: catching a broken
`saturday.yaml` on Tuesday is exactly the unattended-failure-avoidance §8.3/§12
fail-fast exists for; the parse cost is trivial vs the catalog scan.

### Q3 — Keep `time(0,0)`-as-24:00 for Phase 0, but fence the bug class
**Decision:** Retain `time(0,0)` as end-of-day for Phase 0 (Fact Checker confirms
`datetime.time` has no 24:00; the workaround is standard), **but add explicit
validation rules** that kill the degenerate cases the DA found:
- `end == 00:00` is legal **only on the final slot**; a **non-final slot ending at
  00:00 is rejected**.
- **Zero-length slots** (`start == end`, end ≠ 00:00) are rejected.
- The **multi-slot midnight collision** `[00:00→00:00, 00:00→00:00]` is rejected.
- Companion RED tests for each, alongside the existing single-all-day-slot
  acceptance test.

This satisfies the DA's stated alternative ("if keeping `time(0,0)`, add an explicit
rule + test that `end==00:00` is legal only on the final slot"). **Flag** a
minutes-from-midnight / `DayTime` type as a **Phase-1 revisit** if `find_now`
time-binding proves awkward — not worth the `Slot`/validation churn now.

---

## B. Must-fix amendments (before GREEN)

### A1 — Reject empty/blank `*_env` secrets *(Field Operator MAJOR + DA OBJECTION)*
`_check_env_vars_present` uses `n not in os.environ`, so a present-but-empty
`ANTHROPIC_API_KEY=""` (a failed `EnvironmentFile=`/SOPS decrypt) "validates" then
dies on the first cloud call. **Fix:** reject empty/whitespace-only values
(`not os.environ.get(n, "").strip()`); add `test_empty_env_var_rejected` and
`test_whitespace_env_var_rejected`.

### A2 — Make R10 honest: resolve to physical identity, not strings *(DA OBJECTION + RPi MAJOR)*
This is the deepest finding. The resolver exposes `available_devices() ->
frozenset[str]` (set membership), and distinctness/resolution are checked on raw
config **strings** — which **cannot** detect the literal R10 failure (two config
names aliasing the **same physical port**, or one name unstable across reboots).
**Fix:**
- Change the Protocol to `resolve(name) -> PortId` (name → **stable physical id**);
  check **distinctness on the resolved id**, not the string.
- Add a test where **two different config names resolve to the same port** and
  validation **rejects** it.
- **Document the contract:** *stable name = the udev-assigned ALSA card id keyed on
  the physical USB port path* (not USB serial — cheap CM108/CM109 dongles share/omit
  serials); the real resolver bridges **PortAudio name → `hw:CARD=`**. Real
  `UdevAudioDeviceResolver` stays Phase 4 behind `@pytest.mark.hardware`;
  `StaticAudioDeviceResolver` now maps names→PortIds so the Phase-0 test is
  meaningful, not tautological.

### A3 — Close the `tts_providers` R16 hole *(Senior Dev MAJOR; Old Man, QA, FC, DA)*
`tts_providers: dict[str, dict]` is a bare dict in `DaemonConfig`; `extra="forbid"`
does **not** recurse into dict values, so a typo'd credential key (`endpiont`)
passes silently — the exact failure R16 forbids. **Fix (preferred):** add a
`model_validator` that checks each entry against the **known per-backend key sets**;
**or** keep it permissive *only if* explicitly named as Phase-2 debt **with a test
asserting the limitation** (so the gap is visible in the suite, not just prose).
**Resolution: validate now via `model_validator`** (cheap, no Phase-2 reader needed
to justify catching typos at boot).

### A4 — One clock site *(Old Man, Senior Dev, QA, Field Op)*
`load_config` calls `datetime.now().weekday()` when `clock_weekday is None`, a second
`datetime.now()` outside `clock.py`, contradicting the plan's own §5 rule. **Fix:**
`load_config` takes a `Clock` and resolves the weekday from it; `clock.py` becomes
literally the only `datetime.now()` site.

### A5 — Test-quality fixes *(QA 3×MAJOR + DA)*
- **(a) Real crash-injection test** for `persistence.py` (currently prose only):
  monkeypatch `os.replace` **and** `os.fsync` to raise mid-write; assert a
  recoverable state never yields `StateCorruptionError`, `.bak` still validates, **no
  `.tmp` leftover**; test the `_replace_keep_bak` failure path independently.
- **(b) `caplog` assertions** on every skip-and-log path (scanner unreadable/corrupt
  files): prove a WARNING naming the path was emitted — no silent swallow may be
  coverage-invisible.
- **(c) De-tautologize `test_deterministic_ordering`:** assert the actual sorted
  `(group, path)` order, plus a case where files are created in non-sorted order and
  still come out sorted (Phase-1 R19 seeded generation depends on this).
- **(d) Mandatory tagged-metadata fixture:** drop the "if awkward…" hedge; ship a
  real tagged file and **assert extracted title/artist/year** (DA: coverage-gaming
  hides in that hedge — you can hit 90% on `metadata.py` asserting nothing real).

---

## C. Adopt as documentation / forward notes

- **A6 — State-directory convention *(Field Op MAJOR)*.** Add a `state_dir` config
  field (or documented default) placing mutable state **off the boot SD**; validate
  it **exists and is writable** at load (not just `is_dir`); apply the writability
  check to `content_dir`/`schedule_dir`/`state_dir`; log the resolved device once so
  an operator can see where writes land.
- **A7 — Persistence docstring caveats.** State the required filesystem
  (**ext4/f2fs**; not vfat/overlay-on-SD for the state dir); note dir-`fsync` may
  silently no-op on some filesystems; add a **"not for hot paths"** rule (Phase-1
  per-item resume state must batch/debounce or use tmpfs); document the
  single-generation `.bak` window; note read-whole-file is fine for small state.
- **A8 — D6 / time.** Document that the Phase-1 systemd unit must order
  `After=time-sync.target` (headless Pis have **no RTC**; wrong clock at boot until
  NTP → wrong day's grid); adopt the **`PIRATE_RADIO_TZ`** override (open Q5) for
  deterministic deployments; note Bookworm's system tzdata means **no pip `tzdata`
  dep** is needed.
- **A9 — Catalog forward notes.** Eager full scan is acceptable for Phase 0 but SD
  random-read latency on Pi 3/4 → Phase-1 mtime-cached rescan; `rglob` collapses
  nested subfolders (`oldies/1960s/`) into the top-level group (matches spec) —
  document/log it so the flattening isn't silent.
- **A10 — Minors.** `Track.year` tighten to `ge=1000` (or document the loose bound
  intentionally) so schema and producer agree; document grid `name` stem-fallback as
  a decision; `FixedClock` use `cast`/guard not `assert` (`-O` safety); note the
  `StateCorruptionError` → regenerate consumer lands in Phase 1, so "never
  crash-loop" is only fully real once Phase 1 wires it.

---

## D. Accepted as-is (strengths recorded)

- Persistence **copy-then-replace `.bak` ordering** + `except BaseException:
  tmp.unlink()` cleanup — the safer option, correctly argued; keep the crash test as
  the guard.
- **Discriminated unions + `extra="forbid"`** — correct, complete R16 (a typo'd
  `simillarity_boost` fails at load).
- **`yaml.safe_load`-only** + explicit `!!python/object` rejection test — textbook
  boundary validation.
- Injected `resolver` + clock keep config validation deterministic/hardware-free;
  `FixedClock` rejecting naive datetimes prevents naive-time leakage.
- **Dependency-sorted TDD order** imports nothing unwritten; deferrals (R14/R15/R19/
  R7/R8′/R11/R12/D4) are reasoned with re-attach points.
- Deps minimal and ARM-clean: `pydantic`, `mutagen`, `PyYAML` (+`types-PyYAML`), no
  audio/RF/SDK; all code-level API usage **verified by the Fact Checker**.

---

## E. Concrete plan edits (if Rev 1 adopted)

Append a governing **"Review Amendments (Rev 1 — adopted)"** section to
`phase-0-implementation-plan.md`; update the affected module specs + test lists for
A1–A5 and Q1–Q3; add `state_dir` + filesystem caveats (A6–A7); fold in the forward
notes (A8–A10). PR breakdown grows by the new tests but no new module is added (A2
changes the resolver Protocol signature within the existing `audio_devices.py`).

---

## Vote — Round 1 (2026-06-07)

Per charter: **≤ 1 NAY → adopted**; **≥ 2 NAY → Rev 2.**

| Agent | Vote | One-line reason |
|---|---|---|
| Senior Dev | **AYE** | A3/A4/A1/Q1 resolved exactly as argued; A10 minors intact; A5 closes the test-quality gaps. |
| Old Man | **AYE** | Q1 = value object (no speculative cache); future-catalog concern adopted on Q2; amendments are correctness/test-honesty, zero gold-plating. |
| Raspberry Pi Expert | **AYE** | A2 fully resolves the R10 MAJOR (resolve→physical PortId, port-path keying, PortAudio→hw:CARD bridge); A6–A9 capture the forward notes. |
| Fact Checker | **AYE** | Rev 1 records the zero-refutation result and adds no unverified claims; the A2 CM108/udev + A7/A8 OS facts all check out. |
| Devil's Advocate | **AYE** | All three objections are genuine committed fixes with tests (A1, A2 PortId, Q3 fences); noted concerns (A5d, A9) in; nothing regressed. |
| QA Engineer | **AYE** | Three test MAJORs adopted verbatim (A5a–c) + mandatory tagged fixture (A5d) + Q3 rejection tests + one-clock-site; bar met and exceeded. |
| Field Operator | **AYE** | Three MAJORs (A1, A6, A7) adopted as written + A8 boot-clock + A10; A2/A4 further harden field operation. |

**Tally: 7 AYE / 0 NAY → ADOPTED (Round 1).**

Manager applies the amendments to `phase-0-implementation-plan.md` as a governing
"Review Amendments (Rev 1 — adopted)" section.
