"""The video library: identity, deduplication and the shape the pages consume.

The property under test throughout is the one the library exists for - two
files holding the same frames are ONE video, however they got there and
whatever they are called.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "debugweb"))

import library as LIB  # noqa: E402


def clip(root: Path, name: str, body: bytes) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


@pytest.fixture()
def lib(tmp_path):
    return LIB.connect(tmp_path), tmp_path


def test_same_bytes_under_two_names_are_one_video(lib):
    con, root = lib
    clip(root, "data/videos/from-the-phone.mp4", b"frames")
    clip(root, "server/data/9f2b1c.mp4", b"frames")
    report = LIB.scan(con, root)

    rows = LIB.videos(con, root)
    assert len(rows) == 1, "one clip in two places is one video"
    assert report["total"] == 1
    assert len(rows[0]["copies"]) == 2
    assert rows[0]["duplicateOf"] == 1


def test_different_bytes_are_different_videos(lib):
    con, root = lib
    clip(root, "data/videos/a.mp4", b"one")
    clip(root, "data/videos/b.mp4", b"two")
    LIB.scan(con, root)
    assert len(LIB.videos(con, root)) == 2


def test_the_canonical_path_prefers_the_video_folder(lib):
    con, root = lib
    # Registered root-first, so a later data/videos copy has to win on rank
    # rather than on arrival order.
    LIB.register(con, root, clip(root, "loose.mp4", b"frames"))
    LIB.register(con, root, clip(root, "data/videos/kept.mp4", b"frames"))
    row = LIB.videos(con, root)[0]
    assert row["path"] == "data/videos/kept.mp4"
    assert row["filename"] == "kept.mp4"


def test_importing_known_content_adds_no_second_video(lib):
    con, root = lib
    source = clip(root, "incoming/set-3.mp4", b"frames")
    first = LIB.import_file(con, root, source, filename="set-3.mp4")
    again = LIB.import_file(con, root, source, filename="a-different-name.mp4")

    assert first["isNew"] and not again["isNew"]
    assert again["id"] == first["id"]
    assert len(LIB.videos(con, root)) == 1
    assert len(list((root / "data" / "videos").glob("*.mp4"))) == 1


def test_importing_new_content_keeps_the_existing_file(lib):
    con, root = lib
    LIB.import_file(con, root, clip(root, "in/a.mp4", b"one"), filename="clip.mp4")
    second = LIB.import_file(con, root, clip(root, "in/b.mp4", b"two"), filename="clip.mp4")
    assert second["isNew"]
    files = sorted(p.read_bytes() for p in (root / "data" / "videos").glob("*.mp4"))
    assert files == [b"one", b"two"]


def test_rescan_does_not_rehash_unchanged_files(lib, monkeypatch):
    con, root = lib
    clip(root, "data/videos/a.mp4", b"frames")
    LIB.scan(con, root)

    calls = []
    monkeypatch.setattr(LIB, "digest", lambda p: calls.append(p) or "x" * 64)
    report = LIB.scan(con, root)
    assert calls == [], "an unchanged file must not be hashed again"
    assert report["unchanged"] == 1


def test_a_changed_file_is_rehashed_and_becomes_its_own_video(lib):
    con, root = lib
    path = clip(root, "data/videos/a.mp4", b"frames")
    LIB.scan(con, root)
    path.write_bytes(b"different frames entirely")
    import os
    os.utime(path, (0, 0))
    LIB.scan(con, root)
    # The old content has no copy on disk any more, but its row (and so its
    # traces) survive; the new content is a video of its own.
    rows = LIB.videos(con, root)
    assert len(rows) == 2
    assert [r["exists"] for r in sorted(rows, key=lambda r: r["exists"])] == [False, True]


def test_resolve_accepts_id_filename_and_copy_path(lib):
    con, root = lib
    clip(root, "data/videos/kept.mp4", b"frames")
    clip(root, "server/data/9f2b1c.mp4", b"frames")
    LIB.scan(con, root)
    row = LIB.videos(con, root)[0]
    for ident in (row["id"], row["sha256"], "kept.mp4", "9f2b1c.mp4"):
        assert LIB.resolve(con, root, ident) is not None, ident
    assert LIB.resolve(con, root, "not-a-clip.mp4") is None


def test_metadata_is_editable_only_through_the_named_fields(lib):
    con, root = lib
    LIB.register(con, root, clip(root, "data/videos/a.mp4", b"frames"))
    row = LIB.videos(con, root)[0]
    updated = LIB.update(con, row["id"], {"movement": "pull_up", "tags": "session-3"})
    assert updated["movement"] == "pull_up" and updated["tags"] == "session-3"
    with pytest.raises(ValueError, match="not editable"):
        LIB.update(con, row["id"], {"sha256": "0" * 64})


def test_forget_leaves_the_file_alone_unless_asked(lib):
    con, root = lib
    path = clip(root, "data/videos/a.mp4", b"frames")
    row = LIB.videos(con, root)[0] if LIB.count(con) else LIB.register(con, root, path)
    LIB.forget(con, root, row["id"])
    assert path.exists(), "removing a library row must not delete the video"
    assert LIB.count(con) == 0

    again = LIB.register(con, root, path)
    out = LIB.forget(con, root, again["id"], delete_file=True)
    assert out["filesDeleted"] == ["data/videos/a.mp4"]
    assert not path.exists()


def test_the_server_reports_one_clip_per_distinct_video(tmp_path, monkeypatch):
    """The whole point, at the level the pages see it."""
    import server
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setattr(server._LOCAL, "con", None, raising=False)
    clip(tmp_path, "data/videos/set-3.mp4", b"frames")
    clip(tmp_path, "server/data/9f2b1c.mp4", b"frames")
    clip(tmp_path, "other.mp4", b"other frames")

    names = [c["name"] for c in server.list_clips()]
    assert sorted(names) == ["other.mp4", "set-3.mp4"]
    duped = next(c for c in server.list_clips() if c["name"] == "set-3.mp4")
    assert duped["extraCopies"] == 1
    assert sorted(duped["copies"]) == ["data/videos/set-3.mp4", "server/data/9f2b1c.mp4"]


def test_find_clip_will_not_resolve_outside_the_library(tmp_path, monkeypatch):
    import server
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.setattr(server._LOCAL, "con", None, raising=False)
    clip(tmp_path, "data/videos/a.mp4", b"frames")
    (tmp_path / "secrets.env").write_text("nope")

    assert server.find_clip("a.mp4") is not None
    assert server.find_clip("secrets.env") is None
    assert server.find_clip("../../../etc/passwd") is None
