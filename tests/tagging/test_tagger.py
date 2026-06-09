"""RED tests for ``pirate_radio.tagging.tagger`` — Phase-5 P5-7 (orchestration).

`tag_library` walks the content tree (stable order), and per file (ISOLATED): skip-tagged gate →
fingerprint → AcoustID → MusicBrainz → choose_best → atomic write. A raising file never aborts the
batch (others still tag); `dry_run`, deterministic `--limit`, nice/ionice at start, and a summary
are all pinned. Every seam is injected so this runs with fakes — zero network, no binary, no files.
"""

from __future__ import annotations

from pathlib import Path

from pirate_radio.errors import TaggingFatal
from pirate_radio.tagging.models import AcoustIdMatch, Fingerprint, RecordingMetadata, TagPlan
from pirate_radio.tagging.tagger import tag_library


class _Fp:
    def __init__(self, *, fail_on: set[str] | None = None) -> None:
        self.calls: list[Path] = []
        self._fail_on = fail_on or set()

    def fingerprint(self, path: Path) -> Fingerprint:
        self.calls.append(path)
        if path.name in self._fail_on:
            raise TaggingFatal(f"fpcalc blew up on {path.name}")
        return Fingerprint(duration=100.0, fingerprint="FP")


class _Acoust:
    def __init__(self, *, matches: tuple[AcoustIdMatch, ...]) -> None:
        self._matches = matches
        self.calls = 0

    def lookup(self, fp: Fingerprint) -> tuple[AcoustIdMatch, ...]:
        self.calls += 1
        return self._matches


class _MB:
    def __init__(self, *, recording: RecordingMetadata) -> None:
        self._rec = recording
        self.calls = 0

    def recording(self, mbid: str) -> RecordingMetadata:
        self.calls += 1
        return self._rec


def _seams(tmp_path, **over):
    files = over.pop("files", ["a.flac", "b.flac"])
    for name in files:
        (tmp_path / name).write_bytes(b"AUDIO")
    written: list[TagPlan] = []

    def _write(plan: TagPlan, *, dry_run: bool = False) -> bool:
        if plan.is_noop:
            return False
        written.append(plan)
        return not dry_run

    seams: dict = {
        "content_dir": tmp_path,
        "fingerprinter": over.pop("fingerprinter", None) or _Fp(),
        "acoustid": over.pop("acoustid", None)
        or _Acoust(matches=(AcoustIdMatch(recording_id="mbid", score=0.95),)),
        "musicbrainz": over.pop("musicbrainz", None)
        or _MB(recording=RecordingMetadata(title="Song", artist="Band")),
        "read_tags": over.pop("read_tags", None) or (lambda p: RecordingMetadata()),
        "write": _write,
        "walk": over.pop("walk", None) or (lambda d: sorted(d.glob("*.flac"))),
        "lower_priority": over.pop("lower_priority", None) or (lambda: None),
    }
    seams.update(over)
    return seams, written


def test_tags_untagged_files(tmp_path) -> None:
    seams, written = _seams(tmp_path)
    summary = tag_library(**seams)
    assert summary.tagged == 2 and summary.failed == 0 and summary.total == 2
    assert {p.path.name for p in written} == {"a.flac", "b.flac"}


def test_skips_already_tagged_without_fingerprinting(tmp_path) -> None:
    fp = _Fp()
    seams, written = _seams(
        tmp_path,
        fingerprinter=fp,
        read_tags=lambda p: RecordingMetadata(title="Have", artist="Have"),
    )
    summary = tag_library(**seams)
    assert summary.skipped == 2 and summary.tagged == 0
    assert fp.calls == []  # skip-gate short-circuits BEFORE the expensive fingerprint


def test_no_confident_match_skips_without_musicbrainz(tmp_path) -> None:
    mb = _MB(recording=RecordingMetadata(title="X"))
    seams, _ = _seams(
        tmp_path,
        acoustid=_Acoust(matches=(AcoustIdMatch(recording_id="m", score=0.10),)),  # below floor
        musicbrainz=mb,
    )
    summary = tag_library(**seams)
    assert summary.skipped == 2 and mb.calls == 0  # no MB lookup for a sub-floor match


def test_per_file_failure_is_isolated(tmp_path) -> None:
    seams, written = _seams(tmp_path, fingerprinter=_Fp(fail_on={"a.flac"}))
    summary = tag_library(**seams)
    assert summary.failed == 1 and summary.tagged == 1  # b.flac still tagged; batch not aborted
    assert {p.path.name for p in written} == {"b.flac"}


def test_generic_exception_is_also_isolated(tmp_path) -> None:
    # DA: the per-file guard must catch a NON-TaggingError too (a bare RuntimeError/OSError from a
    # degenerate file / mutagen) — one bad file never aborts the batch.
    class _Boom:
        def fingerprint(self, path: Path) -> Fingerprint:
            if path.name == "a.flac":
                raise RuntimeError("mutagen segfault surfaced as a Python error")
            return Fingerprint(duration=100.0, fingerprint="FP")

    seams, written = _seams(tmp_path, fingerprinter=_Boom())
    summary = tag_library(**seams)
    assert summary.failed == 1 and summary.tagged == 1  # b.flac still tagged
    assert {p.path.name for p in written} == {"b.flac"}


def test_dry_run_writes_nothing(tmp_path) -> None:
    seams, _ = _seams(tmp_path)
    summary = tag_library(**seams, dry_run=True)
    assert summary.tagged == 0 and summary.skipped == 2  # planned-but-not-written counts as skipped


def test_limit_is_deterministic(tmp_path) -> None:
    seams, written = _seams(tmp_path, files=["c.flac", "a.flac", "b.flac"])
    summary = tag_library(**seams, limit=2)
    assert summary.total == 2
    assert {p.path.name for p in written} == {"a.flac", "b.flac"}  # the first two in STABLE order


def test_lowers_priority_once_at_start(tmp_path) -> None:
    calls: list[int] = []
    seams, _ = _seams(tmp_path, lower_priority=lambda: calls.append(1))
    tag_library(**seams)
    assert calls == [1]  # nice/ionice applied once so a run can't starve a live broadcast (RPi)
