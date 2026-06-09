"""RED tests for ``pirate_radio.tagging.tag_writer`` — Phase-5 P5-6 (atomic tag write).

The destructive operation. Two CI-testable concerns, no codec needed:
1. **atomic orchestration** — copy to a SAME-DIR temp, write tags to the temp, fsync, atomic
   ``os.replace``; a mid-write failure leaves the ORIGINAL intact (power-loss safe, H-T4/RPi);
   ``dry_run`` and a no-op plan write nothing. Tested with an injected write seam on plain files.
2. **mutagen mapping** — ``_mutagen_write`` maps ``TagPlan.changes()`` to mutagen easy keys
   (``year`` → ``date``), tested against a ``mutagen.File`` mock. Only mutagen's real-container open
   is hardware-only (mutagen's job, not ours — our logic is fully CI-covered).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pirate_radio.errors import TaggingFatal
from pirate_radio.tagging.models import TagPlan
from pirate_radio.tagging.tag_writer import apply_tag_plan


def _file(tmp_path: Path, content: bytes = b"ORIGINAL-AUDIO") -> Path:
    p = tmp_path / "song.flac"
    p.write_bytes(content)
    return p


# ---- no-op + dry-run write nothing --------------------------------------------------------
def test_noop_plan_writes_nothing(tmp_path) -> None:
    calls: list = []
    applied = apply_tag_plan(TagPlan(path=_file(tmp_path)), write_tags=lambda p, c: calls.append(p))
    assert applied is False and calls == []


def test_dry_run_writes_nothing(tmp_path) -> None:
    p = _file(tmp_path)
    calls: list = []
    applied = apply_tag_plan(
        TagPlan(path=p, title="New"), write_tags=lambda path, c: calls.append(path), dry_run=True
    )
    assert applied is False and calls == [] and p.read_bytes() == b"ORIGINAL-AUDIO"


# ---- atomic apply -------------------------------------------------------------------------
def test_apply_writes_via_a_same_dir_temp_then_replaces(tmp_path) -> None:
    p = _file(tmp_path)
    seen: dict = {}

    def _write(temp: Path, changes: dict) -> None:
        seen["temp"] = temp
        seen["changes"] = changes
        temp.write_bytes(b"TAGGED-AUDIO")  # the "tag write" mutates the temp, not the original

    applied = apply_tag_plan(TagPlan(path=p, title="Song", year=1984), write_tags=_write)
    assert applied is True
    assert seen["temp"].parent == p.parent  # SAME dir (so os.replace is an atomic same-fs rename)
    assert seen["changes"] == {"title": "Song", "year": 1984}
    assert p.read_bytes() == b"TAGGED-AUDIO"  # original replaced atomically
    assert not seen["temp"].exists()  # temp consumed by the rename


def test_apply_failure_leaves_the_original_intact_and_cleans_up(tmp_path) -> None:
    p = _file(tmp_path)
    temps: list[Path] = []

    def _boom(temp: Path, changes: dict) -> None:
        temps.append(temp)
        temp.write_bytes(b"HALF-WRITTEN")
        raise TaggingFatal("mutagen blew up mid-write")

    with pytest.raises(TaggingFatal):
        apply_tag_plan(TagPlan(path=p, title="Song"), write_tags=_boom)
    assert p.read_bytes() == b"ORIGINAL-AUDIO"  # power-loss-safe: original untouched
    assert temps and not temps[0].exists()  # the half-written temp is cleaned up


# ---- mutagen mapping (mock; no real codec) ------------------------------------------------
class _FakeAudio(dict):
    def __init__(self) -> None:
        super().__init__()
        self.saved = False

    def save(self) -> None:
        self.saved = True


def test_mutagen_write_maps_changes_to_easy_keys(tmp_path, monkeypatch) -> None:
    from pirate_radio.tagging import tag_writer

    fake = _FakeAudio()
    monkeypatch.setattr(tag_writer, "_open_mutagen", lambda path: fake)
    tag_writer._mutagen_write(
        tmp_path / "x.flac", {"title": "T", "artist": "A", "album": "Al", "year": 1991}
    )
    assert fake["title"] == ["T"] and fake["artist"] == ["A"] and fake["album"] == ["Al"]
    assert fake["date"] == ["1991"]  # year -> the 'date' easy key, stringified
    assert fake.saved


def test_mutagen_write_unreadable_file_is_fatal(tmp_path, monkeypatch) -> None:
    from pirate_radio.tagging import tag_writer

    monkeypatch.setattr(tag_writer, "_open_mutagen", lambda path: None)  # mutagen can't parse it
    with pytest.raises(TaggingFatal):
        tag_writer._mutagen_write(tmp_path / "x.flac", {"title": "T"})
