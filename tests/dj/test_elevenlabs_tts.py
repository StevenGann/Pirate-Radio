"""RED tests for ``ElevenLabsTTS`` in ``pirate_radio.dj.tts`` — Phase 3 plan §4.3 / §5 (P3-6).

Tests first (strict spec-driven TDD): the cloud TTS engine (D5), ranked alongside Piper. Mirrors
the Phase-2 ``PiperTTS`` shape — pure request-build / pure PCM-parse / error-map (from dj/_http,
NOT dj/text) / ONE lazy ``httpx`` line -> ``AudioBuffer`` at the station rate (H5). Requests
s16le PCM so it reuses the Phase-2 PCM-parse idiom (no MP3 decoder, §7-Q7). Empty text ->
station-rate silence; structural garbage -> ProviderFatal; the api_key never leaks (H22).
"""

from __future__ import annotations

import struct
import sys
import types
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from pirate_radio.config import ElevenLabsProviderConfig, ElevenLabsTTSConfig
from pirate_radio.dj.protocols import TTSEngine
from pirate_radio.dj.tts import (
    ElevenLabsTTS,
    build_elevenlabs_request,
    pcm_s16le_to_buffer,
)
from pirate_radio.errors import ProviderFatal, ProviderQuotaExceeded, ProviderUnavailable

_CFG = ElevenLabsTTSConfig(backend="elevenlabs", voice_id="V", stability=0.3, similarity_boost=0.9)
_PROV = ElevenLabsProviderConfig(api_key_env="ELEVENLABS_API_KEY")


def _areturn(value: Any) -> Callable[..., Awaitable[Any]]:
    async def _f(*a: object, **k: object) -> Any:
        return value

    return _f


# ---- pure request build -------------------------------------------------------------------
def test_build_elevenlabs_request_maps_voice_and_settings() -> None:
    url, body = build_elevenlabs_request(_CFG)
    assert url.endswith("/V")  # voice_id -> URL
    assert body["voice_settings"] == {"stability": 0.3, "similarity_boost": 0.9}


def test_build_elevenlabs_request_honors_base_url_override() -> None:
    url, _ = build_elevenlabs_request(_CFG, base_url="https://eg.test/v1/text-to-speech")
    assert url == "https://eg.test/v1/text-to-speech/V"


# ---- pure PCM parse (mirror wav_bytes_to_buffer guards) ------------------------------------
def test_pcm_s16le_golden() -> None:
    raw = struct.pack("<h", 16384)  # 0.5 in s16 (16384/32768 == 0.5 exactly)
    buf = pcm_s16le_to_buffer(raw, sample_rate=24000)
    # tolerance 1e-7 (NOT 1e-3): a wrong /32767 divisor gives 0.50001526 — a 1.5e-5 error a
    # loose tolerance would miss. This is the P2-5 bug class; pin it tight.
    assert abs(float(buf.samples[0, 0]) - 0.5) < 1e-7
    assert buf.sample_rate == 24000 and buf.channels == 1


def test_pcm_s16le_multi_frame_golden_and_reshape() -> None:
    # asymmetric multi-sample value pins byte-order (<h) AND the reshape/frame count
    raw = struct.pack("<hh", 16384, -8192)  # 0.5, -0.25 exactly
    buf = pcm_s16le_to_buffer(raw, sample_rate=24000)
    assert buf.frames == 2
    assert abs(float(buf.samples[0, 0]) - 0.5) < 1e-7
    assert abs(float(buf.samples[1, 0]) - (-0.25)) < 1e-7


def test_pcm_s16le_misaligned_is_fatal() -> None:
    with pytest.raises(ProviderFatal):
        pcm_s16le_to_buffer(b"\x00", sample_rate=24000)  # 1 byte: not frame-aligned


def test_pcm_s16le_empty_is_fatal() -> None:
    with pytest.raises(ProviderFatal):
        pcm_s16le_to_buffer(b"", sample_rate=24000)


# ---- synthesize: resample to station rate + empty-text silence (H5) ------------------------
async def test_elevenlabs_resamples_to_station_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = struct.pack("<h", 100) * 2400  # 0.1s @ 24k mono, non-silent (100/32768 != 0)
    monkeypatch.setattr(ElevenLabsTTS, "_fetch", _areturn(raw))
    buf = await ElevenLabsTTS(cfg=_CFG, provider=_PROV, api_key="k", sample_rate=48000).synthesize(
        "hello"
    )
    assert buf.sample_rate == 48000  # resampled from the 24k request rate to the station rate
    assert abs(buf.frames - 4800) <= 1  # 0.1s @ 48k (±1 polyphase edge) — real audio, not silence
    assert float(buf.samples.max()) > 0  # not a silent/empty buffer masquerading as success


