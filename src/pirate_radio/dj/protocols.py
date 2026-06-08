"""Backend Protocol seams (R11/R15): TextGenerator, TTSEngine, AudioSink.

Each Protocol documents units, threading (blocking native impls hop via
``asyncio.to_thread``), and that backend failures raise ``ProviderError`` (R15) — the
pipeline catches it to fire the R11 backstop. Real impls (Piper/Claude/SoundDevice)
land in later phases behind these unchanged seams.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pirate_radio.audio.buffer import AudioBuffer
from pirate_radio.dj.context import DjContext


@runtime_checkable
class TextGenerator(Protocol):
    """The DJ brain. ``patter`` returns plain text to speak (no SSML in v1).

    Raises ``ProviderError`` (R15) on backend failure. Awaitable; network impls do
    their own I/O, local impls that block MUST hop via ``asyncio.to_thread``. The
    grounded ``DjContext`` (§9.2, R16) is passed in Phase 3 — the seam the Phase-1
    docstring reserved; ``None`` is still accepted (the ``NullDJ`` floor ignores it).
    """

    async def patter(self, item_kind: str, context: DjContext | None) -> str: ...


@runtime_checkable
class TTSEngine(Protocol):
    """Text -> ``AudioBuffer`` (R14 normalized shape). Raises ``ProviderError`` (R15).

    Idempotent for identical text+config. Blocking native synths MUST use
    ``asyncio.to_thread``.
    """

    async def synthesize(self, text: str) -> AudioBuffer: ...


@runtime_checkable
class AudioSink(Protocol):
    """Play one ``AudioBuffer`` to completion, gaplessly after the previous call (§10).

    Awaiting ``play`` returns only when the buffer has been fully consumed.
    """

    async def play(self, buf: AudioBuffer) -> None: ...
