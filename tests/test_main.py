"""RED tests for ``pirate_radio.__main__`` — Phase-4 plan §H / P4-8 (Q10).

``main(argv, *, deps)`` is the testable seam behind ``python -m pirate_radio``: configure logging
**first** (so a config error is logged through the operator stream), load+validate config, build the
coordinator, then either run the daemon or — for ``--regenerate`` — force-regenerate schedules and
**exit** (a oneshot tool, not the live daemon). All side-effecting collaborators are injected via
``deps`` so this runs with fakes only (no real resolver, no ``asyncio.run``, no filesystem).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pirate_radio.__main__ import MainDeps, main


class _FakeCoordinator:
    def __init__(self) -> None:
        self.regen_calls: list[str | None] = []
        self.ran = False

    def regenerate_now(self, only: str | None = None) -> int:
        self.regen_calls.append(only)
        return 1 if only is None else 1

    async def run(self) -> None:
        self.ran = True


@dataclass
class _Recorder:
    order: list[str] = field(default_factory=list)
    log_level: str | None = None
    ran_coro: bool = False
    coord: _FakeCoordinator = field(default_factory=_FakeCoordinator)

    def configure_logging(self, level: str) -> None:
        self.order.append("log")
        self.log_level = level

    def load_config(self, path, *, resolver, clock, preflight):  # noqa: ANN001
        self.order.append("config")
        return object()  # opaque: the fake coordinator_factory ignores it

    def coordinator_factory(self, config):  # noqa: ANN001
        self.order.append("coord")
        return self.coord

    def run(self, coro) -> None:  # noqa: ANN001
        self.ran_coro = True
        coro.close()  # avoid an un-awaited-coroutine warning; we only assert it was handed over


def _deps(rec: _Recorder) -> MainDeps:
    return MainDeps(
        configure_logging=rec.configure_logging,
        load_config=rec.load_config,
        resolver=object(),
        clock=object(),
        coordinator_factory=rec.coordinator_factory,
        run=rec.run,
    )


def test_configures_logging_before_loading_config() -> None:
    rec = _Recorder()
    main(["--config", "/etc/pirate/config.json"], deps=_deps(rec))
    assert rec.order[0] == "log" and rec.order.index("log") < rec.order.index("config")


def test_passes_the_log_level_through() -> None:
    rec = _Recorder()
    main(["--config", "/c.json", "--log-level", "DEBUG"], deps=_deps(rec))
    assert rec.log_level == "DEBUG"


def test_normal_run_starts_the_daemon() -> None:
    rec = _Recorder()
    rc = main(["--config", "/c.json"], deps=_deps(rec))
    assert rc == 0 and rec.ran_coro and rec.coord.regen_calls == []  # ran, did NOT regenerate


def test_regenerate_all_is_a_oneshot_that_does_not_run_the_daemon() -> None:
    rec = _Recorder()
    rc = main(["--config", "/c.json", "--regenerate"], deps=_deps(rec))
    assert (
        rc == 0 and rec.coord.regen_calls == [None] and not rec.ran_coro
    )  # regenerated, no daemon


def test_regenerate_one_station_passes_the_name() -> None:
    rec = _Recorder()
    main(["--config", "/c.json", "--regenerate", "Pi0"], deps=_deps(rec))
    assert rec.coord.regen_calls == ["Pi0"] and not rec.ran_coro


# ---- daemon run + crash-isolated API (P6-5) -----------------------------------------------
async def test_isolated_swallows_a_task_crash() -> None:
    from pirate_radio.__main__ import _isolated

    async def _boom() -> None:
        raise RuntimeError("api down")

    await _isolated(_boom(), name="control-api")  # MUST NOT raise (broadcast must survive)


async def test_run_daemon_api_crash_does_not_stop_the_broadcast() -> None:
    import asyncio

    from pirate_radio.__main__ import _run_daemon

    ran: list[str] = []

    class _Coord:
        async def run(self) -> None:
            ran.append("started")
            await asyncio.sleep(0.01)
            ran.append("finished")

    async def _api_boom() -> None:
        raise RuntimeError("api down")

    await _run_daemon(_Coord(), api_coro=_api_boom())  # type: ignore[arg-type]
    assert ran == ["started", "finished"]  # the broadcast ran to completion despite the API crash


def test_main_builds_the_api_when_a_factory_is_provided() -> None:
    rec = _Recorder()
    built: list = []

    def _build_api(config, coordinator):  # noqa: ANN001
        built.append((config, coordinator))
        return None  # disabled-equivalent for this test; _run_daemon then runs only the broadcast

    deps = _deps(rec)
    deps = MainDeps(  # rebuild with build_api set
        configure_logging=deps.configure_logging,
        load_config=deps.load_config,
        resolver=deps.resolver,
        clock=deps.clock,
        coordinator_factory=deps.coordinator_factory,
        run=deps.run,
        build_api=_build_api,
    )
    main(["--config", "/c.json"], deps=deps)
    assert len(built) == 1  # main consulted the API factory
