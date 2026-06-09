"""Programmatic uvicorn server for the control API (Phase 6, P6-5).

``make_server`` builds the ``uvicorn.Server`` (no bind — binding happens in ``serve()``), so the
host/port wiring is unit-testable without opening a socket. ``serve`` awaits the real bind (the only
hardware/network-adjacent line, ``pragma: no cover``); it shares the daemon's event loop (R23) and
is launched crash-isolated by the entrypoint so an API failure never cancels ``coordinator.run()``.
"""

from __future__ import annotations

from typing import Any


def make_server(app: Any, *, host: str, port: int) -> Any:
    """Build a uvicorn Server bound to ``host:port`` — constructed only (no socket opened yet)."""
    import uvicorn  # lazy (kept off the import path of anything that doesn't serve)

    config = uvicorn.Config(app, host=host, port=port, log_level="info", access_log=False)
    return uvicorn.Server(config)


async def serve(app: Any, *, host: str, port: int) -> None:  # pragma: no cover - the real bind
    await make_server(app, host=host, port=port).serve()
