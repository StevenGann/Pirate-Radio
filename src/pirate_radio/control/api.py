"""The FastAPI control plane (Phase 6, P6-4) — routes, bearer auth, the consistent envelope.

``create_app`` wires the §15 endpoints over a ``ControlService``. Every response is the
``{success, data, error}`` envelope; unknown ``{name}`` → 404, missing/wrong token → 401, a bad
query → 422 (all enveloped via exception handlers). ``/health`` is the only unauthenticated route +
carries no station data. Blocking reads/regenerate run through the injected ``offload`` (R23) so a
handler never stalls the shared loop. The bearer token is read by env-NAME at app creation with
**fail-fast if unset** (never open-by-default, H22); the compare is constant-time.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import FastAPI, Header, Query
from fastapi.requests import Request
from fastapi.responses import JSONResponse

from pirate_radio.control.logs import RingLogHandler, query_logs
from pirate_radio.control.models import ApiResponse, fail, ok
from pirate_radio.control.service import ControlService, ScheduleNotFound, StationNotFound
from pirate_radio.errors import ConfigError

logger = logging.getLogger(__name__)


class _Unauthorized(Exception):
    """Missing/invalid bearer token (→ 401, enveloped)."""


def create_app(
    *,
    service: ControlService,
    log_ring: RingLogHandler,
    token_env: str = "PIRATE_API_TOKEN",
    offload: Callable[..., Awaitable[Any]] = asyncio.to_thread,
) -> FastAPI:
    token = os.environ.get(token_env, "").strip()
    if not token:  # H22: fail-fast, never open-by-default
        raise ConfigError(f"control API token env var {token_env!r} is not set or empty")

    app = FastAPI(title="PiRate Radio control API", version="1")

    def _require_token(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = f"Bearer {token}"
        # compare_digest raises TypeError on a non-ASCII header (Starlette decodes header bytes as
        # latin-1, so a junk byte survives). Treat any such malformed header as unauthorized — fail
        # CLOSED, never a 500 (P6-6 / Fact-Checker F1).
        try:
            valid = authorization is not None and secrets.compare_digest(authorization, expected)
        except TypeError:
            valid = False
        if not valid:
            raise _Unauthorized

    @app.exception_handler(_Unauthorized)
    async def _on_auth(_req: Request, _exc: _Unauthorized) -> JSONResponse:
        return _envelope(401, fail("unauthorized", "missing or invalid bearer token"))

    @app.exception_handler(Exception)
    async def _on_unhandled(_req: Request, exc: Exception) -> JSONResponse:
        # The envelope invariant is TOTAL: any unexpected error becomes a 500 envelope, never
        # Starlette's bare-text default (P6-6 / DA). The detail is generic — no internals leak.
        logger.error("unhandled control-API error: %s: %s", type(exc).__name__, exc)
        return _envelope(500, fail("internal", "internal server error"))

    @app.exception_handler(StationNotFound)
    async def _on_station(_req: Request, exc: StationNotFound) -> JSONResponse:
        return _envelope(404, fail("not_found", str(exc)))

    @app.exception_handler(ScheduleNotFound)
    async def _on_schedule(_req: Request, exc: ScheduleNotFound) -> JSONResponse:
        return _envelope(404, fail("not_found", str(exc)))

    # ---- routes (auth via the manual header dep so a 401 is enveloped, not FastAPI's default) ----
    @app.get("/health")
    async def health() -> ApiResponse:
        return ok({"status": "ok"})  # open + data-free liveness probe

    @app.get("/stations")
    async def stations(authorization: Annotated[str | None, Header()] = None) -> ApiResponse:
        _require_token(authorization)
        return ok(service.list_stations())

    @app.get("/stations/{name}/now")
    async def now(name: str, authorization: Annotated[str | None, Header()] = None) -> ApiResponse:
        _require_token(authorization)
        return ok(await offload(service.now_playing, name))

    @app.get("/stations/{name}/schedule")
    async def schedule(
        name: str,
        on: Annotated[date | None, Query(alias="date")] = None,
        authorization: Annotated[str | None, Header()] = None,
    ) -> ApiResponse:
        _require_token(authorization)
        return ok(await offload(service.schedule, name, on))

    @app.post("/stations/{name}/regenerate", status_code=202)
    async def regenerate(
        name: str, authorization: Annotated[str | None, Header()] = None
    ) -> ApiResponse:
        _require_token(authorization)
        await service.regenerate(name)
        return ok({"accepted": True})  # effect at the next day-roll/restart

    @app.post("/stations/{name}/skip", status_code=202)
    async def skip(name: str, authorization: Annotated[str | None, Header()] = None) -> ApiResponse:
        _require_token(authorization)
        service.skip(name)
        return ok({"accepted": True})  # the player drops the next item at the boundary

    @app.get("/logs")
    async def logs(
        authorization: Annotated[str | None, Header()] = None,
        station: str | None = None,
        level: str | None = None,
        since: datetime | None = None,
        limit: Annotated[int | None, Query(ge=1, le=10000)] = None,
    ) -> ApiResponse:
        _require_token(authorization)
        if since is not None and since.tzinfo is None:
            # Stored stamps are tz-aware (UTC); a naive `?since=2026-06-08T12:00:00` (the obvious
            # way an operator types it) would raise comparing naive-vs-aware. Treat naive as UTC
            # instead of 500-ing (P6-6 / DA).
            since = since.replace(tzinfo=UTC)
        entries = query_logs(
            log_ring.snapshot(), station=station, level=level, since=since, limit=limit
        )
        return ok(entries)

    return app


def _envelope(status_code: int, body: ApiResponse) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=body.model_dump())