async def test_elevenlabs_empty_text_silence_at_station_rate() -> None:
    buf = await ElevenLabsTTS(cfg=_CFG, provider=_PROV, api_key="k", sample_rate=48000).synthesize(
        "   "
    )
    assert buf.sample_rate == 48000 and buf.frames == 0


def test_elevenlabs_satisfies_tts_engine_protocol() -> None:
    assert isinstance(ElevenLabsTTS(cfg=_CFG, provider=_PROV, api_key="k"), TTSEngine)


# ---- _fetch error mapping via a FAKE httpx module (no real import / socket) ----------------
class _FakeResp:
    def __init__(self, *, status_code: int, content: bytes = b"", text: str = "") -> None:
        self.status_code = status_code
        self.content = content
        self.text = text


class _FakeClient:
    def __init__(self, *, resp: _FakeResp | None = None, exc: Exception | None = None) -> None:
        self._resp = resp
        self._exc = exc

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *a: object) -> bool:
        return False

    async def post(self, url: str, **kw: object) -> _FakeResp:
        if self._exc is not None:
            raise self._exc
        assert self._resp is not None
        return self._resp


def _install_fake_httpx(monkeypatch: pytest.MonkeyPatch, client: _FakeClient) -> None:
    fake = types.ModuleType("httpx")
    fake.AsyncClient = lambda **kw: client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "httpx", fake)


async def test_elevenlabs_401_is_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    # ElevenLabs 401 = bad key OR quota; both map Fatal -> skip to the Piper floor under failover
    _install_fake_httpx(monkeypatch, _FakeClient(resp=_FakeResp(status_code=401, text="nope")))
    with pytest.raises(ProviderFatal):
        await ElevenLabsTTS(cfg=_CFG, provider=_PROV, api_key="k").synthesize("hi")


async def test_elevenlabs_429_is_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    # §3.4/§6 gate row: 429 -> QuotaExceeded (distinct from other-4xx Fatal); 429->Fatal impl fails
    _install_fake_httpx(monkeypatch, _FakeClient(resp=_FakeResp(status_code=429, text="slow")))
    with pytest.raises(ProviderQuotaExceeded):
        await ElevenLabsTTS(cfg=_CFG, provider=_PROV, api_key="k").synthesize("hi")


async def test_elevenlabs_5xx_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_httpx(monkeypatch, _FakeClient(resp=_FakeResp(status_code=503, text="down")))
    with pytest.raises(ProviderUnavailable):
        await ElevenLabsTTS(cfg=_CFG, provider=_PROV, api_key="k").synthesize("hi")


async def test_elevenlabs_connect_error_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    class ConnectError(Exception): ...

    _install_fake_httpx(monkeypatch, _FakeClient(exc=ConnectError("refused")))
    with pytest.raises(ProviderUnavailable):
        await ElevenLabsTTS(cfg=_CFG, provider=_PROV, api_key="k").synthesize("hi")


async def test_elevenlabs_garbage_audio_is_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    # a 200 with non-frame-aligned PCM body -> ProviderFatal (mirror the WAV-garbage rule)
    _install_fake_httpx(monkeypatch, _FakeClient(resp=_FakeResp(status_code=200, content=b"\x00")))
    with pytest.raises(ProviderFatal):
        await ElevenLabsTTS(cfg=_CFG, provider=_PROV, api_key="k", sample_rate=24000).synthesize(
            "hi"
        )


async def test_elevenlabs_error_never_contains_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "SUPER_SECRET_KEY"
    _install_fake_httpx(monkeypatch, _FakeClient(resp=_FakeResp(status_code=401, text="denied")))
    with pytest.raises(ProviderFatal) as ei:
        await ElevenLabsTTS(cfg=_CFG, provider=_PROV, api_key=secret).synthesize("hi")
    assert secret not in str(ei.value)  # H22: the key never reaches the error string


async def test_elevenlabs_transport_error_never_contains_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # H22 on the transport path too: a connect error must not surface the key
    secret = "SUPER_SECRET_KEY"

    class ConnectError(Exception): ...

    _install_fake_httpx(monkeypatch, _FakeClient(exc=ConnectError("connecting to host")))
    with pytest.raises(ProviderUnavailable) as ei:
        await ElevenLabsTTS(cfg=_CFG, provider=_PROV, api_key=secret).synthesize("hi")
    assert secret not in str(ei.value)
