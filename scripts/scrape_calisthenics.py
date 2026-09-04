#!/usr/bin/env python3
"""Scrape openly-licensed calisthenics trick clips into data/calisthenics/.

Sources (no API keys needed):
  1. Wikimedia Commons API  - fully CC / public-domain, author + license recorded.
  2. YouTube Creative Commons filter (sp=EgIwAQ%3D%3D) via yt-dlp - only videos
     whose watch-page license is a Creative Commons variant are kept.

Output:
  data/calisthenics/videos/<trick>/<id>.mp4
  data/calisthenics/metadata.csv  (one row per clip, with attribution)

Usage:
  python scripts/scrape_calisthenics.py [--tricks muscle_up,pull_up] [--per-trick N]
      [--include-youtube/--no-youtube] [--include-commons/--no-commons]
      [--max-duration SEC] [--out DIR]

Defaults are deliberately small so a first run finishes in minutes.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = "barrapp-dataset/0.1 (research dataset builder; local use)"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"

# trick -> (youtube queries, commons queries: categories first, then search terms)
TRICKS: dict[str, dict] = {
    "muscle_up": {
        "yt": ["bar muscle up calisthenics", "ring muscle up calisthenics"],
        "commons": ["Category:Muscle-ups", "muscle-up exercise filetype:video"],
    },
    "pull_up": {
        "yt": ["pull up calisthenics form", "weighted pull up calisthenics"],
        "commons": ["Category:Pull-ups",
                    'incategory:Pull-ups filetype:video',
                    "pull-up exercise filetype:video"],
    },
    "dip": {
        "yt": ["bar dip calisthenics", "parallel bar dip form"],
        "commons": ["Category:Dips",
                    "dip exercise calisthenics filetype:video",
                    "parallel bars dip filetype:video"],
    },
    "push_up": {
        "yt": ["push up calisthenics form", "pseudo planche push up"],
        "commons": ["Category:Push-ups",
                    "incategory:Push-ups filetype:video",
                    "push-up exercise filetype:video"],
    },
    "squat": {
        "yt": ["pistol squat calisthenics", "bodyweight squat form"],
        "commons": ["Category:Squats",
                    "bodyweight squat filetype:video",
                    "pistol squat filetype:video"],
    },
    "handstand": {
        "yt": ["handstand hold calisthenics", "handstand push up calisthenics"],
        "commons": ["Category:Handstands",
                    "handstand filetype:video",
                    "handstand push-up filetype:video"],
    },
    "front_lever": {
        "yt": ["front lever calisthenics", "front lever tutorial"],
        "commons": ["front lever calisthenics filetype:video"],
    },
    "planche": {
        "yt": ["planche calisthenics", "tuck planche"],
        "commons": ["planche calisthenics filetype:video"],
    },
    "back_lever": {
        "yt": ["back lever calisthenics", "back lever tutorial progression"],
        "commons": ["back lever calisthenics filetype:video"],
    },
    "human_flag": {
        "yt": ["human flag calisthenics"],
        "commons": ["human flag calisthenics filetype:video"],
    },
}

VIDEO_EXTS = (".mp4", ".webm", ".ogv", ".ogg", ".mov", ".mkv")


def commons_get(params: dict, retries: int = 4) -> dict:
    url = COMMONS_API + "?" + urllib.parse.urlencode(params)
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # 429 rate-limit included; back off and retry
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"commons API failed after {retries} tries: {last}")


def commons_category_files(category: str, limit: int = 20) -> list[str]:
    """List File: titles in a Commons category (may include subcats)."""
    out: list[str] = []
    cont: dict = {}
    while len(out) < limit:
        time.sleep(1.5)  # stay under the Commons rate limit
        params = {
            "action": "query", "format": "json",
            "generator": "categorymembers", "gcmtitle": category,
            "gcmtype": "file", "gcmlimit": min(50, limit - len(out)),
            **cont,
        }
        d = commons_get(params)
        pages = d.get("query", {}).get("pages", {})
        for p in pages.values():
            t = p.get("title", "")
            if t.lower().endswith(VIDEO_EXTS):
                out.append(t)
        if "continue" in d and len(out) < limit:
            cont = d["continue"]
        else:
            break
    return out


def commons_search_files(query: str, limit: int = 10) -> list[str]:
    q = query if "filetype:" in query else query + " filetype:video"
    params = {
        "action": "query", "format": "json",
        "generator": "search", "gsrsearch": q,
        "gsrlimit": limit, "gsrnamespace": 6,
    }
    time.sleep(1.5)  # stay under the Commons rate limit
    d = commons_get(params)
    pages = d.get("query", {}).get("pages", {})
    return [p["title"] for p in pages.values()
            if p.get("title", "").lower().endswith(VIDEO_EXTS)]


def commons_file_info(titles: list[str]) -> list[dict]:
    """Resolve direct URLs + author + license for File: titles (batched)."""
    infos: list[dict] = []
    for i in range(0, len(titles), 20):
        batch = titles[i:i + 20]
        params = {
            "action": "query", "format": "json",
            "titles": "|".join(batch), "prop": "imageinfo",
            "iiprop": "url|user|extmetadata|size|mime",
        }
        d = commons_get(params)
        for p in d.get("query", {}).get("pages", {}).values():
            if "missing" in p:
                continue
            ii = (p.get("imageinfo") or [{}])[0]
            url = ii.get("url", "")
            if not url:
                continue
            meta = ii.get("extmetadata", {})
            lic = (meta.get("LicenseShortName") or {}).get("value", "")
            artist = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", ""))
            infos.append({
                "title": p.get("title", ""),
                "url": url, "user": ii.get("user", ""),
                "artist": artist.strip()[:200], "license": lic or "CC (see page)",
                "page": ii.get("descriptionurl", ""),
                "width": ii.get("width", ""), "height": ii.get("height", ""),
                "mime": ii.get("mime", ""),
            })
    return infos


def yt_search_ids(query: str, n: int) -> list[str]:
    """YouTube search restricted to Creative Commons (sp=EgIwAQ%3D%3D)."""
    q = urllib.parse.quote_plus(query)
    url = f"https://www.youtube.com/results?search_query={q}&sp=EgIwAQ%253D%253D"
    cmd = ["yt-dlp", "--flat-playlist", "--no-warnings",
           "--print", "%(id)s", f"{url}"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  [yt] search failed for {query!r}: {e}", file=sys.stderr)
        return []
    ids = [l.strip() for l in p.stdout.splitlines() if l.strip()]
    return ids[:n]


def yt_info(video_id: str) -> dict | None:
    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = ["yt-dlp", "--no-warnings", "--skip-download",
           "--dump-single-json", url]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if p.returncode != 0 or not p.stdout.strip():
            return None
        return json.loads(p.stdout.strip())
    except Exception as e:
        print(f"  [yt] info failed for {video_id}: {e}", file=sys.stderr)
        return None


def is_cc_license(info: dict) -> bool:
    lic = (info.get("license") or "").lower()
    return "creative commons" in lic or "cc by" in lic or lic.startswith("cc")


def normalize_video(path: Path) -> None:
    """Transcode to 720p H.264 mp4 so the dataset is uniform and small.
    No-op if already <=720p avc mp4."""
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name,height",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=60)
        parts = (p.stdout or "").strip().split(",")
        codec, height = (parts + ["", ""])[:2]
        if codec.strip() == "h264" and height.strip().isdigit() and int(height) <= 720:
            return
        tmp = path.with_suffix(".norm.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
             "-vf", "scale=-2:min(ih,720)", "-c:v", "libx264",
             "-preset", "fast", "-crf", "23", "-c:a", "aac", "-movflags",
             "+faststart", str(tmp)],
            capture_output=True, timeout=900, check=True)
        tmp.replace(path)
    except Exception as e:
        print(f"  [norm] skip {path.name}: {str(e)[:120]}", file=sys.stderr)


def download_direct(url: str, dest: Path, timeout: int = 600) -> bool:
    """Plain HTTP download for direct media files (e.g. upload.wikimedia.org)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part" + dest.suffix)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, length=1024 * 256)
    except Exception as e:
        print(f"  [dl] direct failed ({url[:80]}): {str(e)[:150]}", file=sys.stderr)
        tmp.unlink(missing_ok=True)
        return False
    if not tmp.exists() or tmp.stat().st_size < 50_000:
        tmp.unlink(missing_ok=True)
        return False
    tmp.rename(dest)
    return True


