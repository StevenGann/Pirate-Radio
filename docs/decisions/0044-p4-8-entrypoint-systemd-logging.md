# P4-8 — `__main__.py` + `logging_setup.py` + `systemd/pirate-radio.service` + first-boot runbook

Strict spec-driven TDD (tests from plan §H → RED → GREEN → gate); the R7 tier-1 (systemd) + the
operator-facing entrypoint/logging layer (CF6, Field-Op).

## Implementation

- **`logging_setup.configure_logging(level)`** (R8′): one stdout handler, journald-friendly
  `levelname name: message` format, level from a name or int, **idempotent** (re-call replaces the
  marked handler, never stacks — a restart can't double every line).
- **`__main__.py`** (`python -m pirate_radio`, Q10): `main(argv, *, deps: MainDeps)` is the testable
  seam — every side-effecting collaborator (configure_logging, load_config, resolver, clock,
  `coordinator_factory`, the event-loop `run`) is injected, so the control flow is unit-tested with
  fakes (no real resolver, no `asyncio.run`, no filesystem). Logging is configured **first** (a config
  error logs through the operator stream). `--regenerate [station]` is a **oneshot**:
  `coordinator.regenerate_now(name|None)` then exit — the running daemon is unaffected. `_prod_deps`
  (real `UdevAudioDeviceResolver` / `SystemClock` / `RealSleeper` / `SoundDeviceSink` sink_factory /
  `asyncio.run`) is the only hardware-adjacent path (`pragma: no cover`).
- **`Coordinator.regenerate_now(only)`** + **`Station.prepare_next_day(force=…)`** /
  `_load_or_generate(day, force=…)`: `--regenerate` FORCE-overwrites today's file (an operator
  regenerating after a grid edit wants the new grid, not the cached schedule). Daemon Events untouched.
- **Operator log vocabulary (§H):** the Station now logs `station <name> starting` / `station <name>
  on air (schedule <date>)` at its status transitions (station-tagged). The rest of the vocabulary is
  already emitted + asserted by the live components: supervisor (restart/backoff/escalate/crash,
  test_supervisor), midnight (regen done|FAILED, test_midnight), producer (backstop fired,
  test_producer), coordinator (`N/N ON AIR`, regenerated, test_coordinator).
- **`systemd/pirate-radio.service`:** `Type=simple`, `Restart=on-failure`, `RestartSec=2`,
  `StartLimitIntervalSec=60`/`StartLimitBurst=5` (C2 — terminal `failed`, not an infinite thrash),
  `After=network-online.target time-sync.target` + `Wants=network-online.target` (H22 LAN + H24 clock
  before the wall-clock schedule), `EnvironmentFile=/etc/pirate-radio/secrets.env` (H22 — secrets root
  0600, never in the unit/config), **NO `WatchdogSec`** (a watchdog without a real `sd_notify`
  heartbeat is a footgun; documented optional upgrade). `User=pirate`, `StateDirectory=` (A6).
- **`docs/ops/first-boot.md`:** the ordered runbook — appliance hardware (cooling/SSD/PSU/powered hub),
  `apt install libportaudio2 ffmpeg espeak-ng` (the libportaudio2 hard prereq), venv deploy, service
  user, secrets 0600, per-dongle udev verify + reboot, config + `--regenerate` dry-run, enable, and
  confirming `N/N ON AIR` in journald; plus day-to-day regen/logs/schedules.

## Deviation (for P4-9 ratification)

The prod **sink_factory** builds `SoundDeviceSink(device=str(port_id))`; the exact PortAudio
device-string ↔ PortId binding is a hardware-deployment detail verified by the udev recipe +
`@pytest.mark.hardware` smoke, not on CI. The whole `_prod_deps` path is `pragma: no cover`.

## Tests

`tests/test_logging_setup.py` (4): level from name/int, idempotent (one handler), name+message in the
format. `tests/test_main.py` (5): logging-before-config order, log-level passthrough, normal-run starts
the daemon (no regen), `--regenerate` oneshot (regen, no daemon), `--regenerate NAME` passes the name.
`tests/test_systemd_unit.py` (6): Type=simple/Restart/RestartSec, StartLimit*, After network+time-sync,
EnvironmentFile (no inline secret), **no WatchdogSec**. `tests/test_station.py` (+1): operator starting
/on-air vocabulary (caplog).

## Gate

ruff + ruff-format + mypy `--strict` clean (48 source files); **708 tests** (+16), 97.65% coverage.

## Next

P4-9: housekeeping (fall-through WARNING de-dup) + the full-seven Phase-4 deep-dive (must ratify the
in-band render-poison, the lookahead/coordinator module split, and the deferred audio-buffer prewarm).
