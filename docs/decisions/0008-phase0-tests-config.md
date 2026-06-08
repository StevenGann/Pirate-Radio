# Phase 0 — Increment 5: `audio_devices.py` + `config.py` (tests-first) — Phase 0 complete

> config.json modelling + §12 fail-fast validation, and the R10 resolver seam.
> The densest validation surface; finishes Phase 0.

## Process record

1. **Tests authored** from plan §4.8/§4.9 / §6.7 + amendments A1/A3/A4. RED.
2. **Panel reviewed (Round 1) — 4 AYE / 3 NAY → Rev 2.** QA, RPi, and the Devil's
   Advocate independently caught that I had **regressed adopted amendment A2**: the
   tests used the pre-A2 string-set resolver (`frozenset[str]`) and omitted the
   mandated "two distinct names → same physical port → reject" test. (Old Man,
   Field Op, Senior Dev, Fact Checker AYE'd, with Senior Dev/FC flagging A2 too.)
3. **Rev 2** — restored A2: `StaticAudioDeviceResolver` takes a name→PortId
   mapping; config checks distinctness on the resolved PortId; added
   `test_distinct_names_resolving_to_same_port_rejected` + a positive distinct-port
   case + a new `tests/audio_devices/` seam suite (`resolve(name)->PortId|None`,
   aliasing expressible, Protocol conformance). Plus hardening: absent/malformed
   config.json, empty-stations, persona-file-present, and config models added to the
   shared all-models-frozen test.
4. **Re-vote (Round 2) — 7 AYE / 0 NAY → adopted.**
5. **Implemented to GREEN.** `audio_devices.py` (PortId NewType + Protocol +
   StaticAudioDeviceResolver), `config.py` (discriminated-union TTS/LLM, A4 Clock
   seam, A1 empty/blank-env rejection, A2 PortId distinctness, A3 tts_providers
   backend-key validator). **PR10:** retired the `hello()` placeholder; smoke test
   imports real modules.

## Result

`ruff` clean · `mypy` clean (12 files) · **133 passed** · coverage **98.51%**.
New deps this increment: none (PyYAML already added at grid).

## Phase 0 — COMPLETE

errors, clock, persistence, catalog (models/metadata/scanner), schedule/grid,
audio_devices, config — all tests-first, panel-reviewed, GREEN. The process caught
three real defects in the *tests* before implementation: a non-durable persistence
impl (missing dir-fsync), an untested §8.3 time-parse rule, and the A2 R10 regression.

**Next:** Phase 1 (MVP vertical slice) — needs an implementation plan first
(planner + panel), then testable core: schedule generator (seedable, R19), find_now
/resume, producer/consumer look-ahead pipeline (fakes + virtual time), AudioSink
Protocol + FakeAudioSink. SoundDeviceSink = `@pytest.mark.hardware` (deferred).
