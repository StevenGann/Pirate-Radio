# Devil's Advocate — Notes

> **Mandate:** For anything the other agents suggest, construct the strongest
> honest argument *against* it. I read this file before every engagement and
> append durable learnings (date-stamped) after.

## Method

- Steelman the opposition, never strawman. The goal is to surface real failure
  modes, not to obstruct.
- For each proposal ask: *How does this fail? Who pays for it later? What did we
  assume that might be false? What's the cheaper/simpler alternative we're
  skipping? What happens at the edges (power loss, bad input, wrong Pi model)?*
- Attack the **strongest** version of a proposal, not a convenient weak one.
- Distinguish a **principled NAY** (this is wrong/risky) from a **noted concern**
  (proceed, but eyes open). Only the former should drive my vote to NAY.
- If even I can't find a real objection, say so explicitly — that's a strong
  signal the proposal is sound.

## Recurring angles for this project

- "Do we even need this?" (ally of the Old Man, weaponized).
- "This works on the dev box / Pi 4 but not the target Pi Zero."
- "This is untestable, so the green CI is lying." (hand to QA Engineer).
- "This assumes the deployment environment we wish we had." (hand to Field
  Operator).
- "This factual premise is unverified." (hand to Fact Checker).

## Open questions

- Does §5.3's "depth 1–2 buffer" plus §9.3's "local floor" actually hold when a
  cold start lands on a `block_transition` (LLM+TTS, no track to mask latency)?
- What is the real LFS/JSON log volume at 4 stations × patter-per-track × weeks,
  and what does a `/logs` linear scan cost at that size?

## Notes log

- _2026-06-07_ — Panel established. Standing posture: every distilled doc gets at
  least one genuine counter-argument before I vote. A rubber-stamp AYE from me is
  a failure of my role.

- _2026-06-07_ — **Design Doc Round 1.** Strongest standing objections, ranked:

  1. **"Never dead air" (§2) vs. depth 1–2 buffer (§5.3) is not proven — it's
     asserted.** The buffer hides latency only when there is *prior audio of
     sufficient duration* playing while the producer refills. The doc never
     bounds producer wall-time vs. the duration of the item currently playing.
     Worst cases the design itself creates: (a) **cold start / post-crash
     resume** (§6) when `find_now` lands on or just before a `block_transition` —
     there is no buffered audio and the first segment is LLM+TTS, multi-second,
     possibly with full provider-chain failover (§9.3) running serially; (b) a
     run of short items (station_id → block_transition → short track) where each
     play-time is shorter than the next refill. A bounded queue does NOT bound
     refill *time*; it only bounds memory. The claim needs a stated worst-case
     refill budget and a pre-rendered silence/bumper floor, or it's marketing.

  2. **"Promote player to subprocess later without restructuring" (§5.4) is the
     load-bearing risk-acceptance, and it's optimistic.** Today the player shares
     the in-process `asyncio.Queue` of decoded NumPy `AudioBuffer`s, shared
     LLM/TTS clients, shared catalog, and in-process supervision. A subprocess
     boundary forces: serializing large PCM buffers across IPC (or moving the
     whole producer across too), a new crash/restart protocol, and re-homing the
     audio-device handle. That's a re-plumb of the §5.1 "shared everything"
     thesis, not a swap behind a Protocol. The segfault risk is also accepted
     for the *worst* possible failure: it takes down all 4 stations at once, and
     the in-process supervisor (§5.4/§14) cannot catch a SIGSEGV — only an
     external process can. So the one failure mode the supervisor is sold on
     ("let it crash, restart") is exactly the one it cannot handle.

  3. **Persisting known-wrong `planned_start` (§6) + fully-soft boundaries (§8.5)
     = unbounded same-direction drift within the hour.** TTS length is unknown
     until synthesized (§6 concedes this) yet `planned_start` is computed from
     estimates and persisted, and `find_now` (§6) trusts it for seek offset.
     Every patter item that runs long pushes the rest of the hour later, and
     soft boundaries never claw it back until the *next-day* regen. The "re-anchor
     at hourly IDs" fix is deferred to "later," so v1 ships with the drift it
     admits but does not bound. After a resume, `find_now` can seek to an offset
     that no longer exists in the actual (longer) segment → silence or a skipped
     item. Who pays: a listener tuning in for "Lunchtime Theater at noon" and the
     console (§15) showing a now-playing offset that's wrong.

  4. **Flat-JSON-for-everything incl. queryable logs (§14/§15) doesn't scale and
     the `/logs` endpoint (§15) makes it a feature.** 4 stations emitting patter
     events per track, every day, append to flat JSON with no rotation, index, or
     retention policy stated. `GET /logs?...&since=&limit=` is a linear scan +
     parse of an ever-growing file on Pi-class storage/CPU. Catalog and schedule
     as flat JSON are fine (bounded, rewritten daily); **logs are unbounded
     append** and are the one place "no DB" actually bites. SQLite (stdlib, no
     server, one file) would satisfy "kept simple" and give indexed log queries
     for free. The design conflates three storage problems under one "simple"
     banner.

  5. **Local LLM/TTS as the "always-available floor" (§9.3) assumes headroom the
     hardware doesn't have.** Piper on ARM is plausible; a local *LLM* (Ollama
     llama3.1, §12) as the *floor* for 4 stations is the doubtful part. When
     cloud providers fail (the exact moment the floor is needed), all 4 stations
     fall to local at once, contending for the same CPU/RAM the audio pipeline
     and ffmpeg decode already use. The "floor" can become the slowest provider
     precisely under load — converting objection #1's latency risk into dead air.
     Mitigation exists (NullDJ / pre-rendered generic intro, §9.3), but then the
     honest claim is "the floor is silence/canned patter," not "local LLM."

  Noted-concern tier (eyes open, not NAY): reactive-only quota handling (§14) —
  fine for a homelab, would bite if anyone runs it on a metered account; grounding
  prevents *fabrication of facts present in metadata* but cannot stop tone/emphasis
  hallucination or wrong inferences from sparse tags (§9.2/§9.3) — acceptable for
  a hobby DJ, name it honestly; single shared event loop (§5.2) means one
  mis-behaved `to_thread` pool or a blocking call stalls all stations, but that's
  a code-review concern, not an architecture NAY.

  Conceded sound: broadcast-time model (§6) is genuinely elegant and unifies cold
  start + resume; Protocol-based backends (§11) are clean; fail-fast Pydantic
  config + grid validation (§8.3/§12) is exactly right; secrets-via-env (§12) is
  correct; offline tagging tool kept out of runtime (§7) correctly respects the
  MusicBrainz 1 req/s limit.

