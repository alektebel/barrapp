#!/usr/bin/env python3
"""The video library: one row per clip, keyed by the bytes inside it.

Before this, "which videos are there" was answered by listing three
directories and de-duplicating on filename. That is the wrong key. The same
clip lands in this repository more than once by ordinary means - it sits at the
root from the phone dump, gets copied into `data/videos/` to be worked on, and
the debugger's own import writes a third copy under a uniquified name so a
retry cannot overwrite the first attempt. Three files, identical frames, three
cards on the shelf, three independent debug histories, and no way to notice
that a rejection you already investigated is the same rejection.

So the key is the sha256 of the file content, and the library is a table:

    videos        one row per DISTINCT clip - the thing you debug
    video_copies  every path that content was found at - and the hash cache

A second copy of known content is recorded in `video_copies` and changes
nothing else: the shelf still shows one card, the trace history stays whole,
and the extra path is visible as provenance rather than as another video.
Deduplication is therefore a property of the schema (`sha256 PRIMARY KEY`),
not of a filter someone has to remember to apply.

Everything takes an explicit `root` rather than reading a module global,
because the server is exercised against a tmp_path in the tests and a library
that writes to the developer's real `data/videos/` during a test run is worse
than no library.

Stdlib only, like the server it serves.

    python tools/debugweb/library.py scan          # index what is on disk
    python tools/debugweb/library.py list
    python tools/debugweb/library.py add clip.mp4  # copy a file in
    python tools/debugweb/library.py show <id>
    python tools/debugweb/library.py set <id> movement=pull_up title="Set 3"
    python tools/debugweb/library.py rm <id> [--delete-file]
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

VIDEO_EXT = (".mp4", ".mov", ".m4v", ".avi", ".mkv")

# Where a clip may legitimately live. Order matters twice: it is the order the
# scan walks, and the earlier a directory appears the more it is preferred as
# the canonical home of content found in several places. `data/videos` is
# first because it is the one directory that exists to hold clips.
SEARCH_DIRS = ("data/videos", ".", "server/data")

# The editable columns. A metadata write that is not in this set is refused
# rather than silently dropped, so a typo in a field name is visible.
EDITABLE = ("title", "movement", "tags", "notes")

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    sha256     TEXT PRIMARY KEY,
    id         TEXT UNIQUE NOT NULL,
    path       TEXT NOT NULL,
    filename   TEXT NOT NULL,
    bytes      INTEGER NOT NULL,
    mtime      REAL NOT NULL,
    added_at   REAL NOT NULL,
    source     TEXT NOT NULL,
    title      TEXT NOT NULL DEFAULT '',
    movement   TEXT NOT NULL DEFAULT '',
    tags       TEXT NOT NULL DEFAULT '',
    notes      TEXT NOT NULL DEFAULT '',
    duration_s REAL,
    fps        REAL,
    frames     INTEGER,
    width      INTEGER,
    height     INTEGER,
    probe_note TEXT
);
CREATE TABLE IF NOT EXISTS video_copies (
    path   TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    bytes  INTEGER NOT NULL,
    mtime  REAL NOT NULL,
    seen   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS video_copies_sha ON video_copies(sha256);
"""


# ---------------------------------------------------------------------------
# opening
# ---------------------------------------------------------------------------
def db_path(root: Path) -> Path:
    """`out/` and not `data/videos/`: the library is derived from the videos,
    like the keypoint cache and the traces beside it, and a database file
    sitting among the clips is one more thing every directory walk in this
    project has to learn to ignore."""
    return Path(root) / "out" / "library.db"


