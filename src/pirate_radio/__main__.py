"""``python -m pirate_radio`` — the daemon entrypoint (Phase-4 §H / Q10).

``main(argv, *, deps)`` is the testable seam: every side-effecting collaborator (logging setup,
config load, the resolver/clock, the coordinator factory, the event-loop runner) is injected via
``MainDeps`` so the control flow is unit-tested with fakes — no real udev resolver, no
``asyncio.run``, no filesystem. Logging is configured **first** so a config error is itself logged
through the operator stream. ``--regenerate`` is a **oneshot** (regenerate, then exit).

Only ``_prod_deps`` (the real resolver / sink / ``asyncio.run``) is hardware-adjacent (``pragma: no
cover``); it is wired at ``__main__`` and validated on real hardware (the first-boot runbook).
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pirate_radio.audio_devices import AudioDeviceResolver
from pirate_radio.clock import Clock
from pirate_radio.config import DaemonConfig
from pirate_radio.coordinator import Coordinator

_NO_REGEN = (
    object()
)  # sentinel: distinguishes "--regenerate absent" from "--regenerate with no value"


@dataclass(frozen=True)
class MainDeps:
    """Injected collaborators for ``main`` (prod wires the real ones; tests wire fakes)."""

    configure_logging: Callable[[str], None]
    load_config: Callable[..., DaemonConfig]
    resolver: AudioDeviceResolver
    clock: Clock
    coordinator_factory: Callable[[DaemonConfig], Coordinator]
    run: Callable[[Coroutine[Any, Any, None]], None]
    preflight: bool = True


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="pirate_radio", description="PiRate Radio daemon")
    parser.add_argument("--config", required=True, help="path to config.json")
    parser.add_argument("--log-level", default="INFO", help="root log level (default: INFO)")
    parser.add_argument(
        "--regenerate",
        nargs="?",
        const="",  # bare --regenerate -> all stations; --regenerate NAME -> just that station
        default=_NO_REGEN,
        help="force-regenerate today's schedule(s) and exit (oneshot); optional station name",
    )
    return parser.parse_args(argv)


def main(argv: list[str], *, deps: MainDeps) -> int:
    args = _parse_args(argv)
    deps.configure_logging(
        args.log_level
    )  # FIRST: a config error is logged through the operator stream
    config = deps.load_config(
        Path(args.config), resolver=deps.resolver, clock=deps.clock, preflight=deps.preflight
    )
    coordinator = deps.coordinator_factory(config)
    if args.regenerate is not _NO_REGEN:
        coordinator.regenerate_now(args.regenerate or None)  # "" -> all; NAME -> that one
        return 0
    deps.run(coordinator.run())
    return 0


def _prod_deps() -> MainDeps:  # pragma: no cover - the hardware/asyncio-run wiring (R20/R21)
    from pirate_radio.audio.buffer import DEFAULT_SAMPLE_RATE
    from pirate_radio.audio.sink import SoundDeviceSink
    from pirate_radio.audio_devices import PortId, UdevAudioDeviceResolver
    from pirate_radio.clock import SystemClock
    from pirate_radio.config import load_config
    from pirate_radio.errors import ConfigError
    from pirate_radio.logging_setup import configure_logging
    from pirate_radio.pipeline.timing import RealSleeper

    resolver = UdevAudioDeviceResolver()
    clock = SystemClock()

    def sink_factory(port_id: PortId) -> SoundDeviceSink:
        # Translate the stable PortId (port path, R10 identity) to the PortAudio device INDEX — the
        # sink opens by index, NOT by the sysfs path. None here means the dongle vanished between
        # config validation and sink construction -> fail loud rather than open the wrong device.
        index = resolver.device_index_for_port(port_id)
        if index is None:
            raise ConfigError(f"audio device for port {port_id!r} is no longer present")
        return SoundDeviceSink(sample_rate=DEFAULT_SAMPLE_RATE, channels=1, device=index)

    def coordinator_factory(config: DaemonConfig) -> Coordinator:
        return Coordinator(
            config=config,
            clock=clock,
            resolver=resolver,
            sleeper=RealSleeper(),
            sink_factory=sink_factory,
        )

    return MainDeps(
        configure_logging=configure_logging,
        load_config=load_config,
        resolver=resolver,
        clock=clock,
        coordinator_factory=coordinator_factory,
        run=asyncio.run,
    )


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    import sys

    raise SystemExit(main(sys.argv[1:], deps=_prod_deps()))