- _2026-06-07_ — **Phase 0 Implementation Plan Round 1.** Code-level review; real
  bugs in the drafted code, not taste.

  1. **Empty-but-present env var passes the §12 fail-fast check.**
     `_check_env_vars_present` (~line 1069) uses `n not in os.environ`. An env var
     exported as `""` (the classic "secret didn't load from SOPS/EnvironmentFile")
     IS in `os.environ`, so config validates and the daemon boots with an empty
     API key — failure resurfaces on the first cloud call, defeating "fail at
     startup, not at 3 a.m." Fix: reject empty/whitespace, not just absent keys.

  2. **R10 device-distinctness is checked on config *strings*, not resolved
     physical identities — so the plan does not actually deliver R10.** Both
     `_check_distinct_audio_devices` and `_check_audio_devices_resolve` work on the
     raw `audio_device` string. R10 exists because identical USB dongles alias:
     two config names can resolve to one physical port, or one name can be unstable
     across reboots. `AudioDeviceResolver` only exposes `available_devices() ->
     frozenset[str]` (membership), so aliasing is undetectable. The seam enforces
     "name in set," NOT "each station → distinct stable physical port." Who pays:
     Station 2 transmits on Station 4's frequency — the exact failure R10 targets.
     Resolver must expose name→stable-port-id; distinctness checked on resolved id.

  3. **`time(0,0)`-as-24:00 lets a degenerate grid tile "validly."**
     `_validate_tiling` passes a two-slot `[00:00→00:00, 00:00→00:00]` grid (first
     ok, last ok, pairwise 00:00==00:00 ok) — meaningless, and Phase-1 `find_now`
     against it is undefined. Plan only tests the single all-day slot. Root cause:
     overloading `time(0,0)` for both day-start and day-end. The §9-Q3 sentinel
     (minutes-from-midnight 0–1440 / a `DayTime` type) removes the whole bug class.

  Noted concerns: `_replace_keep_bak` reads+rewrites the whole live file every save
  (read/write amplification at Phase-1 schedule sizes); fixtures are *untagged*
  WAVs so the rich tag path (`_first` spellings, `_parse_year`) is only covered by
  the *optional/hedged* committed-MP3 fixture — that hedge is where coverage-gaming
  hides (90% lines, zero asserted titles/years); make the tagged-fixture test
  mandatory with value assertions. `rglob` silently flattens `oldies/1960s/` into
  `oldies` with no log.

  Conceded strong: persistence `except BaseException: tmp.unlink` + crash-mid-write
  durability test (monkeypatch `os.replace`) is the right paranoia; `extra="forbid"`
  + discriminated unions correctly realizes R16; `safe_load`-only with `!!python`
  rejection test is textbook; injected `resolver`/`clock_weekday` keeps validation
  deterministic + hardware-free; dependency-sorted TDD order imports nothing
  unwritten; deferrals (R14/R15/R19) are reasoned, not lazy.
