"""Shared pytest fixtures for PiRate Radio tests.

Audio fixtures are **real tiny WAVs** written via the stdlib ``wave`` module (and
tagged via mutagen's ``WAVE`` interface) so metadata tests exercise real mutagen on
real files — no mocks (plan §6.0 / §6.8).
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest
from mutagen.id3 import TALB, TDRC, TIT2, TPE1
from mutagen.wave import WAVE


def write_silent_wav(path: Path, *, seconds: int = 1) -> None:
    """Write a real ``seconds``-long silent mono WAV (a genuine ``info.length``)."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * (8000 * seconds))


def write_tagged_wav(
    path: Path, *, title: str, artist: str, album: str, year: int, seconds: int = 1
) -> None:
    """Write a silent WAV carrying real ID3 tags via the WAVE tag interface.

    (Writing a bare ID3 blob to a .wav path makes mutagen mis-detect it as MP3;
    the WAVE object stores the ID3 inside the RIFF structure correctly.)
    """
    write_silent_wav(path, seconds=seconds)
    audio = WAVE(str(path))
    audio.add_tags()
    audio.tags.add(TIT2(encoding=3, text=title))
    audio.tags.add(TPE1(encoding=3, text=artist))
    audio.tags.add(TALB(encoding=3, text=album))
    audio.tags.add(TDRC(encoding=3, text=str(year)))
    audio.save()


@pytest.fixture
def content_tree(tmp_path: Path) -> Path:
    """A content_dir with two non-empty groups of tiny real WAVs + an empty group."""
    root = tmp_path / "library"
    for group, count in (("classical", 2), ("oldies", 2)):
        d = root / group
        d.mkdir(parents=True)
        for i in range(count):
            write_silent_wav(d / f"track{i}.wav")
    (root / "empty_group").mkdir()  # present but empty -> must be ignored
    return root


@pytest.fixture
def tagged_wav(tmp_path: Path) -> Path:
    """A single WAV carrying real, known ID3 tags (drives the tag-extraction test)."""
    p = tmp_path / "tagged.wav"
    write_tagged_wav(p, title="Clair de Lune", artist="Debussy", album="Suite", year=1905)
    return p


@pytest.fixture
def make_wav() -> object:
    """Factory: write a silent WAV at an arbitrary path, creating parent dirs."""

    def _make(path: Path, *, seconds: int = 1) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_silent_wav(path, seconds=seconds)
        return path

    return _make
