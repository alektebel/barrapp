#!/usr/bin/env python
"""Turn filmed sets into per-rep fault ground truth, cheaply.

Every fault number this repo can currently quote is measured against a vision
model's opinion, because that is the only labelled fault data that exists. That
is enough to find the layer's big structural problems - it fires four times more
often than there are faults to find - and not enough to fix them: twenty of the
thirty-two measurable rules have never seen a single instance of the fault they
exist to catch, so their recall is not low, it is unknown.

The way out is not more scraped tutorials. It is filming the fault ON PURPOSE,
because then the label exists at capture time: a set performed with a
deliberately shallow squat is labelled `shallow_depth` before anyone annotates
anything. That is stronger ground truth than any model's read, and it costs a
CSV row.

This script closes the gap between that CSV row and a usable label:

  1. `--extract` reads the capture manifest, segments each clip into reps with
     the SAME code the pipeline uses, and pulls frames from each rep.
  2. `--serve` opens a review page on localhost showing those frames rep by
     rep, with the intended fault pre-marked. You confirm or correct per rep -
     because an intended fault is what you meant to do, not necessarily what
     every rep shows.
  3. What you save lands in `out/fault-labels-human/`, which `fault_eval.py`
     prefers over the model's labels wherever it exists.

The per-rep grain matters. A fault happens in a rep, not in a clip, and asking
a model "what is wrong in this twenty-second video" is a large part of why
three independent models could not agree on an answer.

Usage:
  python scripts/label_reps.py --extract          # segment + pull frames
  python scripts/label_reps.py --serve            # review at localhost:8765
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import secrets
import shutil
import subprocess
import sys
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))

from barra.posecache import load as load_cached, load_or_estimate  # noqa: E402
from barra.rules import RULES  # noqa: E402
from barra.skills import MEASURED, SKILLS  # noqa: E402

DATASET = ROOT / "data" / "calisthenics"
MANIFEST = DATASET / "capture.csv"
# The scrape's own index: one row per downloaded corpus clip. Not a capture
# manifest, but the only list of every video the corpus holds.
LABELS = DATASET / "labels.csv"
REVIEW = ROOT / "out" / "rep-review"
HUMAN = ROOT / "out" / "fault-labels-human"
# The movement a person settled on goes to the corpus' existing adjudication
# sheet rather than a new file of its own, because that is already the only
# reference allowed to overrule a clip's directory - classify_eval reads it,
# label_source_eval scores against it, and a second store would silently
# compete with it.
ADJUDICATED = DATASET / "labels-adjudicated.csv"
# `reason` is why a person changed the label. A relabel without one is a
# second opinion; a relabel with one is evidence, and the difference matters
# when the sheet is the reference every accuracy in the repo is scored against.
ADJUDICATED_FIELDS = ["clip", "directory", "vision", "model", "verdict",
                      "reason", "description"]
FRAMES_PER_REP = 6
# A clip of a movement barra cannot segment still gets frames, just spread
# over the whole clip instead of over a rep.
FRAMES_PER_CLIP = 8
# The review page shows one still full-bleed, so a 360px frame would be
# upscaled to mush. 720 holds up in the viewer and stays cheap per frame.
FRAME_WIDTH = 720
UNCLEAR = "unclear"

MANIFEST_FIELDS = ["file", "movement", "intended_fault", "severity",
                   "subject", "angle", "note"]

# The review page commits a verdict to these two places; it shows them in a
# quiet footer so the reviewer always knows where their attention lands.
DEST_CSV = "data/calisthenics/labels-adjudicated.csv"
DEST_JSON = "out/fault-labels-human/"

# The app's own fonts, copied beside the page so the tool wears the product's
# type without a CDN. Kept here rather than inlined: the page stays an
# editable string constant, and the server already serves this directory.
FONT_FILES = [
    "barlow_condensed_bold.ttf", "barlow_condensed_black.ttf",
    "jetbrains_mono_regular.ttf", "jetbrains_mono_semibold.ttf",
    "inter_regular.ttf", "inter_semibold.ttf",
]


def ensure_fonts() -> None:
    """Put the app's typefaces next to the review page.

    Best-effort by design: a missing font is a fallback stack, never a reason
    for the labelling tool to refuse to start.
    """
    src = ROOT / "app" / "src" / "main" / "res" / "font"
    dest = REVIEW / "fonts"
    try:
        dest.mkdir(parents=True, exist_ok=True)
        for name in FONT_FILES:
            found = src / name
            if found.exists():
                shutil.copyfile(found, dest / name)
    except OSError:
        pass


def adjudication_stats() -> dict:
    """How much of the corpus sheet carries a human verdict.

    The page's progress bar counts these, not the eight clips in this review
    set: 92 rows and 0 verdicts is the whole job, and hiding it behind a
    session counter is how the job stayed invisible.
    """
    answered = total = 0
    if ADJUDICATED.exists():
        with ADJUDICATED.open() as f:
            for row in csv.DictReader(f):
                if not (row.get("clip") or "").strip():
                    continue
                total += 1
                if (row.get("verdict") or "").strip():
                    answered += 1
    return {"answered": answered, "total": total}


def adjudicated_clips() -> set[str]:
    """Clip names the corpus sheet already holds a settled movement for."""
    out: set[str] = set()
    if ADJUDICATED.exists():
        with ADJUDICATED.open() as f:
            for row in csv.DictReader(f):
                if (row.get("verdict") or "").strip() and (row.get("clip") or "").strip():
                    out.add(Path(row["clip"]).name)
    return out


def human_labels() -> dict[str, dict]:
    """Every saved fault label, keyed by clip stem, for reopening a clip."""
    out: dict[str, dict] = {}
    if HUMAN.exists():
        for path in HUMAN.glob("*.json"):
            try:
                out[path.stem] = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
    return out


def read_manifest() -> list[dict]:
    if not MANIFEST.exists():
        return []
    with MANIFEST.open() as f:
        return [r for r in csv.DictReader(f) if (r.get("file") or "").strip()]


def write_template() -> None:
    """A manifest that documents itself, so filming does not need this file open."""
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        w.writeheader()
        w.writerow({
            "file": "videos/squat/session01_shallow_a.mp4",
            "movement": "squat",
            "intended_fault": "shallow_depth",
            "severity": "major",
            "subject": "diego",
            "angle": "sagittal-left",
            "note": "deliberately stopping above parallel",
        })
        w.writerow({
            "file": "videos/squat/session01_clean_a.mp4",
            "movement": "squat",
            "intended_fault": "",
            "severity": "",
            "subject": "diego",
            "angle": "oblique-45",
            "note": "clean reps, negative example",
        })
    print(f"wrote a template manifest -> {MANIFEST}")


def rep_windows(video: Path, movement: str) -> list[tuple[float, float]]:
    """Rep boundaries from the real pipeline, so labels and measurements align.

    Using the pipeline's own segmenter is the point: a label attached to a rep
    the measurement code does not agree exists cannot be compared with anything
    that code produces.
    """
    from process import analyze_clip  # noqa: PLC0415

    if load_cached(video) is None:
        raise LookupError(f"no cached keypoints for {video.name} - run "
                          "scripts/extract_keypoints.py first")
    pose = load_or_estimate(video, fresh=False, write_cache=False)
    payload = analyze_clip(video, exercise=movement, pose=pose)
    out = []
    for rep in payload.get("reps", []):
        try:
            out.append((float(rep["startS"]), float(rep["endS"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def clip_seconds(video: Path) -> float:
    """The clip's duration, for spreading frames across a hold.

    ffprobe would be the obvious tool and is deliberately not used: every
    other path in this script needs ffmpeg only, and adding a second binary to
    the requirements for one number is how a labelling tool stops running on
    the machine that needs it.
    """
    try:
        import cv2

        cap = cv2.VideoCapture(str(video))
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        cap.release()
        if fps > 0 and frames > 0:
            return float(frames) / float(fps)
    except Exception:  # noqa: BLE001
        pass
    return 0.0


def movement_vocabulary() -> list[dict]:
    """Every skill in the graph, for the review page's movement picker.

    Sorted by family and then by name so the picker reads like the skill tree
    rather than like a hash order, and carrying `measurable`/`hasRules` so the
    page can say why a given movement offers no fault questions.
    """
    return [
        {"id": k, "name": sk.name, "family": sk.family,
         "measurable": k in MEASURED, "hasRules": k in RULES}
        for k, sk in sorted(SKILLS.items(),
                            key=lambda kv: (kv[1].family, kv[1].name))
    ]


def record_movement(clip: str, verdict: str, reason: str = "",
                    declared: str = "") -> bool:
    """Write a person's movement verdict into the corpus adjudication sheet.

    This is the only reference allowed to overrule a clip's directory, and
    only a person may write it - not the vision pass, and not the classifier
    being scored, which would be marking its own homework. So it is written
    here, from the review UI, where a person is the one answering.

    Upserts by clip name and rewrites the file. The sheet is under a hundred
    rows; a read-modify-write is honest about the fact that two reviewers
    running at once would race, which a partial append would hide.
    """
    verdict = (verdict or "").strip()
    if not clip or not verdict or verdict == UNCLEAR:
        return False
    reason = (reason or "").strip()[:500]
    rows: list[dict] = []
    if ADJUDICATED.exists():
        with ADJUDICATED.open() as f:
            rows = list(csv.DictReader(f))
    for row in rows:
        if Path(row.get("clip") or "").name == Path(clip).name:
            row["verdict"] = verdict
            row["reason"] = reason
            # `description` is the clip's own description, written by the
            # vision pass, and it is the evidence that made this clip worth
            # settling. The reason a person disagreed with it belongs beside
            # it, never on top of it.
            break
    else:
        rows.append({"clip": Path(clip).name,
                     # The label the clip arrived with. For a corpus clip that
                     # is the directory a scraper chose; for a filmed one it is
                     # what the capture manifest declared. Either way it is
                     # what `verdict` is a correction OF, and without it the
                     # reason has nothing to point at.
                     "directory": declared, "vision": "", "model": "",
                     "verdict": verdict, "reason": reason, "description": ""})
    ADJUDICATED.parent.mkdir(parents=True, exist_ok=True)
    with ADJUDICATED.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ADJUDICATED_FIELDS,
                           extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in ADJUDICATED_FIELDS})
    return True


def extract_frames(video: Path, start: float, end: float, dest: Path,
                   n: int = FRAMES_PER_REP) -> list[str]:
    dest.mkdir(parents=True, exist_ok=True)
    span = max(0.05, end - start)
    names = []
    for i in range(n):
        t = round(start + span * (i + 0.5) / n, 2)
        out = dest / f"{i}.jpg"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t),
                 "-i", str(video), "-frames:v", "1",
                 "-vf", f"scale={FRAME_WIDTH}:-2",
                 "-q:v", "4", str(out)],
                capture_output=True, timeout=60, check=True)
        except Exception:  # noqa: BLE001 - a missing frame is not fatal
            continue
        if out.exists():
            names.append(out.name)
    return names


def corpus_rows() -> list[dict]:
    """Every clip in `labels.csv`, shaped like a capture manifest row.

    The scrape has no intended fault, subject or angle to carry - inventing
    them would put a fiction in front of the reviewer - so those stay empty and
    the trick the source claimed travels in `note`, where the person can see
    what they are correcting.
    """
    out: list[dict] = []
    if not LABELS.exists():
        return out
    with LABELS.open() as f:
        for row in csv.DictReader(f):
            path = (row.get("file") or "").strip()
            if not path:
                continue
            claimed = (row.get("claimed_trick") or "").strip()
            detected = (row.get("detected_trick") or "").strip()
            note = f"corpus claim: {claimed or '?'}"
            if detected and detected != claimed:
                note += f" (the vision pass read {detected})"
            out.append({"file": path, "movement": claimed, "intended_fault": "",
                        "severity": "", "subject": "", "angle": "", "note": note})
    return out


def extract(include_corpus: bool = False, include_unknown: bool = False,
            limit: int = 0) -> int:
    rows = read_manifest()
    if include_corpus:
        rows = corpus_rows() + rows
    # The capture manifest is the more specific row, so it wins a tie; the
    # corpus list only ever adds clips the manifest does not already name.
    seen: set[str] = set()
    unique: list[dict] = []
    for row in rows:
        key = (row.get("file") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(row)
    rows = unique
    if limit:
        rows = rows[:limit]
    if not rows:
        print(f"no manifest at {MANIFEST}", file=sys.stderr)
        write_template()
        return 1
    index = []
    for row in rows:
        video = DATASET / row["file"]
        movement = (row.get("movement") or video.parent.name).strip()
        if not video.exists():
            print(f"  [skip] {row['file']}: not on disk")
            continue
        # The vocabulary is the whole skill graph, not the ten movements that
        # happen to have fault rules. A clip of a back lever is still a clip
        # whose MOVEMENT a person can confirm, and that confirmation is ground
        # truth the classifier has never had - refusing the clip because its
        # faults cannot be labelled threw away the easy half of the job.
        #
        # A word the graph does not know - `deadlift`, `handstand`, `planche` -
        # is exactly the clip the classifier needs a human read on. With
        # `include_unknown` it is kept for movement-only review instead of
        # skipped, and the picker starts unselected until a person chooses.
        if movement not in SKILLS and not include_unknown:
            near = [k for k in SKILLS if movement and movement in k]
            hint = f" - did you mean {near[0]!r}?" if near else ""
            print(f"  [skip] {video.name}: {movement!r} is not a skill{hint}")
            continue

        # Two kinds of clip. Only what barra can segment gets per-rep
        # questions; everything else is reviewed whole, which is all a hold
        # ever was - see barra/holds.py, "a lever and a planche are not a set
        # of repetitions". Conflating the two is what made this tool refuse
        # 78 of the 88 skills.
        reps: list[tuple[float, float]] = []
        kind = "reps" if movement in MEASURED else "clip"
        if kind == "reps":
            try:
                reps = rep_windows(video, movement)
            except Exception as exc:  # noqa: BLE001
                print(f"  [warn] {video.name}: {type(exc).__name__} "
                      f"{str(exc)[:70]} - reviewing whole")
                kind = "clip"
            if kind == "reps" and not reps:
                print(f"  [warn] {video.name}: the segmenter found no reps - "
                      "reviewing whole")
                kind = "clip"

        stem = video.stem
        entry = {
            "file": row["file"], "clip": video.name, "movement": movement,
            "kind": kind,
            "declared": movement,
            "hasRules": movement in RULES,
            "measurable": movement in MEASURED,
            "intendedFault": (row.get("intended_fault") or "").strip(),
            "severity": (row.get("severity") or "").strip(),
            "subject": (row.get("subject") or "").strip(),
            "angle": (row.get("angle") or "").strip(),
            "note": (row.get("note") or "").strip(),
            "vocabulary": [
                {"name": r.id.split(".", 1)[1], "label": r.name,
                 "observable": r.observable, "correction": r.correction}
                for r in RULES.get(movement, ())],
            "reps": [],
        }
        if kind == "reps":
            for i, (a, b) in enumerate(reps):
                frames = extract_frames(video, a, b, REVIEW / stem / f"rep{i}")
                entry["reps"].append(
                    {"index": i, "startS": round(a, 2), "endS": round(b, 2),
                     "frames": [f"{stem}/rep{i}/{f}" for f in frames]})
        else:
            span = clip_seconds(video)
            frames = extract_frames(video, 0.0, span, REVIEW / stem / "clip",
                                    n=FRAMES_PER_CLIP)
            entry["clipFrames"] = [f"{stem}/clip/{f}" for f in frames]
            entry["durationS"] = round(span, 2)
        index.append(entry)
        if kind == "reps":
            print(f"  {video.name}: {len(reps)} reps, "
                  f"intended={entry['intendedFault'] or 'clean'}")
        else:
            why = ("no fault rules" if not entry["hasRules"]
                   else "not segmentable")
            print(f"  {video.name}: whole-clip review "
                  f"({movement}, {why})")
    REVIEW.mkdir(parents=True, exist_ok=True)
    ensure_fonts()
    payload = {"movements": movement_vocabulary(), "clips": index,
               "stats": adjudication_stats(),
               "destinations": {"csv": DEST_CSV, "json": DEST_JSON}}
    (REVIEW / "index.json").write_text(json.dumps(payload, indent=1))
    (REVIEW / "review.html").write_text(PAGE)
    print(f"\n{len(index)} clips ready -> {REVIEW}/index.json")
    print("now run: python scripts/label_reps.py --serve")
    return 0


class Handler(SimpleHTTPRequestHandler):
    """Static files out of the review directory, plus one save endpoint.

    When credentials are configured, every request - the page, each frame it
    loads, the save - sits behind HTTP Basic. There are no accounts and no
    sessions here: one pair of credentials, terminated over TLS by whatever
    reverse proxy or tunnel fronts this, is the entire security model. The
    check is here rather than only at the proxy so the tool is never naked
    even when someone runs it directly on a public interface.
    """

    def _authorized(self) -> bool:
        creds = getattr(self.server, "credentials", None)
        if not creds:
            return True
        header = self.headers.get("Authorization", "")
        user = password = ""
        if header.startswith("Basic "):
            try:
                raw = base64.b64decode(header[6:].strip()).decode("utf-8")
                user, _, password = raw.partition(":")
            except (ValueError, UnicodeDecodeError):
                pass
        if (secrets.compare_digest(user, creds[0])
                and secrets.compare_digest(password, creds[1])):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate",
                         'Basic realm="Rep review", charset="UTF-8"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def do_GET(self) -> None:  # noqa: N802 - http.server's naming
        if not self._authorized():
            return
        super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802
        if not self._authorized():
            return
        super().do_HEAD()

    def do_POST(self) -> None:  # noqa: N802 - http.server's naming
        if not self._authorized():
            return
        if self.path != "/save":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_error(400, "not json")
            return
        clip = Path(payload.get("clip") or "").name
        if not clip:
            self.send_error(400, "no clip")
            return
        # The movement verdict goes to the corpus sheet whatever kind of clip
        # this is - it is the half of the answer that exists for all 88
        # skills, and the only half that exists for a hold.
        moved = record_movement(clip, payload.get("movement") or "",
                                payload.get("movementReason") or "",
                                payload.get("declared") or "")

        HUMAN.mkdir(parents=True, exist_ok=True)
        # Clip-level roll-up beside the per-rep detail: a fault is present on
        # the clip if any rep shows it, which is the question fault_eval asks.
        reps = payload.get("reps") or []
        names = {n for rep in reps for n in (rep.get("faults") or {})}
        rolled = {}
        for n in names:
            says = [(rep.get("faults") or {}).get(n) for rep in reps]
            rolled[n] = ("present" if "present" in says
                         else "absent" if "absent" in says else "unclear")
        payload["faults"] = rolled
        payload["source"] = "human"
        (HUMAN / f"{Path(clip).stem}.json").write_text(json.dumps(payload, indent=1))
        body = json.dumps({"ok": True, "faults": rolled,
                           "movementRecorded": moved,
                           "movement": payload.get("movement") or "",
                           "progress": adjudication_stats()}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a) -> None:  # keep the console for real output
        pass


def serve(port: int, host: str = "127.0.0.1",
          credentials: tuple[str, str] | None = None) -> int:
    if not (REVIEW / "index.json").exists():
        print("nothing extracted yet - run --extract first", file=sys.stderr)
        return 1
    (REVIEW / "review.html").write_text(PAGE)
    ensure_fonts()
    # Reopening a clip must show the answer that was already committed, not a
    # blank sheet with the previous verdict invisible behind it.
    saved = human_labels()
    settled = adjudicated_clips()
    data = json.loads((REVIEW / "index.json").read_text())
    clips = data["clips"] if isinstance(data, dict) else data
    for entry in clips:
        stem = Path(entry.get("clip") or "").stem
        if stem in saved:
            entry["saved"] = saved[stem]
            entry["done"] = True
        elif Path(entry.get("clip") or "").name in settled:
            entry["done"] = True
    if isinstance(data, dict):
        data["stats"] = adjudication_stats()
        data["destinations"] = {"csv": DEST_CSV, "json": DEST_JSON}
        (REVIEW / "index.json").write_text(json.dumps(data, indent=1))
    existing = set(saved)
    by_rep = sum(1 for c in clips if c.get("kind", "reps") == "reps")
    print(f"{len(clips)} clips, {len(existing)} already labelled "
          f"({by_rep} with per-rep faults, {len(clips) - by_rep} movement only)")
    # Bind before printing the URL or opening a browser: a port that cannot be
    # bound - 876 needs root, 8765 does not - must fail at once with a
    # sentence, not a half-truth and a traceback.
    handler = partial(Handler, directory=str(REVIEW))
    try:
        httpd = ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        print(f"cannot bind {host}:{port} ({exc}) - try --port 8765",
              file=sys.stderr)
        return 1
    httpd.credentials = credentials
    url = f"http://{host if host not in ('0.0.0.0', '::') else '127.0.0.1'}:{port}/review.html"
    print(f"review at {url}   (ctrl-c to stop)")
    if host in ("0.0.0.0", "::"):
        print(f"reachable from other devices on this port; "
              f"put TLS in front before exposing it")
    if credentials:
        print(f"HTTP Basic auth on - user {credentials[0]!r}")
    else:
        print("NO auth - keep this on localhost or bind it to a private network")
    if host in ("127.0.0.1", "localhost"):
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - a headless host is fine
            pass
    with httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print(f"\nlabels in {HUMAN}")
    return 0


PAGE = r'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rep review</title>
<link rel="icon" href="data:,">
<style>
@font-face{font-family:Barlow;font-style:normal;font-weight:700;src:url("fonts/barlow_condensed_bold.ttf") format("truetype")}
@font-face{font-family:Barlow;font-style:normal;font-weight:900;src:url("fonts/barlow_condensed_black.ttf") format("truetype")}
@font-face{font-family:"JetBrains Mono";font-style:normal;font-weight:400;src:url("fonts/jetbrains_mono_regular.ttf") format("truetype")}
@font-face{font-family:"JetBrains Mono";font-style:normal;font-weight:600;src:url("fonts/jetbrains_mono_semibold.ttf") format("truetype")}
@font-face{font-family:Inter;font-style:normal;font-weight:400;src:url("fonts/inter_regular.ttf") format("truetype")}
@font-face{font-family:Inter;font-style:normal;font-weight:600;src:url("fonts/inter_semibold.ttf") format("truetype")}
:root{
  --bg:#090D16;--bg2:#0B0F19;--panel:#0F1521;--card:#141C2B;--card2:#1A2233;
  --line:#1E2A3D;--line2:#27354A;
  --ink:#E8EEF7;--muted:#8794A8;--faint:#5B6879;
  --teal:#2DD4BF;--teal-d:#0E3A38;--teal-b:rgba(45,212,191,.45);
  --amber:#F5A524;--amber-d:#3A2A10;--amber-b:rgba(245,165,36,.5);
  --rose:#F43F5E;--rose-d:#3A1420;--rose-b:rgba(244,63,94,.5);
  --violet:#7C5DFA;
  --ui:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  --mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --disp:Barlow,"Arial Narrow",var(--ui);
}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--ui);
  font-size:13px;line-height:1.45;-webkit-font-smoothing:antialiased;
  display:flex;flex-direction:column;height:100vh;overflow:hidden}
button{font-family:inherit;color:inherit;cursor:pointer}
input,textarea,select{font-family:inherit;color:inherit}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-thumb{background:#1c2636;border-radius:6px;border:2px solid var(--bg)}
::-webkit-scrollbar-track{background:transparent}
.eyebrow{font-family:var(--mono);font-size:9.5px;letter-spacing:.18em;text-transform:uppercase;color:var(--faint)}

/* top bar */
.topbar{flex:none;display:flex;align-items:center;gap:26px;padding:12px 20px;
  background:var(--bg2);border-bottom:1px solid var(--line)}
.brand{min-width:300px}
.brand .row1{display:flex;align-items:center;gap:10px}
.brand h1{margin:0;font-family:var(--disp);font-weight:900;font-size:26px;line-height:1;letter-spacing:.01em}
.badge{font-family:var(--mono);font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--teal);border:1px solid var(--teal-b);background:rgba(45,212,191,.07);
  padding:3px 8px;border-radius:999px;white-space:nowrap}
.clipline{margin-top:5px;font-family:var(--mono);font-size:11px;color:var(--faint);display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.clipline select{appearance:none;background:transparent;border:1px solid transparent;border-radius:6px;
  color:var(--ink);font-family:var(--mono);font-size:11px;padding:2px 20px 2px 6px;max-width:min(330px,100%);
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='8' height='5'><path d='M0 0l4 5 4-5z' fill='%238794A8'/></svg>");
  background-repeat:no-repeat;background-position:right 6px center;cursor:pointer}
.clipline select:hover{border-color:var(--line2)}
.progress{flex:1;max-width:430px}
.progress .lbl{font-family:var(--mono);font-size:11px;color:var(--muted);text-align:right}
.progress .lbl b{color:var(--ink);font-weight:600}
.track{height:3px;margin-top:7px;background:#1A2333;border-radius:3px;overflow:hidden}
.track i{display:block;height:100%;width:0;background:var(--teal);transition:width .35s ease}
.session{text-align:right;font-family:var(--mono);font-size:11px;color:var(--muted);min-width:185px}
.session .dirty{display:block;color:var(--amber);margin-bottom:6px}
.session .dirty.off{visibility:hidden}

/* shell */
.shell{flex:1;display:flex;min-height:0}
.main{flex:1;min-width:0;display:flex;flex-direction:column;gap:12px;padding:14px 16px;overflow:auto;background:var(--bg)}
.side{flex:none;width:406px;background:var(--panel);border-left:1px solid var(--line);overflow:auto;padding:18px 18px 34px}

/* viewer */
.viewer{position:relative;flex:1;min-height:420px;background:#05070C;border:1px solid var(--line);
  border-radius:12px;overflow:hidden;display:flex;align-items:center;justify-content:center}
.viewer .still{max-width:100%;max-height:100%;object-fit:contain;display:block}
.viewer .shade{position:absolute;inset:0;pointer-events:none;
  background:linear-gradient(180deg,rgba(0,0,0,.58),rgba(0,0,0,0) 28%,rgba(0,0,0,0) 60%,rgba(0,0,0,.66))}
.v-top{position:absolute;top:0;left:0;right:0;display:flex;justify-content:space-between;
  align-items:flex-start;padding:14px 16px;pointer-events:none}
.v-ts{font-family:var(--mono);font-size:10.5px;color:var(--muted);letter-spacing:.06em}
.v-ts b{font-family:var(--mono);font-weight:600;color:var(--ink);font-size:11px}
.v-title{margin:8px 0 4px;font-family:var(--disp);font-weight:900;font-size:44px;line-height:.95;
  letter-spacing:.01em;text-transform:uppercase;color:var(--ink);text-shadow:0 2px 18px rgba(0,0,0,.6)}
.v-tag{font-family:var(--mono);font-size:10px;letter-spacing:.14em;color:var(--teal)}
.v-right{text-align:right;display:flex;flex-direction:column;gap:6px;align-items:flex-end}
.v-right .pill{font-family:var(--mono);font-size:10px;color:var(--teal);
  border:1px solid var(--teal-b);background:rgba(10,20,28,.72);padding:3px 8px;border-radius:6px}
.v-right .pill.mut{color:var(--muted);border-color:var(--line2);background:rgba(8,12,20,.72)}
.v-facets{position:absolute;left:16px;top:156px;display:flex;flex-direction:column;gap:4px;pointer-events:none}
.v-facets span{font-family:var(--mono);font-size:10.5px;letter-spacing:.12em;color:#C3CEDD;text-shadow:0 1px 8px #000}
.v-bottom{position:absolute;left:0;right:0;bottom:0;display:flex;justify-content:space-between;
  align-items:flex-end;padding:14px 16px 34px;pointer-events:none}
.v-bottom b{display:block;font-family:var(--mono);font-size:11px;font-weight:600;color:var(--ink)}
.v-bottom .sub{font-family:var(--mono);font-size:9.5px;letter-spacing:.12em;color:var(--muted)}
.v-bottom .ts{display:block;margin-top:6px;font-family:var(--mono);font-size:10.5px;color:var(--muted)}
.v-bottom .right{text-align:right}
.v-hint{position:absolute;left:50%;bottom:9px;transform:translateX(-50%);
  font-family:var(--mono);font-size:10px;color:var(--muted);background:rgba(6,10,18,.85);
  border:1px solid var(--line);padding:4px 12px;border-radius:8px;white-space:nowrap}
.v-hint b{color:var(--ink);font-weight:600}

/* evidence */
.ev-head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:9px}
.ev-head b{font-size:13.5px;font-weight:600}
.ev-head span{font-family:var(--mono);font-size:11px;color:var(--muted)}
.ev-head span b{color:var(--ink);font-weight:600}
.stills{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}
.still-card{padding:0;border:1px solid var(--line2);border-radius:9px;overflow:hidden;background:var(--card);
  display:flex;flex-direction:column;transition:border-color .15s,transform .15s}
.still-card:hover{transform:translateY(-1px)}
.still-card.active{border-color:var(--teal);box-shadow:0 0 0 1px var(--teal-b)}
.still-card.unseen{border-style:dashed;border-color:#31405a}
.still-card img{width:100%;height:104px;object-fit:cover;display:block;background:#05070C}
.still-card.empty{height:132px;align-items:center;justify-content:center;color:var(--faint);
  font-family:var(--mono);font-size:10px;text-align:center;padding:8px}
.sc-foot{display:flex;align-items:center;gap:6px;padding:5px 7px;background:var(--card2);border-top:1px solid var(--line)}
.sc-i{font-family:var(--mono);font-size:9px;color:var(--faint);border:1px solid var(--line2);border-radius:4px;padding:1px 4px}
.sc-name{font-family:var(--mono);font-size:9.5px;color:var(--muted);white-space:nowrap}
.sc-status{margin-left:auto;font-family:var(--mono);font-size:9px;color:var(--faint);white-space:nowrap}
.sc-status.v{color:var(--teal)}

/* destinations */
.dest{margin-top:auto;border-top:1px solid var(--line);padding-top:12px;display:flex;flex-direction:column;gap:5px}
.dest .row{display:flex;gap:10px;font-family:var(--mono);font-size:11px}
.dest .k{color:var(--faint);min-width:118px}
.dest .v{color:var(--muted)}

/* sidebar */
.sec{padding:16px 0;border-bottom:1px solid var(--line)}
.sec:first-child{padding-top:0}
.sec:last-child{border-bottom:0;padding-bottom:0}
.sec-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;gap:10px}
.sec-head h2{margin:0;font-size:15px;font-weight:600;letter-spacing:.01em}
.kbd{font-family:var(--mono);font-size:10px;color:var(--muted);background:var(--card);
  border:1px solid var(--line2);border-radius:6px;padding:3px 8px;white-space:nowrap}
.searchbox{position:relative;display:flex;align-items:center;margin-bottom:10px}
.searchbox .ico{position:absolute;left:10px;color:var(--teal);display:flex;pointer-events:none}
.searchbox input{width:100%;background:var(--card);border:1px solid var(--teal-b);border-radius:8px;
  padding:9px 10px 9px 32px;font-size:13px;outline:none}
.searchbox input:focus{box-shadow:0 0 0 3px rgba(45,212,191,.12)}
.matched{font-family:var(--mono);font-size:11px;color:var(--muted);margin-bottom:8px;padding-left:2px}
.matched b{color:var(--ink);font-weight:600}
.mvlist{list-style:none;margin:0;padding:0;max-height:228px;overflow:auto;border:1px solid var(--line);border-radius:9px}
.mvlist li{display:flex;align-items:center;gap:8px;padding:8px 10px;font-size:12.5px;color:var(--muted);cursor:pointer;border-bottom:1px solid var(--line)}
.mvlist li:last-child{border-bottom:0}
.mvlist li:hover,.mvlist li.hi{background:#182234;color:var(--ink)}
.mvlist li.sel{background:#16283a;color:var(--teal)}
.mvlist li .dot{width:4px;height:4px;border-radius:50%;background:currentColor;flex:none;opacity:.7}
.mvlist li .fam{margin-left:auto;font-family:var(--mono);font-size:9.5px;color:var(--faint);text-transform:uppercase;letter-spacing:.08em}
.mvlist li .tag{font-family:var(--mono);font-size:10px;color:var(--muted);margin-left:auto;white-space:nowrap}
.mvlist li.sel .tag{color:var(--teal)}
.reason{display:none;margin-top:12px;background:rgba(245,165,36,.06);border:1px solid var(--amber-b);
  border-left:3px solid var(--amber);border-radius:8px;padding:10px}
.reason.on{display:block}
.reason label{display:block;font-size:11.5px;color:var(--amber);margin-bottom:6px}
.reason input{width:100%;background:var(--bg2);border:1px solid var(--line2);border-radius:6px;padding:7px 9px;font-size:12px;outline:none}
.reason input.missing{border-color:var(--rose)}

/* rep rail + faults */
.rep-rail{display:flex;gap:5px;max-width:230px;overflow-x:auto;padding-bottom:2px}
.rep-rail button{font-family:var(--mono);font-size:10px;padding:3px 7px;border-radius:6px;
  border:1px solid var(--line2);background:var(--card);color:var(--muted);flex:none}
.rep-rail button.ok{color:var(--teal);border-color:var(--teal-b);background:rgba(45,212,191,.07)}
.rep-rail button.part{color:var(--amber);border-color:var(--amber-b)}
.rep-rail button.cur{outline:2px solid var(--violet);outline-offset:1px;color:var(--ink)}
.rep-body{border:1px solid var(--line);border-radius:10px;background:var(--card);overflow:hidden}
.rep-head{display:flex;justify-content:space-between;align-items:center;padding:10px 12px;border-bottom:1px solid var(--line)}
.rep-head b{font-size:13.5px;font-weight:600}
.rep-badge{font-family:var(--mono);font-size:9.5px;color:var(--muted);border:1px solid var(--line2);border-radius:5px;padding:2px 6px}
.rep-lock{padding:14px 12px;font-size:12px;color:var(--amber);background:rgba(245,165,36,.05);
  border-bottom:1px solid var(--line);display:flex;gap:9px;align-items:flex-start;line-height:1.4}
.rep-lock b{font-weight:600}
.rep-lock.hide{display:none}
.no-faults{display:flex;align-items:center;gap:10px;padding:9px 12px;border-bottom:1px solid var(--line)}
.no-faults button{font-size:12px;font-weight:600;padding:5px 12px;border-radius:999px;
  border:1px solid var(--line2);background:var(--card2);color:var(--muted);white-space:nowrap}
.no-faults button.on{color:var(--teal);border-color:var(--teal-b);background:var(--teal-d)}
.no-faults button:disabled{opacity:.4;cursor:not-allowed}
.no-faults small{font-size:10.5px;color:var(--faint);line-height:1.3}
.no-faults small b{color:var(--muted);font-weight:600}
.faults-list{list-style:none;margin:0;padding:0}
.fault{padding:9px 12px;border-bottom:1px solid var(--line);border-left:3px solid transparent}
.fault:last-child{border-bottom:0}
.fault.unanswered{border-left-color:var(--amber)}
.f-top{display:flex;align-items:center;gap:10px}
.f-name{font-size:12.5px;font-weight:600}
.f-name .nm{font-weight:400;color:var(--faint);font-size:10.5px;margin-left:5px}
.tri{margin-left:auto;display:flex;gap:4px}
.tri button{font-family:var(--mono);font-size:10px;width:26px;height:22px;border-radius:6px;
  border:1px solid var(--line2);background:var(--card2);color:var(--muted);padding:0}
.tri button:focus-visible{outline:2px solid var(--violet);outline-offset:1px}
.tri button:disabled{opacity:.35;cursor:not-allowed}
.tri button.on[data-v=present]{background:var(--rose-d);border-color:var(--rose-b);color:var(--rose)}
.tri button.on[data-v=absent]{background:var(--teal-d);border-color:var(--teal-b);color:var(--teal)}
.tri button.on[data-v=unclear]{background:var(--amber-d);border-color:var(--amber-b);color:var(--amber)}
.f-obs{margin-top:3px;font-size:11px;color:var(--muted);line-height:1.4}
.f-corr{margin-top:2px;font-size:10.5px;color:var(--faint);font-style:italic}

/* audit */
.lowconf{width:100%;display:flex;gap:10px;align-items:flex-start;text-align:left;
  background:var(--card);border:1px solid var(--line2);border-radius:9px;padding:10px 12px}
.lowconf .ico{width:26px;height:26px;flex:none;border-radius:7px;border:1px solid var(--line2);
  display:grid;place-items:center;color:var(--muted)}
.lowconf b{display:block;font-size:13px;font-weight:600;color:var(--muted)}
.lowconf small{display:block;font-size:10.5px;color:var(--faint);margin-top:2px;line-height:1.35}
.lowconf.on{border-color:var(--amber-b);background:rgba(245,165,36,.06)}
.lowconf.on .ico{color:var(--amber);border-color:var(--amber-b)}
.lowconf.on b{color:var(--amber)}
.notebox{display:block;margin-top:14px}
.notebox textarea{width:100%;min-height:62px;margin-top:7px;resize:vertical;background:var(--card);
  border:1px solid var(--line2);border-radius:8px;padding:9px;font-size:12px;outline:none}
.notebox textarea:focus{border-color:var(--teal-b)}
.reqs{margin-top:18px}
.reqs ul{list-style:none;margin:9px 0 0;padding:0;display:flex;flex-direction:column;gap:7px}
.reqs li{display:flex;gap:9px;align-items:flex-start;font-size:12px;color:var(--ink)}
.reqs li .mk{width:15px;flex:none;display:grid;place-items:center;margin-top:1px}
.reqs li.ok .mk{color:var(--teal)}
.reqs li.no .mk{color:var(--amber)}
.reqs li .hint{color:var(--amber)}
.commit{width:100%;margin-top:16px;padding:12px;border-radius:9px;border:1px solid var(--line2);
  background:var(--card);color:var(--faint);font-size:13px;font-weight:600;
  display:flex;align-items:center;justify-content:center;gap:8px}
.commit:not(:disabled){background:var(--teal-d);border-color:var(--teal-b);color:var(--teal)}
.commit.next{background:var(--teal-d);border-color:var(--teal-b);color:var(--teal)}
.commit:disabled{cursor:not-allowed}
.locknote{margin-top:9px;font-size:10.5px;color:var(--faint);text-align:center;line-height:1.4}
.toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%) translateY(20px);
  background:var(--card);border:1px solid var(--teal-b);border-radius:9px;padding:10px 16px;
  font-size:12px;color:var(--ink);opacity:0;transition:.25s;pointer-events:none;z-index:50;
  box-shadow:0 10px 30px rgba(0,0,0,.5);max-width:70vw}
.toast.on{opacity:1;transform:translateX(-50%) translateY(0)}
.toast.err{border-color:var(--rose-b)}
.toast b{color:var(--teal)}
@media(max-width:1180px){.side{width:350px}.v-title{font-size:36px}}
@media(max-width:980px){
  /* One column: the whole shell scrolls, not two nested scroll areas. */
  .shell{flex-direction:column;overflow:auto}
  .main{overflow:visible;flex:none}
  .side{width:auto;border-left:0;border-top:1px solid var(--line);overflow:visible;flex:none}
  .topbar{flex-wrap:wrap;gap:12px}
  .brand{min-width:0}
  .progress{flex:1 1 220px;max-width:none}
  .stills{grid-template-columns:repeat(3,1fr)}
}
@media(max-width:600px){
  .topbar{padding:10px 12px}
  .session{min-width:0;text-align:left}
  .main{padding:10px;gap:10px}
  .side{padding:14px 14px 28px}
  .viewer{min-height:300px}
  .v-title{font-size:28px}
  .v-facets{display:none}
  .v-hint{display:none}
  .still-card img{height:76px}
  .sec-head h2{font-size:14px}
  .mvlist{max-height:180px}
}
</style></head><body>
<header class="topbar">
  <div class="brand">
    <div class="row1"><h1>Rep Review</h1><span class="badge">Local Dev Tool</span></div>
    <div class="clipline">Active Clip:&nbsp;<select id="pick" aria-label="Active clip"></select></div>
  </div>
  <div class="progress">
    <div class="lbl">Adjudication Progress: <b id="progText">0 / 0 Verdicts</b></div>
    <div class="track"><i id="progFill"></i></div>
  </div>
  <div class="session">
    <span class="dirty off" id="dirty">&#9679; Unsaved Changes</span>
    <span id="clock">Current session: 0 mins</span>
  </div>
</header>
<div class="shell">
  <main class="main">
    <div class="viewer" id="viewer">
      <img class="still" id="bigStill" alt="">
      <div class="shade"></div>
      <div class="v-top">
        <div>
          <div class="v-ts">STILL <b id="stillNo">01 / 06</b> &nbsp;&middot;&nbsp; Frame <b id="frameNo">1</b></div>
          <h2 class="v-title" id="vTitle">&mdash;</h2>
          <div class="v-tag" id="vTag">[REP 01 / 01]</div>
        </div>
        <div class="v-right">
          <span class="pill" id="vFrames">Frames Extracted: 0 / 0</span>
          <span class="pill mut" id="vMeta">Subject: ?</span>
        </div>
      </div>
      <div class="v-facets" id="vFacets"></div>
      <div class="v-bottom">
        <div>
          <b id="vbTitle">&mdash;</b>
          <span class="sub" id="vbSub">TIMING</span>
          <span class="ts" id="vbTs">Timestamp: &mdash;</span>
        </div>
        <div class="right">
          <b id="vbRight">&mdash;</b>
          <span class="sub" id="vbRightSub">Duration: &mdash;</span>
        </div>
      </div>
      <div class="v-hint"><b>&larr;/&rarr;</b> Still &nbsp; <b>[ ]</b> Rep &nbsp; <b>P</b> Present &nbsp; <b>A</b> Absent &nbsp; <b>C</b> Unclear &nbsp; <b>N</b> No Faults &nbsp; <b>Enter</b> Commit</div>
    </div>

    <section class="evidence">
      <div class="ev-head"><b>Required Evidence: Inspect All Stills</b>
        <span>Viewed Stills Progress: <b id="evProgress">0 / 0 viewed</b></span></div>
      <div class="stills" id="stills"></div>
    </section>

    <footer class="dest">
      <span class="eyebrow">Quiet Audit Destinations</span>
      <div class="row"><span class="k">CSV Destination:</span><span class="v">data/calisthenics/labels-adjudicated.csv</span></div>
      <div class="row"><span class="k">JSON Destination:</span><span class="v" id="jsonDest">out/fault-labels-human/&hellip;.json</span></div>
    </footer>
  </main>

  <aside class="side">
    <section class="sec">
      <div class="sec-head"><h2>1. Authoritative Movement</h2><button class="kbd" id="searchBtn">[S] Search</button></div>
      <div class="searchbox">
        <span class="ico"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.6-3.6"/></svg></span>
        <input id="mvSearch" autocomplete="off" spellcheck="false" aria-label="Search and select the movement performed" placeholder="Search 88 skills&hellip;">
      </div>
      <div class="matched">Matched in <b id="mvCount">88</b> skills:</div>
      <ul class="mvlist" id="mvList"></ul>
      <div class="reason" id="reasonBox">
        <label for="whyInput">Movement changed &mdash; what in the clip says so? <span style="color:var(--rose)">*</span></label>
        <input id="whyInput" aria-label="Why the movement is different" placeholder="e.g. the rear foot is on a bench, so it is a bulgarian split squat">
      </div>
    </section>

    <section class="sec">
      <div class="sec-head"><h2>2. Per-Repetition Faults</h2><span class="rep-rail" id="repRail"></span></div>
      <div class="rep-body">
        <div class="rep-head"><b id="repTitle">Repetition 1</b><span class="rep-badge" id="repBadge">R1</span></div>
        <div class="rep-lock" id="repLock"></div>
        <div class="no-faults">
          <button id="noFaults">No Faults</button>
          <small>Sets every fault here to <b>absent</b> &mdash; an explicit choice, not a default.</small>
        </div>
        <ul class="faults-list" id="faultsList"></ul>
      </div>
    </section>

    <section class="sec">
      <div class="sec-head"><h2>Audit &amp; Confidence Capture</h2><span class="kbd">[U]</span></div>
      <button class="lowconf" id="lowConf">
        <span class="ico" id="lcIco"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M9.5 9.5l5 5M14.5 9.5l-5 5"/></svg></span>
        <span><b>Flag as Low Confidence</b><small>Pins to &ldquo;Uncertain&rdquo; for secondary lead-developer review.</small></span>
      </button>
      <label class="notebox"><span class="eyebrow">Reviewer Note</span>
        <textarea id="note" aria-label="Reviewer note" placeholder="what you saw, in your words &mdash; kept with the label"></textarea></label>
      <div class="reqs"><span class="eyebrow">Verdict Requirements</span><ul id="reqList"></ul></div>
      <button class="commit" id="commit" disabled></button>
      <div class="locknote" id="lockNote">Attention-visibility lock: Unlocks only when all evidence is examined.</div>
    </section>
  </aside>
</div>
<div class="toast" id="toast"></div>
<script>
"use strict";
var $=function(s){return document.querySelector(s)};
var key=function(r,i){return r+":"+i};
var V=["present","absent","unclear"];
var DATA=null,CLIPS=[],MOVEMENTS=[],BYID={},cur=0,S=null,dirty=false,toastTimer=0,hi=-1;
var t0=Date.now();
var ICON={
 ok:'<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>',
 no:'<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 8v5"/><path d="M12 16.4v.02"/></svg>',
 lock:'<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="4" y="11" width="16" height="9" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>'
};
function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]})}
function skillName(id){return BYID[id]?BYID[id].name:(id||"")}
function fmt(s){s=Math.max(0,Number(s)||0);var m=Math.floor(s/60);var sec=s-m*60;return String(m).padStart(2,"0")+":"+sec.toFixed(2).padStart(5,"0")}
function frames(c){return c.kind==="reps"?c.reps:[{index:0,startS:0,endS:c.durationS||0,frames:c.clipFrames||[],whole:true}]}

fetch("index.json").then(function(r){return r.json()}).then(function(d){
  DATA=d;CLIPS=d.clips||[];MOVEMENTS=d.movements||[];
  MOVEMENTS.forEach(function(m){BYID[m.id]=m});
  buildPick();updateProgress(d.stats);
  setInterval(tick,15000);tick();
  loadClip(0);
});

function buildPick(){
  var p=$("#pick");p.innerHTML="";
  CLIPS.forEach(function(c,i){var o=document.createElement("option");o.value=i;
    o.textContent=c.clip+" ("+skillName(c.movement)+", "+(c.kind==="reps"?c.reps.length+" reps":"whole clip")+")"+(c.done?" \u2713":"");
    p.appendChild(o)});
  p.value=cur;
  p.onchange=function(){if(dirty&&!confirm("Discard unsaved changes on this clip?")){p.value=cur;return}loadClip(+p.value)};
}
function updateProgress(st){
  if(!st)return;DATA.stats=st;
  $("#progText").textContent=st.answered+" / "+st.total+" Verdicts";
  $("#progFill").style.width=(st.total?Math.round(st.answered/st.total*100):0)+"%";
}
function tick(){var m=Math.floor((Date.now()-t0)/60000);$("#clock").textContent="Current session: "+m+" min"+(m===1?"":"s")}
function setDirty(v){dirty=v;$("#dirty").classList.toggle("off",!v)}
function toast(msg,err){
  var el=$("#toast");el.textContent=msg;el.className="toast on"+(err?" err":"");
  clearTimeout(toastTimer);toastTimer=setTimeout(function(){el.className="toast"},2800);
}

function loadClip(i){
  cur=i;var c=CLIPS[i];
  var reps=frames(c).map(function(r){return{index:r.index,startS:r.startS,endS:r.endS,frames:r.frames||[],whole:!!r.whole}});
  S={c:c,reps:reps,rep:0,still:0,
     movement:(c.saved&&c.saved.movement)||c.movement,
     confirmed:!!c.saved,
     movementReason:(c.saved&&c.saved.movementReason)||"",
     lowConfidence:!!(c.saved&&c.saved.lowConfidence),
     note:(c.saved&&c.saved.note)||"",
     viewed:{},answers:{},saved:!!c.saved};
  if(c.saved&&c.saved.reps)c.saved.reps.forEach(function(r){var f=r.faults||{};Object.keys(f).forEach(function(k){S.answers[key(r.index,k)]=f[k]})});
  if(c.saved)S.reps.forEach(function(r){r.frames.forEach(function(_,j){S.viewed[key(r.index,j)]=true})});
  renderAll();
  if(!c.saved)markViewed();else renderReqs();
}

function renderAll(){
  renderViewer();renderEvidence();renderMovementSection();renderRepRail();renderRepCard();renderReqs();
  $("#jsonDest").textContent="out/fault-labels-human/"+String(S.c.clip).replace(/\.[^.]+$/,"")+".json";
  $("#note").value=S.note;
  $("#lowConf").classList.toggle("on",S.lowConfidence);
  setDirty(false);
}

/* ---------- viewer ---------- */
function renderViewer(){
  var c=S.c,r=S.reps[S.rep],fr=r.frames||[],total=fr.length||1;
  S.still=Math.max(0,Math.min(S.still,total-1));
  var src=fr[S.still],img=$("#bigStill");
  if(src){img.src=src;img.style.display=""}else{img.removeAttribute("src");img.style.display="none"}
  $("#stillNo").textContent=String(S.still+1).padStart(2,"0")+" / "+String(total).padStart(2,"0");
  $("#frameNo").textContent=S.still+1;
  $("#vTitle").textContent=skillName(c.movement).toUpperCase();
  $("#vTag").textContent=c.kind==="reps"?"[REP "+String(S.rep+1).padStart(2,"0")+" / "+String(S.reps.length).padStart(2,"0")+"]":"[WHOLE CLIP]";
  var viewed=fr.filter(function(_,j){return S.viewed[key(r.index,j)]}).length;
  $("#vFrames").textContent="Frames Extracted: "+viewed+" / "+total;
  $("#vMeta").textContent="Subject: "+(c.subject||"?")+(c.angle?" \u00b7 "+c.angle:"");
  var facets=["MOVEMENT \u00b7 "+c.movement,"DECLARED \u00b7 "+(c.declared||"?"),
    c.intendedFault?"INTENDED FAULT \u00b7 "+c.intendedFault:"INTENDED \u00b7 none (clean set)"];
  $("#vFacets").innerHTML=facets.map(function(x){return "<span>"+esc(x)+"</span>"}).join("");
  $("#vbTitle").textContent=skillName(c.movement).toUpperCase();
  $("#vbSub").textContent=c.kind==="reps"?"TIMING \u00b7 REP WINDOW":"TIMING \u00b7 WHOLE CLIP";
  $("#vbTs").textContent=c.kind==="reps"?"Timestamp: "+fmt(r.startS)+" \u2013 "+fmt(r.endS):"Timestamp: 00:00.00 \u2013 "+fmt(c.durationS);
  $("#vbRight").textContent=c.kind==="reps"?"Rep "+(S.rep+1)+" of "+S.reps.length:total+" stills";
  $("#vbRightSub").textContent="Duration: "+(c.kind==="reps"?fmt(Math.max(0,r.endS-r.startS)):fmt(c.durationS));
}

/* ---------- evidence ---------- */
function renderEvidence(){
  var r=S.reps[S.rep],fr=r.frames||[],wrap=$("#stills");wrap.innerHTML="";
  if(!fr.length){
    wrap.innerHTML='<div class="still-card empty">frames failed to extract \u2014 movement can still be labelled</div>';
  }else{
    fr.forEach(function(src,j){
      var done=!!S.viewed[key(r.index,j)];
      var b=document.createElement("button");
      b.className="still-card"+(j===S.still?" active":"")+(done?"":" unseen");
      b.innerHTML='<img src="'+src+'" loading="lazy" alt="">'+
        '<div class="sc-foot"><span class="sc-i">'+(j+1)+'</span><span class="sc-name">Still '+String(j+1).padStart(2,"0")+'</span>'+
        '<span class="sc-status'+(done?" v":"")+'">'+(done?"\u2713 Viewed":"\u25cb Unseen")+'</span></div>';
      b.onclick=function(){S.still=j;markViewed()};
      wrap.appendChild(b);
    });
  }
  var v=fr.filter(function(_,j){return S.viewed[key(r.index,j)]}).length;
  $("#evProgress").textContent=v+" / "+fr.length+" viewed";
}

/* ---------- movement ---------- */
function renderMovementSection(){
  var inp=$("#mvSearch");
  inp.value=skillName(S.movement);
  renderMatches("");
  updateReason();
}
function renderMatches(q){
  q=(q||"").trim().toLowerCase();
  var matches=MOVEMENTS.filter(function(m){return !q||m.name.toLowerCase().indexOf(q)>=0||m.id.indexOf(q)>=0||m.family.toLowerCase().indexOf(q)>=0});
  $("#mvCount").textContent=q?matches.length:MOVEMENTS.length;
  hi=-1;
  var list=$("#mvList");list.innerHTML="";
  if(!q){var sel=matches.filter(function(m){return m.id===S.movement})[0];if(sel)list.appendChild(mvRow(sel));}
  matches.forEach(function(m){if(!q&&m.id===S.movement)return;list.appendChild(mvRow(m))});
  list.appendChild(ctRow());
}
function mvRow(m){
  var isSel=S.movement===m.id,li=document.createElement("li");
  li.className=isSel?"sel":"";li.dataset.id=m.id;
  li.innerHTML='<span class="dot"></span><span>'+esc(m.name)+'</span>'+
    (isSel?'<span class="tag">'+(S.confirmed?"Selected":"Confirm \u00b7 Enter")+'</span>':'<span class="fam">'+esc(m.family)+'</span>');
  li.onclick=function(){chooseMovement(m.id)};
  return li;
}
function ctRow(){
  var isSel=S.movement==="unclear",li=document.createElement("li");
  li.className=isSel?"sel":"";li.dataset.id="unclear";
  li.innerHTML='<span class="dot"></span><span>&mdash; cannot tell from this clip &mdash;</span>'+
    (isSel?'<span class="tag">'+(S.confirmed?"Selected":"Confirm \u00b7 Enter")+'</span>':'');
  li.onclick=function(){chooseMovement("unclear")};
  return li;
}
function chooseMovement(id){
  S.movement=id;S.confirmed=true;
  $("#mvSearch").value=skillName(id);
  setDirty(true);renderMatches("");updateReason();renderReqs();
}
function movementChanged(){return S.movement!==S.c.movement&&S.movement!=="unclear"}
function updateReason(){
  var need=movementChanged(),box=$("#reasonBox"),inp=$("#whyInput");
  box.classList.toggle("on",need);
  inp.value=S.movementReason;
  inp.classList.toggle("missing",need&&!S.movementReason.trim());
}
function paintHi(){Array.prototype.forEach.call($("#mvList").children,function(el,i){el.classList.toggle("hi",i===hi)})}

/* ---------- reps + faults ---------- */
function repUnlocked(r){var fr=r.frames||[];return fr.length===0||fr.every(function(_,j){return S.viewed[key(r.index,j)]})}
function renderRepRail(){
  var rail=$("#repRail");rail.innerHTML="";
  S.reps.forEach(function(r,ri){
    var fr=r.frames||[],total=S.c.vocabulary.length;
    var v=fr.filter(function(_,j){return S.viewed[key(r.index,j)]}).length;
    var ans=total?S.c.vocabulary.filter(function(x){return S.answers[key(r.index,x.name)]}).length:0;
    var cls="";
    if(total)cls=ans>=total?"ok":(ans>0||v>0?"part":"");
    else cls=v>=fr.length&&fr.length>0?"ok":(v>0?"part":"");
    var b=document.createElement("button");
    b.className=cls+(ri===S.rep?" cur":"");
    b.textContent=S.c.kind==="reps"?"R"+(ri+1):"CLIP";
    b.title=total?ans+"/"+total+" faults answered":v+"/"+fr.length+" stills viewed";
    b.onclick=function(){S.rep=ri;S.still=0;renderRepCard();renderRepRail();renderViewer();renderEvidence()};
    rail.appendChild(b);
  });
}
function renderRepCard(){
  var c=S.c,r=S.reps[S.rep],total=c.vocabulary.length;
  $("#repTitle").textContent=c.kind==="reps"?"Repetition "+(S.rep+1):"Whole Clip";
  $("#repBadge").textContent=c.kind==="reps"?"R"+(S.rep+1):"CLIP";
  var unlocked=repUnlocked(r),lock=$("#repLock");
  var remaining=(r.frames||[]).filter(function(_,j){return !S.viewed[key(r.index,j)]}).length;
  if(total&&!unlocked){lock.classList.remove("hide");
    lock.innerHTML=ICON.no+'<span>Inspect all <b>'+(r.frames||[]).length+'</b> stills of this rep to answer its faults. <b>'+remaining+'</b> remain.</span>';
  }else lock.classList.add("hide");
  var list=$("#faultsList");list.innerHTML="";
  if(!total){
    list.innerHTML='<li class="fault" style="border-left:0;color:var(--faint);font-size:11.5px">No per-rep fault questions for this movement.</li>';
  }else{
    c.vocabulary.forEach(function(v){
      var ans=S.answers[key(r.index,v.name)];
      var li=document.createElement("li");
      li.className="fault "+(ans?"answered":"unanswered");
      li.dataset.rep=r.index;li.dataset.name=v.name;
      li.innerHTML='<div class="f-top"><span class="f-name">'+esc(v.label||v.name)+'<span class="nm">'+esc(v.name)+'</span></span>'+
        '<span class="tri">'+V.map(function(x){return '<button data-v="'+x+'" class="'+(ans===x?"on":"")+'" '+(unlocked?"":"disabled")+'" title="'+x+'">'+x[0].toUpperCase()+'</button>'}).join("")+'</span></div>'+
        '<div class="f-obs">'+esc(v.observable||"")+'</div>'+
        (v.correction?'<div class="f-corr">fix: '+esc(v.correction)+'</div>':'');
      list.appendChild(li);
    });
  }
  var nf=$("#noFaults");
  var allAbsent=total>0&&c.vocabulary.every(function(x){return S.answers[key(r.index,x.name)]==="absent"});
  nf.classList.toggle("on",allAbsent);nf.disabled=!unlocked;
  Array.prototype.forEach.call(list.querySelectorAll(".tri button"),function(b){
    b.onclick=function(){if(b.disabled)return;var li=b.closest(".fault");setFault(li.dataset.rep,li.dataset.name,b.dataset.v)};
  });
}
function setFault(rep,name,v){
  var r=S.reps.filter(function(x){return String(x.index)===String(rep)})[0]||S.reps[S.rep];
  if(!repUnlocked(r))return;
  S.answers[key(rep,name)]=v;setDirty(true);renderRepCard();renderRepRail();renderReqs();
}

/* ---------- requirements / commit ---------- */
function clipProgress(){
  var ft=0,fd=0,wt=0,wd=0;
  S.reps.forEach(function(r){
    var fr=r.frames||[];wt+=fr.length;wd+=fr.filter(function(_,j){return S.viewed[key(r.index,j)]}).length;
    S.c.vocabulary.forEach(function(v){ft++;if(S.answers[key(r.index,v.name)])fd++});
  });
  return{faultsTotal:ft,faultsDone:fd,framesTotal:wt,framesDone:wd};
}
function renderReqs(){
  var p=clipProgress(),reasonNeeded=movementChanged()&&!S.movementReason.trim(),items=[];
  items.push(S.confirmed
    ?{ok:true,text:S.movement==="unclear"?"Movement marked cannot tell":"Movement skill assigned"}
    :{ok:false,text:"Movement skill not confirmed",hint:"Select it in section 1"});
  if(p.framesTotal===0)items.push({ok:true,text:"No stills to inspect (extraction failed)"});
  else items.push(p.framesDone>=p.framesTotal
    ?{ok:true,text:"All "+p.framesTotal+" stills viewed"}
    :{ok:false,text:(p.framesTotal-p.framesDone)+" still"+(p.framesTotal-p.framesDone===1?"":"s")+" remain unseen",hint:"Inspect to unlock"});
  if(p.faultsTotal>0)items.push(p.faultsDone>=p.faultsTotal
    ?{ok:true,text:"All "+p.faultsTotal+" fault calls answered"}
    :{ok:false,text:(p.faultsTotal-p.faultsDone)+" fault call"+(p.faultsTotal-p.faultsDone===1?"":"s")+" unanswered",hint:"present / absent / unclear"});
  if(movementChanged())items.push(reasonNeeded
    ?{ok:false,text:"Movement reason required",hint:"A correction needs its evidence"}
    :{ok:true,text:"Movement reason recorded"});
  $("#reqList").innerHTML=items.map(function(it){
    return '<li class="'+(it.ok?"ok":"no")+'"><span class="mk">'+(it.ok?ICON.ok:ICON.no)+'</span><span>'+esc(it.text)+
      (it.hint?' <span class="hint">('+esc(it.hint)+')</span>':'')+'</span></li>';
  }).join("");
  var can=items.every(function(i){return i.ok}),btn=$("#commit");
  if(S.saved){btn.disabled=false;btn.classList.add("next");btn.innerHTML="Next Clip &rarr;"}
  else{btn.classList.remove("next");btn.disabled=!can;btn.innerHTML=ICON.lock+" Commit Verdict [Enter]"}
  $("#lockNote").textContent=S.saved?"Saved. Move on when ready.":(can?"All evidence examined \u2014 verdict unlocks.":"Attention-visibility lock: Unlocks only when all evidence is examined.");
  return can;
}
function save(){
  var c=S.c;
  var payload={file:c.file,clip:c.clip,movement:S.movement,movementReason:S.movementReason.trim(),
    declared:c.declared,proposed:c.proposed||"",kind:c.kind,intendedFault:c.intendedFault,
    severity:c.severity,subject:c.subject,angle:c.angle,note:S.note,lowConfidence:S.lowConfidence,
    reps:S.reps.map(function(r){return{index:r.index,startS:r.startS,endS:r.endS,
      viewed:(r.frames||[]).filter(function(_,j){return S.viewed[key(r.index,j)]}).length,
      faults:Object.fromEntries(c.vocabulary.map(function(v){return[v.name,S.answers[key(r.index,v.name)]]}).filter(function(kv){return kv[1]}))}})};
  var btn=$("#commit");btn.disabled=true;btn.textContent="Saving\u2026";
  fetch("/save",{method:"POST",body:JSON.stringify(payload)})
    .then(function(r){if(!r.ok)throw new Error("HTTP "+r.status);return r.json()})
    .then(function(d){
      updateProgress(d.progress);
      c.done=true;c.saved=Object.assign({},payload,{faults:d.faults});
      S.saved=true;setDirty(false);buildPick();renderReqs();
      var present=Object.keys(d.faults||{}).filter(function(k){return d.faults[k]==="present"}).join(", ");
      toast("Saved \u00b7 "+skillName(S.movement)+(d.movementRecorded?"":" (movement not recorded)")+(present?" \u00b7 "+present:""));
    })
    .catch(function(err){toast("Save failed: "+err,true);renderReqs()});
}
function nextClip(){
  var n=(cur+1)%CLIPS.length;
  for(var k=1;k<=CLIPS.length;k++){var j=(cur+k)%CLIPS.length;if(!CLIPS[j].done){n=j;break}}
  loadClip(n);
}
function markViewed(){
  var r=S.reps[S.rep];
  if(r.frames[S.still]!==undefined)S.viewed[key(r.index,S.still)]=true;
  renderViewer();renderEvidence();renderRepCard();renderReqs();renderRepRail();
}

/* ---------- controls ---------- */
$("#commit").onclick=function(){
  if(S.saved){nextClip();return}
  if(!renderReqs()){toast("Not yet \u2014 finish the requirements",true);return}
  save();
};
$("#searchBtn").onclick=function(){$("#mvSearch").focus()};
$("#lowConf").onclick=function(){S.lowConfidence=!S.lowConfidence;setDirty(true);$("#lowConf").classList.toggle("on",S.lowConfidence)};
$("#note").addEventListener("input",function(e){S.note=e.target.value;setDirty(true)});
$("#whyInput").addEventListener("input",function(e){S.movementReason=e.target.value;setDirty(true);e.target.classList.toggle("missing",movementChanged()&&!e.target.value.trim());renderReqs()});
$("#noFaults").onclick=function(){
  var r=S.reps[S.rep];if(!repUnlocked(r))return;
  S.c.vocabulary.forEach(function(v){S.answers[key(r.index,v.name)]="absent"});
  setDirty(true);renderRepCard();renderRepRail();renderReqs();
};
$("#mvSearch").addEventListener("input",function(e){renderMatches(e.target.value)});
$("#mvSearch").addEventListener("focus",function(e){
  if(e.target.value===skillName(S.movement))e.target.select();
  renderMatches(e.target.value===skillName(S.movement)?"":e.target.value);
});
$("#mvSearch").addEventListener("blur",function(e){
  setTimeout(function(){if(!document.activeElement||!document.activeElement.closest(".mvlist"))e.target.value=skillName(S.movement)},150);
});
$("#mvSearch").addEventListener("keydown",function(e){
  var items=Array.prototype.slice.call($("#mvList").children);
  if(e.key==="ArrowDown"){e.preventDefault();hi=Math.min(items.length-1,hi+1);paintHi()}
  else if(e.key==="ArrowUp"){e.preventDefault();hi=Math.max(0,hi-1);paintHi()}
  else if(e.key==="Enter"){e.preventDefault();var el=items[hi<0?0:hi];if(el)chooseMovement(el.dataset.id)}
  else if(e.key==="Escape"){e.target.value="";renderMatches("");e.target.blur()}
});
document.addEventListener("keydown",function(e){
  var tag=(e.target.tagName||"").toLowerCase(),typing=tag==="input"||tag==="textarea";
  if(e.key==="Escape"&&typing){e.target.blur();return}
  if(typing||e.ctrlKey||e.metaKey||e.altKey)return;
  var k=e.key.toLowerCase();
  if(k==="s"){e.preventDefault();$("#mvSearch").focus();return}
  if(e.key==="ArrowLeft"){e.preventDefault();moveStill(-1)}
  else if(e.key==="ArrowRight"){e.preventDefault();moveStill(1)}
  else if(k==="["){e.preventDefault();moveRep(-1)}
  else if(k==="]"){e.preventDefault();moveRep(1)}
  else if(k==="n"){e.preventDefault();$("#noFaults").click()}
  else if(k==="u"){e.preventDefault();$("#lowConf").click()}
  else if(k==="p"||k==="1"){setFocusedFault("present")}
  else if(k==="a"||k==="2"){setFocusedFault("absent")}
  else if(k==="c"||k==="3"){setFocusedFault("unclear")}
  else if(e.key==="Enter"){e.preventDefault();if(!$("#commit").disabled)$("#commit").click()}
});
function setFocusedFault(v){
  var el=document.activeElement,li=el&&el.closest?el.closest(".fault"):null;
  if(li){setFault(li.dataset.rep,li.dataset.name,v);return}
  var r=S.reps[S.rep],v0=S.c.vocabulary.filter(function(x){return !S.answers[key(r.index,x.name)]})[0];
  if(v0)setFault(r.index,v0.name,v);
}
function moveStill(d){var r=S.reps[S.rep],n=(r.frames||[]).length;if(!n)return;S.still=(S.still+d+n)%n;markViewed()}
function moveRep(d){S.rep=(S.rep+d+S.reps.length)%S.reps.length;S.still=0;renderRepCard();renderRepRail();renderViewer();renderEvidence()}
</script></body></html>
'''



def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--extract", action="store_true")
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--template", action="store_true",
                    help="write a starter capture manifest and exit")
    ap.add_argument("--from-labels", action="store_true", dest="from_labels",
                    help="extract every clip in data/calisthenics/labels.csv too")
    ap.add_argument("--include-unknown", action="store_true",
                    help="keep clips whose movement is not a skill id, for "
                         "movement-only review, instead of skipping them")
    ap.add_argument("--limit", type=int, default=0,
                    help="extract only the first N clips (a smoke test)")
    # 876 was the historic default, but it is below 1024 and therefore
    # privileged: binding it without root fails with PermissionError, which
    # made the shipped default unusable on a normal dev machine.
    ap.add_argument("--port", type=int, default=8765)
    # Bind where the review is reachable from. Localhost by default; a phone
    # on the LAN wants 0.0.0.0, and a reverse proxy in front wants localhost
    # again. Environment fallbacks exist so a systemd unit can carry the
    # settings without putting a password on the command line.
    ap.add_argument("--host", default=os.environ.get("LABEL_HOST", "127.0.0.1"),
                    help="interface to bind (127.0.0.1, 0.0.0.0)")
    ap.add_argument("--user", default=os.environ.get("LABEL_USER", ""),
                    help="HTTP Basic user; empty disables auth")
    ap.add_argument("--password", default=os.environ.get("LABEL_PASSWORD", ""),
                    help="HTTP Basic password")
    a = ap.parse_args()
    if a.template:
        write_template()
        return 0
    if a.extract:
        return extract(include_corpus=a.from_labels,
                       include_unknown=a.include_unknown, limit=a.limit)
    if a.serve:
        credentials = (a.user, a.password) if (a.user or a.password) else None
        if a.user and not a.password:
            print("refusing: a user was given with no password", file=sys.stderr)
            return 2
        return serve(a.port, a.host, credentials)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