def download(url: str, dest: Path, max_duration: int = 180) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part.mp4")
    cmd = ["yt-dlp", "--no-warnings", "--no-playlist",
           "-f", "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/b[height<=720]/best[height<=720]/best",
           "--match-filter", f"duration < {max_duration}",
           "--max-filesize", "120M",
           "--merge-output-format", "mp4",
           "-o", str(tmp), url]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        print(f"  [dl] TIMEOUT {url}", file=sys.stderr)
        return False
    if p.returncode != 0:
        print(f"  [dl] skip ({url[:80]}): {(p.stderr or '')[-200:]}", file=sys.stderr)
        return False
    # yt-dlp may append extensions; find the actual file
    candidates = [tmp] + list(dest.parent.glob(tmp.stem + "*"))
    src = next((c for c in candidates if c.exists()), None)
    if src is None:
        print(f"  [dl] no output for {url[:80]}", file=sys.stderr)
        return False
    if src.suffix != ".mp4":
        try:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                            "-i", str(src), str(dest)],
                           capture_output=True, timeout=300, check=True)
            src.unlink(missing_ok=True)
        except Exception as e:
            print(f"  [dl] transcode failed {src}: {e}", file=sys.stderr)
            return False
    else:
        src.rename(dest)
    return dest.exists() and dest.stat().st_size > 50_000


