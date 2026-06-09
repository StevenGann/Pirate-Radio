"""RED tests for ``pirate_radio.control.api`` — Phase-6 P6-4 (FastAPI routes + auth).

In-process ``TestClient`` (no socket bind — ``pytest-socket`` enforces it). Every route returns the
consistent envelope; unknown ``{name}`` → 404; missing/wrong token → 401; ``/health`` open +
data-free; a bad query → 422; skip/regenerate → 202 + side effect; the schedule read is offloaded
the injected R23 seam (asserted); the token is read by env-name with fail-fast if unset.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from pirate_radio.catalog.models import Track
from pirate_radio.clock import FixedClock
from pirate_radio.config import PiperTTSConfig, StationConfig
from pirate_radio.control.api import create_app
from pirate_radio.control.logs import RingLogHandler
from pirate_radio.control.service import ControlService
from pirate_radio.errors import ConfigError
from pirate_radio.schedule.models import DailySchedule, StationIdItem, TrackItem
from pirate_radio.status import StationState, StationStatus

pytestmark = pytest.mark.disable_socket  # P6-4: prove the routes never bind a real TCP socket (R21)

_TZ = ZoneInfo("America/New_York")
_NOW = datetime(2026, 6, 10, 0, 0, 30, tzinfo=_TZ)
_TOKEN = "s3cret-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


def _config(name: str) -> StationConfig:
    return StationConfig(
        name=name,
        schedule_dir=Path("/sched"),
        content_dir=Path("/content"),
        dj_personality="warm",
        tts=(PiperTTSConfig(backend="piper", voice="v"),),
        audio_device=f"usb-{name}",
    )


def _schedule(day: date) -> DailySchedule:
    start = datetime(2026, 6, 10, 0, 0, tzinfo=_TZ)
    track = Track(path=Path("/c/g/a.flac"), group="g", duration=600.0, title="Song", artist="Band")
    items = (
        TrackItem(planned_start=start, duration=600.0, block_name="Morning", track=track),
        StationIdItem(planned_start=start, duration=5.0, block_name="Morning"),
    )
    return DailySchedule(date=day, station="Pi0", seed=1, items=items)


def _client(monkeypatch, **over) -> tuple[TestClient, dict]:
    monkeypatch.setenv("PIRATE_API_TOKEN", _TOKEN)
    rec: dict = {"skipped": [], "regenerated": [], "offloaded": []}

    def _skip(name: str) -> None:
        rec["skipped"].append(name)

    async def _regen(name: str) -> None:
        rec["regenerated"].append(name)

    async def _offload(fn, *a, **kw):
        rec["offloaded"].append(fn.__name__)
        return fn(*a, **kw)  # run inline in the test (real to_thread in prod)

    service = ControlService(
        registry={"Pi0": StationStatus(name="Pi0", state=StationState.ON_AIR)},
        configs={"Pi0": _config("Pi0")},
        clock=FixedClock(_NOW),
        load_schedule=over.pop("load_schedule", lambda name, day: _schedule(day)),
        skip=_skip,
        regenerate=_regen,
    )
    ring = RingLogHandler(maxsize=50, clock=lambda: _NOW)
    app = create_app(service=service, log_ring=ring, token_env="PIRATE_API_TOKEN", offload=_offload)
    return TestClient(app), rec


# ---- fail-fast on missing token ------------------------------------------------------------
def test_create_app_without_token_env_fails_fast(monkeypatch) -> None:
    monkeypatch.delenv("PIRATE_API_TOKEN", raising=False)
    service = ControlService(
        registry={}, configs={}, clock=FixedClock(_NOW), load_schedule=lambda n, d: None
    )
    with pytest.raises(ConfigError):  # never start open-by-default
        create_app(
            service=service, log_ring=RingLogHandler(maxsize=1), token_env="PIRATE_API_TOKEN"
        )


# ---- health (open, data-free) -------------------------------------------------------------
def test_health_is_open_and_data_free(monkeypatch) -> None:
    client, _ = _client(monkeypatch)
    r = client.get("/health")  # no auth header
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True and body["error"] is None
    assert "Pi0" not in r.text  # no station data leaks on the unauthenticated probe


# ---- auth ----------------------------------------------------------------------------------
def test_stations_requires_a_token(monkeypatch) -> None:
    client, _ = _client(monkeypatch)
    assert client.get("/stations").status_code == 401
    assert client.get("/stations", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_stations_with_token_returns_the_envelope(monkeypatch) -> None:
    client, _ = _client(monkeypatch)
    r = client.get("/stations", headers=_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True and body["data"][0]["name"] == "Pi0"


# ---- 404 + envelope ------------------------------------------------------------------------
def test_unknown_station_is_404_with_envelope(monkeypatch) -> None:
    client, _ = _client(monkeypatch)
    r = client.get("/stations/Nope/now", headers=_AUTH)
    assert r.status_code == 404
    body = r.json()
    assert body["success"] is False and body["error"]["code"] == "not_found"


# ---- now / schedule (+ R23 offload) -------------------------------------------------------
def test_now_playing_ok(monkeypatch) -> None:
    client, _ = _client(monkeypatch)
    body = client.get("/stations/Pi0/now", headers=_AUTH).json()
    assert body["data"]["playing"] is True and body["data"]["item_kind"] == "track"


def test_schedule_read_is_offloaded_r23(monkeypatch) -> None:
    client, rec = _client(monkeypatch)
    r = client.get("/stations/Pi0/schedule", headers=_AUTH)
    assert r.status_code == 200 and r.json()["data"]["item_count"] == 2
    assert "schedule" in rec["offloaded"]  # the blocking file read ran through the offload seam


def test_schedule_bad_date_is_422(monkeypatch) -> None:
    client, _ = _client(monkeypatch)
    assert client.get("/stations/Pi0/schedule?date=not-a-date", headers=_AUTH).status_code == 422


# ---- skip / regenerate (202 + side effect) -------------------------------------------------
def test_skip_returns_202_and_invokes_skip(monkeypatch) -> None:
    client, rec = _client(monkeypatch)
    r = client.post("/stations/Pi0/skip", headers=_AUTH)
    assert r.status_code == 202 and rec["skipped"] == ["Pi0"]


def test_regenerate_returns_202_and_invokes_regenerate(monkeypatch) -> None:
    client, rec = _client(monkeypatch)
    r = client.post("/stations/Pi0/regenerate", headers=_AUTH)
    assert r.status_code == 202 and rec["regenerated"] == ["Pi0"]


def test_skip_unknown_station_is_404(monkeypatch) -> None:
    client, rec = _client(monkeypatch)
    assert client.post("/stations/Nope/skip", headers=_AUTH).status_code == 404
    assert rec["skipped"] == []  # never invoked


# ---- logs ----------------------------------------------------------------------------------
def test_logs_filters_from_the_ring(monkeypatch) -> None:
    import logging

    monkeypatch.setenv("PIRATE_API_TOKEN", _TOKEN)
    service = ControlService(
        registry={}, configs={}, clock=FixedClock(_NOW), load_schedule=lambda n, d: None
    )
    ring = RingLogHandler(maxsize=50, clock=lambda: _NOW)
    ring.emit(logging.LogRecord("x", logging.INFO, __file__, 1, "station Pi0 on air", None, None))
    ring.emit(
        logging.LogRecord(
            "x", logging.WARNING, __file__, 1, "station Pi0 backstop fired", None, None
        )
    )
    app = create_app(service=service, log_ring=ring, token_env="PIRATE_API_TOKEN")
    client = TestClient(app)
    body = client.get("/logs?level=WARNING", headers=_AUTH).json()
    assert body["success"] is True
    assert [e["message"] for e in body["data"]] == ["station Pi0 backstop fired"]