def connect(root: Path) -> sqlite3.Connection:
    """Open (creating if needed) the library for this root."""
    path = db_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")   # the server reads while a scan writes
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    return con


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------
def digest(path: Path) -> str:
    """sha256 of the whole file. Not a sample of it: two phone clips of the
    same set share their first megabyte (container, codec config, the first
    seconds of a static frame) and a prefix hash would fuse them into one."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(1 << 20):
            h.update(block)
    return h.hexdigest()


def short(sha: str) -> str:
    return sha[:12]


def is_video(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXT


def rel(root: Path, path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return str(Path(path).resolve())


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------
def register(con: sqlite3.Connection, root: Path, path: Path,
             source: str = "scan", **meta) -> dict:
    """Put one file in the library and return its row.

    The return carries `isNew`: False means this content was already known,
    and the caller (an import, say) is looking at a duplicate rather than at a
    video it just added. That distinction is the whole point of the table, so
    it is returned rather than logged.
    """
    path = Path(path)
    stat = path.stat()
    sha = digest(path)
    where = rel(root, path)
    now = time.time()

    con.execute(
        "INSERT INTO video_copies(path, sha256, bytes, mtime, seen) "
        "VALUES(?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET "
        "sha256=excluded.sha256, bytes=excluded.bytes, mtime=excluded.mtime, seen=excluded.seen",
        (where, sha, stat.st_size, stat.st_mtime, now))

    row = con.execute("SELECT * FROM videos WHERE sha256=?", (sha,)).fetchone()
    if row is None:
        fields = {k: v for k, v in meta.items() if k in EDITABLE and v is not None}
        con.execute(
            "INSERT INTO videos(sha256, id, path, filename, bytes, mtime, added_at, "
            "source, title, movement, tags, notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (sha, short(sha), where, path.name, stat.st_size, stat.st_mtime, now, source,
             fields.get("title", ""), fields.get("movement", ""),
             fields.get("tags", ""), fields.get("notes", "")))
        con.commit()
        return dict(con.execute("SELECT * FROM videos WHERE sha256=?", (sha,)).fetchone(),
                    isNew=True)

    # Known content. Move the canonical path only if this copy lives in a
    # more-preferred directory, or if the recorded one has gone away - never
    # just because this scan happened to reach it later.
    if _rank(where) < _rank(row["path"]) or not (Path(root) / row["path"]).is_file():
        con.execute("UPDATE videos SET path=?, filename=?, mtime=? WHERE sha256=?",
                    (where, path.name, stat.st_mtime, sha))
    con.commit()
    return dict(con.execute("SELECT * FROM videos WHERE sha256=?", (sha,)).fetchone(),
                isNew=False)


def _rank(where: str) -> int:
    parent = str(Path(where).parent).replace("\\", "/")
    return SEARCH_DIRS.index(parent) if parent in SEARCH_DIRS else len(SEARCH_DIRS)


def scan(con: sqlite3.Connection, root: Path) -> dict:
    """Index every video under the search directories.

    Unchanged files are not re-hashed - `video_copies` doubles as the hash
    cache, keyed on (path, size, mtime) - so a rescan of a settled library is
    a directory walk and a few hundred bytes of SQL.
    """
    root = Path(root)
    cache = {r["path"]: r for r in con.execute("SELECT * FROM video_copies")}
    added, known, unchanged = [], [], 0
    present: set[str] = set()

    for name in SEARCH_DIRS:
        folder = root / name
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if not is_video(path):
                continue
            where = rel(root, path)
            present.add(where)
            stat = path.stat()
            hit = cache.get(where)
            if hit and hit["bytes"] == stat.st_size and abs(hit["mtime"] - stat.st_mtime) < 1e-6 \
                    and con.execute("SELECT 1 FROM videos WHERE sha256=?", (hit["sha256"],)).fetchone():
                unchanged += 1
                continue
            row = register(con, root, path, source="scan")
            (added if row["isNew"] else known).append(row["id"])

    # A path that vanished stops being a copy. The video row survives as long
    # as ANY copy of that content is still on disk; a video whose every copy
    # is gone is kept too, because its traces are still real - it is reported
    # as missing rather than deleted, and only `rm` deletes.
    gone = [p for p in cache if p not in present]
    if gone:
        con.executemany("DELETE FROM video_copies WHERE path=?", [(p,) for p in gone])
        con.commit()
    return {"added": added, "alreadyKnown": known, "unchanged": unchanged,
            "copiesDropped": gone, "total": count(con)}


def import_file(con: sqlite3.Connection, root: Path, src: Path,
                filename: str | None = None, source: str = "import",
                **meta) -> dict:
    """Copy a file into `data/videos/` and register it.

    If the content is already in the library the copy is discarded and the
    existing row is returned with `isNew` False - importing the same clip
    twice must not produce a second card on the shelf.
    """
    root, src = Path(root), Path(src)
    sha = digest(src)
    row = con.execute("SELECT * FROM videos WHERE sha256=?", (sha,)).fetchone()
    if row is not None and (root / row["path"]).is_file():
        return dict(row, isNew=False)
    folder = root / "data" / "videos"
    folder.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(filename or src.name).stem)[:80] or "video"
    suffix = Path(filename or src.name).suffix.lower()
    dest = folder / f"{stem}{suffix}"
    if dest.exists():
        dest = folder / f"{stem}-{short(sha)}{suffix}"
    shutil.copyfile(src, dest)
    return register(con, root, dest, source=source, **meta)


def update(con: sqlite3.Connection, ident: str, fields: dict) -> dict | None:
    row = get(con, ident)
    if row is None:
        return None
    bad = [k for k in fields if k not in EDITABLE]
    if bad:
        raise ValueError(f"not editable: {', '.join(sorted(bad))}; "
                         f"editable fields are {', '.join(EDITABLE)}")
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        con.execute(f"UPDATE videos SET {sets} WHERE sha256=?",
                    (*[str(v) for v in fields.values()], row["sha256"]))
        con.commit()
    return get(con, ident)


def forget(con: sqlite3.Connection, root: Path, ident: str,
           delete_file: bool = False) -> dict | None:
    """Drop a video from the library. The file is left alone unless asked for,
    and its traces in `out/traces/` are never touched: they are evidence."""
    row = get(con, ident)
    if row is None:
        return None
    removed = []
    if delete_file:
        for copy in row["copies"]:
            path = Path(root) / copy["path"]
            if path.is_file():
                path.unlink()
                removed.append(copy["path"])
    con.execute("DELETE FROM video_copies WHERE sha256=?", (row["sha256"],))
    con.execute("DELETE FROM videos WHERE sha256=?", (row["sha256"],))
    con.commit()
    return {"id": row["id"], "filename": row["filename"], "filesDeleted": removed}


# ---------------------------------------------------------------------------
# probing (best effort; the library is useful without it)
# ---------------------------------------------------------------------------
def probe(con: sqlite3.Connection, root: Path, row) -> dict:
    """Fill duration/fps/geometry once, from the same `probe_video` the
    pipeline opens the clip with - so a duration shown on the shelf is the
    duration the analyzer will see, not one from a different decoder."""
    if row["duration_s"] is not None or row["probe_note"]:
        return dict(row)
    path = Path(root) / row["path"]
    try:
        from barra.ingest import probe_video
        info = probe_video(path)
        if not info.get("ok"):
            raise OSError(info.get("reason", "cannot open"))
        con.execute("UPDATE videos SET duration_s=?, fps=?, frames=?, width=?, height=?, "
                    "probe_note='' WHERE sha256=?",
                    (round(float(info["duration_s"]), 3), round(float(info["fps"]), 3),
                     int(info["frames"]), int(info["width"]), int(info["height"]),
                     row["sha256"]))
    except Exception as exc:  # noqa: BLE001 - a clip we cannot probe is still a clip
        con.execute("UPDATE videos SET probe_note=? WHERE sha256=?",
                    (str(exc)[:200], row["sha256"]))
    con.commit()
    return dict(con.execute("SELECT * FROM videos WHERE sha256=?", (row["sha256"],)).fetchone())


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------
def count(con: sqlite3.Connection) -> int:
    return int(con.execute("SELECT COUNT(*) FROM videos").fetchone()[0])


def _copies(con: sqlite3.Connection, sha: str) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT path, bytes, mtime FROM video_copies WHERE sha256=? ORDER BY path", (sha,))]


def _row(con: sqlite3.Connection, root: Path, row) -> dict:
    out = dict(row)
    out["copies"] = _copies(con, row["sha256"])
    out["duplicateOf"] = max(0, len(out["copies"]) - 1)  # extra paths holding these bytes
    # "Is this video still on disk" is a question about the CONTENT, so it is
    # answered from the copy list rather than from `path`. Overwrite a clip in
    # place and its path is still a file - but the bytes there now belong to a
    # different video, and the row that used to own them owns nothing.
    out["exists"] = any((Path(root) / c["path"]).is_file() for c in out["copies"])
    return out


def videos(con: sqlite3.Connection, root: Path) -> list[dict]:
    return [_row(con, root, r) for r in
            con.execute("SELECT * FROM videos ORDER BY added_at DESC, filename")]


def get(con: sqlite3.Connection, ident: str, root: Path | None = None) -> dict | None:
    """Resolve by library id, full sha256, or filename - the three things a
    URL, a trace subject and a person each naturally carry."""
    if not ident:
        return None
    row = con.execute(
        "SELECT * FROM videos WHERE id=? OR sha256=? OR filename=?",
        (ident, ident, ident)).fetchone()
    if row is None:
        # A trace records the file it ran on, which may since have been
        # renamed or been one of the extra copies. Fall back to the copy list.
        hit = con.execute(
            "SELECT sha256 FROM video_copies WHERE path=? OR path LIKE ?",
            (ident, f"%/{ident}")).fetchone()
        if hit:
            row = con.execute("SELECT * FROM videos WHERE sha256=?", (hit["sha256"],)).fetchone()
    if row is None:
        return None
    return _row(con, root if root is not None else Path("."), row)


def resolve(con: sqlite3.Connection, root: Path, ident: str) -> Path | None:
    """The file on disk for an identifier, or None. Confined to the library:
    a path that is not a registered copy is not served, whatever it says."""
    row = get(con, ident, root)
    if row is None:
        return None
    # Only registered copies: `path` is a preference, the copy list is the
    # record of which files actually hold this content.
    ordered = sorted((c["path"] for c in row["copies"]),
                     key=lambda p: (p != row["path"], _rank(p), p))
    for candidate in ordered:
        path = (Path(root) / candidate).resolve()
        if path.is_file():
            return path
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _print(rows: list[dict]) -> None:
    if not rows:
        print("the library is empty - run: python tools/debugweb/library.py scan")
        return
    print(f"{'id':<14}{'movement':<14}{'size':>9}  path")
    for r in rows:
        dup = f"  (+{r['duplicateOf']} copy)" if r["duplicateOf"] else ""
        print(f"{r['id']:<14}{(r['movement'] or '-'):<14}"
              f"{r['bytes'] / 1e6:>8.1f}M  {r['path']}{dup}")
    print(f"\n{len(rows)} distinct videos")


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parents[2]
    cmd = argv[0] if argv else "list"
    con = connect(root)
    if cmd == "scan":
        report = scan(con, root)
        print(f"added {len(report['added'])} · already known {len(report['alreadyKnown'])} "
              f"· unchanged {report['unchanged']} · {report['total']} distinct videos")
        for path in report["copiesDropped"]:
            print(f"  copy gone: {path}")
        return 0
    if cmd == "list":
        _print(videos(con, root))
        return 0
    if cmd == "add" and argv[1:]:
        for name in argv[1:]:
            src = Path(name)
            if not is_video(src):
                print(f"not a video: {name}")
                continue
            row = import_file(con, root, src)
            print(f"{'added' if row['isNew'] else 'already in the library as'} "
                  f"{row['id']}  {row['path']}")
        return 0
    if cmd == "show" and argv[1:]:
        row = get(con, argv[1], root)
        if row is None:
            print(f"no such video: {argv[1]}")
            return 1
        print(json.dumps(probe(con, root, con.execute(
            "SELECT * FROM videos WHERE sha256=?", (row["sha256"],)).fetchone()) | row,
            indent=2, default=str))
        return 0
    if cmd == "set" and len(argv) > 2:
        fields = dict(p.split("=", 1) for p in argv[2:] if "=" in p)
        try:
            row = update(con, argv[1], fields)
        except ValueError as exc:
            print(exc)
            return 1
        if row is None:
            print(f"no such video: {argv[1]}")
            return 1
        _print([row])
        return 0
    if cmd == "rm" and argv[1:]:
        out = forget(con, root, argv[1], "--delete-file" in argv)
        print(f"removed {out['id']} ({out['filename']})" if out else f"no such video: {argv[1]}")
        return 0 if out else 1
    print(__doc__.split("Stdlib only")[-1].split("\n", 1)[-1].rstrip())
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
