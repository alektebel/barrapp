"""Bring YouTube clips into the golden/session corpus, with attribution.

A wrapper over the same yt-dlp invocation scripts/scrape_calisthenics.py
proven in that script's runs (the 720p combined-format spec that YouTube
actually serves, merged to mp4 by ffmpeg), so an eval set can be rebuilt
from the same public sources rather than accumulated by hand.

Licensing is not decorative: the metadata row records source URL and
license so a clip in the corpus can always be defended. YouTube results
are filtered to Creative Commons unless --any-license is given, matching
the scrape script's policy.

Output follows data/videos/ conventions (the naming ingest.py parses:
YYYY-MM-DD__<exercise>__set<NN>.mp4) and appends a row to a metadata CSV
in the style of data/calisthenics/metadata.csv.

Usage:
  python -m barra.eval.fetch --url "https://youtube.com/watch?v=..." \
      --exercise pull_up --set 3
  python -m barra.eval.fetch --manifest urls.txt --exercise dip
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# The format spec proven against YouTube's current roster: at 720p the
# platform serves av01/webm for this pairing, so ext=mp4 filters exclude
# everything. bv*+ba merged to mp4 by ffmpeg always lands.
FORMAT = "bv*[height<=720]+ba/b[height<=720]/best"


def _ffprobe(path: Path) -> dict:
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate:format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60, check=True)
        info = json.loads(p.stdout)
        s = (info.get("streams") or [{}])[0]
        dur = float((info.get("format") or {}).get("duration") or 0.0)
        num, _, den = (s.get("r_frame_rate") or "0/1").partition("/")
        fps = float(num) / float(den) if den and float(den) else 0.0
        return {"width": s.get("width"), "height": s.get("height"),
                "duration": round(dur, 2), "fps": round(fps, 2)}
    except Exception:  # noqa: BLE001 - metadata is recorded, never gating
        return {}


def _yt_dlp(url: str, dest: Path, max_duration: int, max_filesize: str) -> tuple[bool, str]:
    """One download attempt; returns (ok, note)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part.mp4")
    cmd = ["yt-dlp", "--no-warnings", "--no-playlist",
           "-f", FORMAT,
           "--match-filter", f"duration < {max_duration}",
           "--max-filesize", max_filesize,
           "--merge-output-format", "mp4",
           "-o", str(tmp), url]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except FileNotFoundError:
        return False, ("yt-dlp not on PATH; install with `uv tool install yt-dlp` "
                       "(the scrape script has the same requirement)")
    except subprocess.TimeoutExpired:
        return False, "download timed out (600s)"
    if p.returncode != 0:
        return False, (p.stderr or "yt-dlp failed")[-200:].strip()
    # yt-dlp merges to the template name itself. With a .part.mp4 template
    # the merged file keeps that full name - the ".part." inside it is ours,
    # not yt-dlp's incomplete-download marker - so the template file IS the
    # result. Any sibling sharing the stem (stray fNNN fragments) also counts.
    stem = tmp.name[: -len(".mp4")] if tmp.name.endswith(".mp4") else tmp.stem
    candidates = [tmp] + sorted(dest.parent.glob(stem + "*"))
    src = next((c for c in candidates if c.exists() and c != dest
                and not c.name.endswith(".part.f")), None)
    if src is None and dest.exists():
        src = dest                      # merged straight onto the final name
    if src is None:
        return False, "yt-dlp produced no output file"
    if src.suffix != ".mp4":
        try:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                            str(dest)], capture_output=True, timeout=300, check=True)
            src.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            return False, f"transcode failed: {exc}"
    else:
        src.rename(dest)
    if not dest.exists() or dest.stat().st_size < 50_000:
        dest.unlink(missing_ok=True)
        return False, "output too small to be a real clip"
    return True, "ok"