def probe(path: Path) -> dict:
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate,duration",
             "-show_entries", "format=duration", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60)
        d = json.loads(p.stdout or "{}")
        s = (d.get("streams") or [{}])[0]
        fps = s.get("r_frame_rate", "")
        if "/" in fps:
            a, b = fps.split("/", 1)
            fps = float(a) / float(b) if float(b) else ""
        return {"width": s.get("width", ""), "height": s.get("height", ""),
                "fps": round(float(fps), 2) if fps else "",
                "duration": round(float((d.get("format") or {}).get("duration")
                                        or s.get("duration") or 0), 1)}
    except Exception:
        return {}


def slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", s).strip("_")[:60]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tricks", default=",".join(TRICKS),
                    help="comma-separated trick names")
    ap.add_argument("--per-trick", type=int, default=4)
    ap.add_argument("--max-duration", type=int, default=180)
    ap.add_argument("--out", default="data/calisthenics")
    ap.add_argument("--include-youtube", dest="youtube", action="store_true", default=True)
    ap.add_argument("--no-youtube", dest="youtube", action="store_false")
    ap.add_argument("--include-commons", dest="commons", action="store_true", default=True)
    ap.add_argument("--no-commons", dest="commons", action="store_false")
    a = ap.parse_args()

    tricks = [t.strip() for t in a.tricks.split(",") if t.strip() in TRICKS]
    out = Path(a.out)
    vdir = out / "videos"
    meta_path = out / "metadata.csv"
    existing: set[str] = set()
    rows: list[dict] = []
    if meta_path.exists():
        with open(meta_path) as f:
            for r in csv.DictReader(f):
                existing.add(r.get("source_url", ""))
                rows.append(r)

    def add_row(row: dict) -> bool:
        if row["source_url"] in existing:
            print(f"  skip (already have): {row['source_url'][:80]}")
            return False
        existing.add(row["source_url"])
        rows.append(row)
        return True

    for trick in tricks:
        print(f"== {trick} ==")
        got = sum(1 for r in rows if r.get("trick") == trick)
        cfg = TRICKS[trick]

        # --- Wikimedia Commons ---
        if a.commons and got < a.per_trick:
            titles: list[str] = []
            for cat in cfg["commons"]:
                try:
                    found = (commons_category_files(cat, limit=a.per_trick) if cat.startswith("Category:")
                             else commons_search_files(cat, limit=a.per_trick))
                    print(f"  [commons] {cat}: {len(found)} candidates")
                    titles.extend(found)
                except Exception as e:
                    print(f"  [commons] {cat} failed: {e}", file=sys.stderr)
            for info in commons_file_info(list(dict.fromkeys(titles))):
                if got >= a.per_trick:
                    break
                fid = slug(info["title"].removeprefix("File:").rsplit(".", 1)[0])
                dest = vdir / trick / f"commons_{fid}.mp4"
                if dest.exists():
                    got += 1
                    continue
                print(f"  [commons] dl {info['title'][:70]}")
                time.sleep(1.5)  # rate-limit courtesy
                if download_direct(info["url"], dest):
                    normalize_video(dest)
                    pr = probe(dest)
                    if add_row({"file": str(dest.relative_to(out)), "trick": trick,
                             "source": "wikimedia_commons", "source_url": info["url"],
                             "page_url": info["page"], "license": info["license"],
                             "author": info["user"] or info["artist"],
                             **{k: pr.get(k, "") for k in ("width", "height", "duration", "fps")},
                             "title": info["title"]}):
                        got += 1

        # --- YouTube Creative Commons ---
        if a.youtube and got < a.per_trick:
            for q in cfg["yt"]:
                if got >= a.per_trick:
                    break
                ids = yt_search_ids(q, a.per_trick - got + 2)
                print(f"  [yt] {q!r}: {len(ids)} CC-search hits")
                for vid in ids:
                    if got >= a.per_trick:
                        break
                    info = yt_info(vid)
                    if not info:
                        continue
                    if not is_cc_license(info):
                        print(f"  [yt] skip non-CC ({info.get('license')}): {vid}")
                        continue
                    if (info.get("duration") or 0) > a.max_duration:
                        print(f"  [yt] skip long ({info.get('duration')}s): {vid}")
                        continue
                    page = info.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}"
                    if page in existing:
                        print(f"  [yt] skip duplicate: {vid}")
                        continue
                    dest = vdir / trick / f"youtube_{vid}.mp4"
                    if dest.exists():
                        got += 1
                        continue
                    print(f"  [yt] dl {vid} {(info.get('title') or '')[:60]}")
                    if download(page, dest, a.max_duration):
                        pr = probe(dest)
                        if add_row({"file": str(dest.relative_to(out)), "trick": trick,
                                 "source": "youtube_cc",
                                 "source_url": page,
                                 "page_url": page,
                                 "license": info.get("license", ""),
                                 "author": info.get("uploader", "") or info.get("channel", ""),
                                 **{k: pr.get(k) if pr.get(k, '') != '' else info.get(
                                     {'width': 'width', 'height': 'height',
                                      'duration': 'duration', 'fps': 'fps'}[k], '')
                                     for k in ("width", "height", "duration", "fps")},
                                 "title": info.get("title", "")}):
                            got += 1
        print(f"  -> {trick}: {got} clips total")

    with open(meta_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "trick", "source", "source_url",
                                          "page_url", "license", "author",
                                          "width", "height", "duration", "fps", "title"])
        w.writeheader()
        w.writerows(rows)
    print(f"\nDone: {len(rows)} clips, {len([r for r in rows if (out / r['file']).exists()])} files on disk -> {meta_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
