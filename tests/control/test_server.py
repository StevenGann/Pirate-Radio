"""RED tests for ``pirate_radio.control.server`` — Phase-6 P6-5 (uvicorn wiring, no bind)."""

from __future__ import annotations

from fastapi import FastAPI

from pirate_radio.control.server import make_server


def test_make_server_binds_the_configured_host_and_port() -> None:
    server = make_server(FastAPI(), host="127.0.0.1", port=9876)
    assert server.config.host == "127.0.0.1" and server.config.port == 9876  # built, not yet bound