def fetch(url: str, exercise: str, set_index: int, out_dir: Path,
          date: str | None = None, max_duration: int = 180,
          max_filesize: str = "120M") -> dict:
    """Download one URL, name it the ingest.py way, return the record."""
    date = date or _dt.date.today().isoformat()
    dest = out_dir / f"{date}__{exercise}__set{set_index:02d}.mp4"
    if dest.exists():
        return {"ok": False, "note": f"{dest.name} already exists", "file": str(dest)}
    ok, note = _yt_dlp(url, dest, max_duration, max_filesize)
    rec: dict = {"url": url, "file": str(dest), "ok": ok, "note": note}
    if ok:
        rec["probe"] = _ffprobe(dest)
    return rec


def append_metadata(csv_path: Path, rows: list[dict]) -> None:
    """One attribution row per fetched clip, calisthenics-metadata style."""
    if not rows:
        return
    fields = ["file", "source", "source_url", "license", "author",
              "width", "height", "duration", "fps", "title"]
    new = [r for r in rows if r.get("ok")]
    if not new:
        return
    write_header = not csv_path.exists()
    with csv_path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if write_header:
            w.writeheader()
        for r in new:
            probe = r.get("probe") or {}
            w.writerow({
                "file": r["file"], "source": "youtube",
                "source_url": r["url"],
                "license": r.get("license") or "see source_url",
                "author": r.get("author") or "",
                "width": probe.get("width", ""), "height": probe.get("height", ""),
                "duration": probe.get("duration", ""), "fps": probe.get("fps", ""),
                "title": r.get("title") or "",
            })


def _yt_info(url: str) -> dict:
    """Title + license for attribution; best-effort."""
    try:
        p = subprocess.run(
            ["yt-dlp", "--no-warnings", "--skip-download", "--print",
             "%(title)s\t%(license)s\t%(uploader)s", url],
            capture_output=True, text=True, timeout=120)
        if p.returncode == 0 and "\t" in p.stdout:
            title, license_, uploader = p.stdout.strip().split("\t", 2)
            return {"title": title, "license": license_ or None,
                    "author": uploader or ""}
    except Exception:  # noqa: BLE001
        pass
    return {}



def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", action="append", default=[],
                    help="YouTube URL; repeatable")
    ap.add_argument("--manifest", type=Path,
                    help="text file with one URL per line (# comments ok)")
    ap.add_argument("--exercise", required=True,
                    help="squat|pull_up|dip|muscle_up|push_up|... (catalog name)")
    ap.add_argument("--set", type=int, default=1, help="set index, default 1")
    ap.add_argument("--out", type=Path, default=None,
                    help="output dir; default data/videos (the session corpus)")
    ap.add_argument("--metadata", type=Path, default=None,
                    help="attribution CSV to append to; default <out>/metadata.csv")
    ap.add_argument("--date", default=None, help="override the session date prefix")
    ap.add_argument("--max-duration", type=int, default=180)
    ap.add_argument("--max-filesize", default="120M")
    args = ap.parse_args(argv)
    exercise = args.exercise.strip().lower().replace("_", "-").replace(" ", "-")

    urls = list(args.url)
    if args.manifest:
        urls += [ln.strip() for ln in args.manifest.read_text().splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
    if not urls:
        ap.error("give --url or --manifest")

    out_dir = args.out or ROOT / "data" / "videos"
    metadata = args.metadata or out_dir / "metadata.csv"

    records = []
    set_index = args.set
    for i, url in enumerate(urls):
        rec = fetch(url, exercise, set_index + i, out_dir,
                    date=args.date, max_duration=args.max_duration,
                    max_filesize=args.max_filesize)
        if rec["ok"]:
            rec.update(_yt_info(url))
        records.append(rec)
        print(f"{'ok  ' if rec['ok'] else 'FAIL'} {url} -> {rec['file']}  "
              f"{rec.get('note', '')[:100]}")

    append_metadata(metadata, records)
    print(f"\n{sum(1 for r in records if r['ok'])}/{len(records)} fetched; "
          f"attribution in {metadata}")
    return 0 if any(r["ok"] for r in records) else 1


if __name__ == "__main__":
    sys.exit(main())
