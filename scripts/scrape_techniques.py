#!/usr/bin/env python3
"""Collect openly licensed technique knowledge for the skill graph.

The measurement core says what a rep *did*. It has never been able to say what
a rep is *for* - the cues a coach gives, the faults people actually make, which
muscles carry the movement - because it had no source for any of that, and
inventing it would be the thing this project refuses to do everywhere else.

This script builds that source, from places that publish it under a licence
that allows reuse, and records the attribution on every record so the app can
show where a sentence came from:

  free_exercise_db   github.com/yuhonas/free-exercise-db - Unlicense (public
                     domain). 870 exercises with step-by-step instructions.
  wger               wger.de REST API - CC BY-SA 4.0, no key needed. Exercise
                     descriptions, muscles, equipment, per-record author.
  wikipedia          en.wikipedia.org - CC BY-SA 4.0. The article extract for
                     each skill that has one (Muscle-up, Front lever, ...).
  youtube_cc         auto-captions of the Creative Commons tutorials already in
                     data/calisthenics/metadata.csv, via yt-dlp. CC BY, credit
                     the channel. Off by default: it needs yt-dlp and YouTube.

Every record is matched to a skill id from barra/skills.py by name, with an
explicit alias table. An entry that names no skill is dropped rather than
guessed, and an entry that names a machine, barbell or dumbbell is dropped even
when it names a skill: "Smith Machine Pistol Squat" is not a pistol squat.

Cues and faults are *mined* from the instruction text by sentence shape -
"keep your elbows close" is a cue, "avoid swinging" is a fault - and marked as
mined, not authored. It is a heuristic and it says so in the output.

    python scripts/scrape_techniques.py                     # every source that answers
    python scripts/scrape_techniques.py --sources free_exercise_db
    python scripts/scrape_techniques.py --transcripts       # also caption-mine the CC clips
    python scripts/scrape_techniques.py --offline           # rebuild from the raw cache

Output: data/techniques/techniques.json, plus data/techniques/raw/ (cached
downloads, not committed) and data/techniques/ATTRIBUTION.md.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from barra.skills import SKILLS  # noqa: E402

UA = "barrapp-techniques/0.1 (research dataset builder; local use)"

FREE_DB_URL = ("https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/"
               "dist/exercises.json")
FREE_DB_PAGE = "https://github.com/yuhonas/free-exercise-db"
WGER_API = "https://wger.de/api/v2/exerciseinfo/"
WIKI_API = "https://en.wikipedia.org/w/api.php"

LICENSES = {
    "free_exercise_db": ("Unlicense (public domain)", FREE_DB_PAGE),
    "wger": ("CC BY-SA 4.0", "https://wger.de/en/software/api"),
    "wikipedia": ("CC BY-SA 4.0", "https://en.wikipedia.org/wiki/Wikipedia:Copyrights"),
    "youtube_cc": ("CC BY 3.0 (YouTube Creative Commons)",
                   "https://support.google.com/youtube/answer/2797468"),
}

# ---------------------------------------------------------------------------
# Skill aliases: how each source names the thing the graph calls `skill_id`.
# Matched as whole phrases against a normalised name, longest alias wins.
# ---------------------------------------------------------------------------
ALIASES: dict[str, list[str]] = {
    "push_up": ["push up", "push ups", "pushup", "pushups", "press up"],
    "incline_push_up": ["incline push up"],
    "knee_push_up": ["knee push up", "kneeling push up"],
    "wide_push_up": ["push up wide", "wide push up", "wide grip push up"],
    "diamond_push_up": ["diamond push up", "close triceps position", "close grip push up"],
    "decline_push_up": ["decline push up", "feet elevated"],
    "archer_push_up": ["archer push up"],
    "pseudo_planche_push_up": ["pseudo planche push up", "pseudo planche"],
    "one_arm_push_up": ["single arm push up", "one arm push up"],
    "bench_dip": ["bench dip", "bench dips"],
    "dip": ["parallel bar dip", "dips triceps version", "dips chest version",
            "bar dips", "bar dip", "dip", "dips"],
    "ring_dip": ["ring dip", "ring dips"],
    "korean_dip": ["korean dip"],
    "dead_hang": ["dead hang"],
    "scapular_pull": ["scapular pull up", "scapular pull", "scap pull"],
    "australian_row": ["australian pull up", "australian row", "inverted row",
                       "bodyweight row"],
    "negative_pull_up": ["negative pull up", "negative pullup", "eccentric pull up"],
    "chin_up": ["chin up", "chin ups", "chinup", "chinups"],
    "pull_up": ["pull up", "pull ups", "pullup", "pullups"],
    "chest_to_bar": ["chest to bar"],
    "typewriter_pull_up": ["typewriter pull up", "typewriter"],
    "archer_pull_up": ["archer pull up"],
    "one_arm_pull_up": ["one arm pull up", "single arm pull up"],
    "explosive_pull_up": ["explosive pull up", "high pull up"],
    "kipping_muscle_up": ["kipping muscle up"],
    "muscle_up": ["muscle up", "muscle ups", "muscleup"],
    "strict_muscle_up": ["strict muscle up"],
    "ring_muscle_up": ["ring muscle up"],
    "plank": ["plank"],
    "hollow_hold": ["hollow hold", "hollow body hold", "hollow body"],
    "knee_raise": ["hanging knee raise", "hanging knee raises"],
    "leg_raise": ["hanging leg raise", "hanging leg raises"],
    "toes_to_bar": ["toes to bar", "hanging pike"],
    "l_sit": ["l sit", "l sits"],
    "dragon_flag": ["dragon flag"],
    "v_sit": ["v sit"],
    "front_lever": ["front lever"],
    "tuck_front_lever": ["tuck front lever"],
    "back_lever": ["back lever"],
    "tuck_back_lever": ["tuck back lever"],
    "skin_the_cat": ["skin the cat"],
    "planche_lean": ["planche lean"],
    "frog_stand": ["frog stand", "crow pose"],
    "tuck_planche": ["tuck planche"],
    "straddle_planche": ["straddle planche"],
    "full_planche": ["full planche", "planche"],
    "planche_push_up": ["planche push up"],
    "chest_to_wall_handstand": ["chest to wall handstand", "wall handstand"],
    "freestanding_handstand": ["handstand", "freestanding handstand"],
    "wall_hspu": ["handstand push up", "handstand push ups", "wall handstand push up"],
    "press_to_handstand": ["press to handstand", "press handstand"],
    "elbow_lever": ["elbow lever"],
    "human_flag": ["human flag"],
    "squat": ["bodyweight squat", "air squat", "body weight squat"],
    "jump_squat": ["jump squat", "freehand jump squat"],
    "split_squat": ["split squat"],
    "bulgarian_split_squat": ["bulgarian split squat"],
    "pistol_squat": ["pistol squat", "pistol"],
    "shrimp_squat": ["shrimp squat"],
    "sissy_squat": ["sissy squat"],
    "nordic_curl": ["nordic curl", "nordic hamstring curl", "natural glute ham raise"],
}

# Names carrying any of these are not bodyweight skills whatever else they say.
NOT_BODYWEIGHT = ("machine", "barbell", "dumbbell", "kettlebell", "cable",
                  "smith", "band ", "banded", "weighted", "leverage",
                  "rocky", "v bar", "wide grip rear")

# Wikipedia article per skill, where one exists that is about the skill.
WIKI_PAGES: dict[str, str] = {
    "muscle_up": "Muscle-up",
    "pull_up": "Pull-up (exercise)",
    "chin_up": "Chin-up",
    "dip": "Dip (exercise)",
    "push_up": "Push-up",
    "squat": "Squat (exercise)",
    "pistol_squat": "Pistol squat",
    "plank": "Plank (exercise)",
    "l_sit": "L-sit",
    "front_lever": "Front lever",
    "back_lever": "Back lever",
    "full_planche": "Planche (exercise)",
    "freestanding_handstand": "Handstand",
    "wall_hspu": "Handstand push-up",
    "human_flag": "Human flag",
    "leg_raise": "Leg raise",
    "dragon_flag": "Dragon flag",
    "australian_row": "Inverted row",
    "nordic_curl": "Nordic hamstring curl",
}


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
def normalise(name: str) -> str:
    s = html.unescape(name or "").lower()
    s = re.sub(r"[\-_/(),.:]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


_ALIAS_INDEX: list[tuple[str, str]] = sorted(
    ((alias, sid) for sid, aliases in ALIASES.items() for alias in aliases),
    key=lambda t: -len(t[0]),
)


def match_skill(name: str) -> str | None:
    """The skill an exercise name is about, or None. Longest alias wins, so
    "kipping muscle up" is not filed under "muscle up"."""
    n = normalise(name)
    if not n or any(bad in n + " " for bad in NOT_BODYWEIGHT):
        return None
    padded = f" {n} "
    for alias, sid in _ALIAS_INDEX:
        if f" {alias} " in padded:
            return sid
    return None


# ---------------------------------------------------------------------------
# Cue and fault mining
# ---------------------------------------------------------------------------
_CUE_START = re.compile(
    r"^(keep|maintain|squeeze|lock|drive|pull|push|press|brace|tuck|point|"
    r"engage|lower|extend|hold|start|initiate|reverse|control|pause|breathe|"
    r"exhale|inhale|make sure|try to|focus on|concentrate on|grip|grab|hang|"
    r"raise|lift|bend|straighten|stay|think|imagine|aim)\b", re.I)
_FAULT = re.compile(
    r"\b(avoid|don'?t|do not|never|mistake|common error|too (fast|far|wide|"
    r"much)|swing(ing)?|kip(ping)?|shrug(ging)?|flar(e|ing)|sag(ging)?|"
    r"arch(ing)? (the|your) (lower )?back|jerk(ing)?|momentum|bounce|"
    r"half rep|partial|round(ing)? (the|your) back)\b", re.I)
_TIP = re.compile(r"\btip\s*:\s*", re.I)
# A cue often follows a lead-in ("As you squat, keep your chest up"). The
# lead-in is stripped before the sentence shape is read.
_LEAD_IN = re.compile(
    r"^(as you [^,]{2,40},|now,?|then,?|next,?|slowly,?|finally,?|"
    r"at the top,?|at the bottom,?|from (here|there),?|throughout,?)\s*", re.I)
_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def sentences(text: str) -> list[str]:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    out = []
    for s in _SPLIT.split(text):
        s = s.strip()
        if 20 <= len(s) <= 240:
            out.append(s)
    return out


def mine(text: str) -> tuple[list[str], list[str]]:
    """(cues, faults) read out of free text by sentence shape. Heuristic."""
    cues: list[str] = []
    faults: list[str] = []
    for s in sentences(text):
        body = _TIP.sub("", s).strip()
        core = _LEAD_IN.sub("", body).strip()
        is_fault = bool(_FAULT.search(body))
        is_cue = bool(_CUE_START.match(core)) or _TIP.search(s) is not None
        if is_fault:
            faults.append(body)
        elif is_cue:
            cues.append(body)
    return _dedupe(cues), _dedupe(faults)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for it in items:
        k = normalise(it)
        if k not in seen:
            seen.add(k)
            out.append(it)
    return out


# ---------------------------------------------------------------------------
# Fetching, with a raw cache so a rebuild does not re-download
# ---------------------------------------------------------------------------
def get(url: str, cache: Path, retries: int = 3, timeout: int = 60) -> bytes:
    if cache.exists():
        return cache.read_bytes()
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(data)
            return data
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


# ---------------------------------------------------------------------------
# Sources. Each returns a list of records:
#   {skill, source, title, url, license, attribution, summary, instructions[],
#    muscles[], equipment[], level}
# ---------------------------------------------------------------------------
def parse_free_exercise_db(data: list[dict]) -> list[dict]:
    out = []
    for e in data:
        sid = match_skill(e.get("name", ""))
        if not sid:
            continue
        equipment = (e.get("equipment") or "").lower()
        if equipment not in ("", "body only", "other", "none"):
            continue
        out.append({
            "skill": sid, "source": "free_exercise_db",
            "title": e.get("name", ""),
            "url": f"{FREE_DB_PAGE}/blob/main/exercises/{e.get('id', '')}.json",
            "license": LICENSES["free_exercise_db"][0],
            "attribution": "free-exercise-db contributors",
            "summary": "",
            "instructions": [s for s in (e.get("instructions") or []) if s],
            "muscles": list((e.get("primaryMuscles") or []) + (e.get("secondaryMuscles") or [])),
            "equipment": [equipment] if equipment else [],
            "level": e.get("level") or "",
        })
    return out


def fetch_free_exercise_db(raw: Path) -> list[dict]:
    data = json.loads(get(FREE_DB_URL, raw / "free_exercise_db.json"))
    return parse_free_exercise_db(data)


def parse_wger(pages: list[dict]) -> list[dict]:
    out = []
    for page in pages:
        for e in page.get("results", []):
            # v2 exerciseinfo carries translations; older payloads carried
            # name/description at the top level. Read either.
            trans = [t for t in (e.get("translations") or []) if t.get("language") == 2]
            name = (trans[0].get("name") if trans else e.get("name")) or ""
            desc = (trans[0].get("description") if trans else e.get("description")) or ""
            sid = match_skill(name)
            if not sid:
                continue
            equipment = [q.get("name", "").lower() for q in (e.get("equipment") or [])]
            if any(q not in ("none (bodyweight exercise)", "pull-up bar", "gym mat",
                             "parallel bars", "rings", "bench", "")
                   for q in equipment):
                continue
            lic = (e.get("license") or {}).get("short_name") or "CC BY-SA 4.0"
            author = e.get("license_author") or (trans[0].get("license_author") if trans else "") or "wger.de contributors"
            eid = e.get("id", "")
            out.append({
                "skill": sid, "source": "wger", "title": name,
                "url": f"https://wger.de/en/exercise/{eid}/view",
                "license": lic, "attribution": author,
                "summary": "",
                "instructions": sentences(desc),
                "muscles": [m.get("name_en") or m.get("name") for m in (e.get("muscles") or [])],
                "equipment": equipment,
                "level": "",
            })
    return out


def fetch_wger(raw: Path) -> list[dict]:
    pages = []
    offset = 0
    while True:
        url = f"{WGER_API}?language=2&limit=100&offset={offset}"
        page = json.loads(get(url, raw / f"wger_{offset}.json"))
        pages.append(page)
        if not page.get("next") or offset > 2000:
            break
        offset += 100
        time.sleep(0.5)
    return parse_wger(pages)


def parse_wikipedia(sid: str, title: str, data: dict) -> list[dict]:
    pages = (data.get("query") or {}).get("pages") or {}
    for p in pages.values():
        if "missing" in p or not p.get("extract"):
            continue
        extract = p["extract"]
        # First paragraph is the summary; the rest is where technique lives.
        paras = [x.strip() for x in extract.split("\n") if x.strip()]
        summary = paras[0] if paras else ""
        return [{
            "skill": sid, "source": "wikipedia", "title": p.get("title", title),
            "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(p.get("title", title).replace(" ", "_")),
            "license": LICENSES["wikipedia"][0],
            "attribution": "Wikipedia contributors",
            "summary": summary,
            "instructions": sentences(" ".join(paras[1:])),
            "muscles": [], "equipment": [], "level": "",
        }]
    return []


def fetch_wikipedia(raw: Path) -> list[dict]:
    out = []
    for sid, title in WIKI_PAGES.items():
        params = {"action": "query", "prop": "extracts", "explaintext": 1,
                  "redirects": 1, "titles": title, "format": "json"}
        url = WIKI_API + "?" + urllib.parse.urlencode(params)
        try:
            data = json.loads(get(url, raw / f"wikipedia_{sid}.json"))
        except RuntimeError as e:
            print(f"  [wikipedia] {title}: {e}", file=sys.stderr)
            continue
        out.extend(parse_wikipedia(sid, title, data))
        time.sleep(0.5)
    return out


# ---- YouTube captions ------------------------------------------------------
def vtt_to_text(vtt: str) -> str:
    """Flatten a WebVTT auto-caption file: drop timings and the rolling
    duplicates YouTube writes, keep one copy of each line in order."""
    lines = []
    last = ""
    for line in vtt.splitlines():
        line = re.sub(r"<[^>]+>", "", line).strip()
        if not line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        if re.match(r"^\d{2}:\d{2}:\d{2}\.\d{3} -->", line) or line.isdigit():
            continue
        if line != last:
            lines.append(line)
            last = line
    return " ".join(lines)


def fetch_transcripts(raw: Path, ledger: Path) -> list[dict]:
    if not ledger.exists():
        return []
    out = []
    with open(ledger) as f:
        rows = [r for r in csv.DictReader(f) if r.get("source", "").startswith("youtube")]
    for r in rows:
        sid = match_skill(r.get("trick", "").replace("_", " ")) or r.get("trick")
        if sid not in SKILLS:
            continue
        vid = re.search(r"v=([\w-]+)", r.get("page_url", "")) or None
        if not vid:
            continue
        vid = vid.group(1)
        cache = raw / f"yt_{vid}.txt"
        if not cache.exists():
            tmpl = str(raw / f"yt_{vid}")
            cmd = ["yt-dlp", "--skip-download", "--write-auto-subs", "--write-subs",
                   "--sub-langs", "en.*,en", "--sub-format", "vtt", "--no-warnings",
                   "-o", tmpl, r["page_url"]]
            try:
                subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            except (subprocess.TimeoutExpired, FileNotFoundError) as e:
                print(f"  [yt] {vid}: {e}", file=sys.stderr)
                continue
            vtts = sorted(raw.glob(f"yt_{vid}*.vtt"))
            if not vtts:
                continue
            cache.write_text(vtt_to_text(vtts[0].read_text(errors="ignore")))
            for v in vtts:
                v.unlink(missing_ok=True)
        text = cache.read_text()
        if len(text) < 200:
            continue
        out.append({
            "skill": sid, "source": "youtube_cc", "title": r.get("title", ""),
            "url": r.get("page_url", ""), "license": r.get("license") or LICENSES["youtube_cc"][0],
            "attribution": r.get("author", ""), "summary": "",
            # Captions are speech: sentence splitting is unreliable, so the
            # miner sees the whole text and the record keeps no "steps".
            "instructions": [], "transcript": text,
            "muscles": [], "equipment": [], "level": "",
        })
    return out


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------
def merge(records: list[dict]) -> dict:
    skills: dict[str, dict] = {}
    for r in records:
        sid = r["skill"]
        entry = skills.setdefault(sid, {
            "id": sid, "name": SKILLS[sid].name if sid in SKILLS else sid,
            "family": SKILLS[sid].family if sid in SKILLS else "",
            "measurable": bool(sid in SKILLS and SKILLS[sid].measurable),
            "summary": "", "instructions": [], "cues": [], "faults": [],
            "muscles": [], "equipment": [], "level": "", "sources": [],
        })
        text = " ".join(r.get("instructions") or []) + " " + (r.get("transcript") or "")
        cues, faults = mine(text)
        if r.get("summary") and not entry["summary"]:
            entry["summary"] = r["summary"]
        if r.get("instructions") and not entry["instructions"]:
            entry["instructions"] = list(r["instructions"])
        entry["cues"] = _dedupe(entry["cues"] + cues)
        entry["faults"] = _dedupe(entry["faults"] + faults)
        entry["muscles"] = _dedupe(entry["muscles"] + [m for m in r.get("muscles") or [] if m])
        entry["equipment"] = _dedupe(entry["equipment"] + [q for q in r.get("equipment") or [] if q])
        if r.get("level") and not entry["level"]:
            entry["level"] = r["level"]
        entry["sources"].append({
            "source": r["source"], "title": r.get("title", ""), "url": r.get("url", ""),
            "license": r.get("license", ""), "attribution": r.get("attribution", ""),
            "cues": len(cues), "faults": len(faults),
        })
    return dict(sorted(skills.items()))


def attribution_md(doc: dict) -> str:
    lines = ["# Technique sources", "",
             "Every sentence in `techniques.json` traces to one of these records. "
             "Cues and faults are *mined* from the text by sentence shape, not "
             "authored; treat them as quotations, not as barra's opinion.", ""]
    for name, (lic, url) in LICENSES.items():
        lines.append(f"- **{name}** - {lic} - {url}")
    lines += ["", "| skill | source | title | licence | attribution |", "|---|---|---|---|---|"]
    for sid, e in doc["skills"].items():
        for s in e["sources"]:
            lines.append(f"| {sid} | {s['source']} | [{s['title']}]({s['url']}) | "
                         f"{s['license']} | {s['attribution']} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="free_exercise_db,wger,wikipedia",
                    help="comma-separated: free_exercise_db, wger, wikipedia")
    ap.add_argument("--transcripts", action="store_true",
                    help="also mine auto-captions of the CC clips in data/calisthenics")
    ap.add_argument("--offline", action="store_true",
                    help="never download; rebuild from data/techniques/raw")
    ap.add_argument("--out", default=str(ROOT / "data" / "techniques"))
    a = ap.parse_args()

    out = Path(a.out)
    raw = out / "raw"
    out.mkdir(parents=True, exist_ok=True)
    wanted = [s.strip() for s in a.sources.split(",") if s.strip()]

    if a.offline:
        # Make every fetch a cache hit or a clear failure.
        global get
        _get = get

        def get(url, cache, retries=3, timeout=60):  # noqa: F811
            if cache.exists():
                return cache.read_bytes()
            raise RuntimeError(f"offline and not cached: {cache.name}")

    records: list[dict] = []
    status: dict[str, str] = {}
    fetchers = {"free_exercise_db": fetch_free_exercise_db,
                "wger": fetch_wger, "wikipedia": fetch_wikipedia}
    for name in wanted:
        fn = fetchers.get(name)
        if fn is None:
            print(f"unknown source {name!r}", file=sys.stderr)
            continue
        print(f"== {name}")
        try:
            got = fn(raw)
            records.extend(got)
            status[name] = f"ok, {len(got)} records"
            print(f"  {len(got)} matched records")
        except Exception as e:  # noqa: BLE001 - a dead source must not sink the rest
            status[name] = f"failed: {str(e)[:160]}"
            print(f"  FAILED: {e}", file=sys.stderr)
    if a.transcripts:
        print("== youtube_cc captions")
        got = fetch_transcripts(raw, ROOT / "data" / "calisthenics" / "metadata.csv")
        records.extend(got)
        status["youtube_cc"] = f"ok, {len(got)} transcripts"
        print(f"  {len(got)} transcripts")

    skills = merge(records)
    doc = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": ("Cues and faults are mined from the source text by sentence "
                 "shape. They are quotations with a licence, not measurements "
                 "and not barra's opinion."),
        "sources": {k: {"license": v[0], "url": v[1], "status": status.get(k, "not run")}
                    for k, v in LICENSES.items()},
        "skills": skills,
    }
    (out / "techniques.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    (out / "ATTRIBUTION.md").write_text(attribution_md(doc))
    measured = [s for s in skills if skills[s]["measurable"]]
    print(f"\n{len(skills)} skills documented ({len(measured)} of the measured six: "
          f"{', '.join(measured)}), {sum(len(e['cues']) for e in skills.values())} cues, "
          f"{sum(len(e['faults']) for e in skills.values())} faults -> {out / 'techniques.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
