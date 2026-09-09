"""The multimodal pass: a vision model studies the technique, given the evidence.

The measurement pipeline is geometric - pose landmarks in, numbers out - and
the text model that writes the prose only ever sees those numbers. This module
closes the gap: it shows a vision model stills that walk through the phases of
representative reps (see barra/frames.py) together with what was measured, and
asks for structured, frame-referenced observations it can abstain from.

Three rules, all of them about not letting a fluent model outrank a
measurement:

* The model's observations are ADVISORY and separately sourced. They never
  overwrite the geometric movement label, the rep count or a calibrated score;
  a disagreement with the geometry is recorded for review, not resolved here.
* Every response is validated against the registry: an observation must name
  a rule the detected movement defines, a rep the payload contains, frames the
  request actually sent and a phase the pipeline knows. Anything else is
  dropped and counted. Malformed JSON degrades to "no note", never to a failed
  job.
* Pose estimates are not called ground truth in the prompt, and the model is
  told what it cannot see: forces, muscle activation, joints the camera hides,
  phases no still shows, and the count or precise timing of fast reps from a
  handful of frames.

Optional by design. Without a key the pipeline behaves exactly as before.
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

REQUEST_TIMEOUT = 60
SOURCE_VISION = "vision-advisory"

# Statuses an observation may carry. `uncertain` is the model's abstention on
# one specific check; leaving a check out entirely is abstention as well.
OBSERVATION_STATUSES = ("observed", "not_observed", "unobservable", "uncertain")

SYSTEM = """You are barrapp's technique analyst. You look at stills that walk \
through the phases of a few representative repetitions (or holds) of one \
calisthenics set, alongside what a pose-estimation pipeline measured.

What you are given:
- The movement the geometry recognised, the technique variant if one was \
declared, each sampled rep's time boundaries and phases, the checks the \
geometry made (observed / not observed / could not be checked, and why), and \
every still labelled with its rep, phase and timestamp in the source video.

Rules:
- The measurements come from pose estimation. They are evidence, not ground \
truth. Do not restate or contradict a number; if what you SEE disagrees with a \
measurement or with the recognised movement, say so in `movement` or \
`observations`, and it will be reviewed rather than applied.
- Report only what is visible in the stills you were shown. Never claim \
anything about a phase no still shows, about forces, effort or muscle \
activation, or about a joint the camera hides. Do not count repetitions or \
give precise timings from sparse stills.
- For each technique error you can judge, give an observation with: errorId \
(from the list provided, exactly), rep (a label from the list), phase, status \
(observed / not_observed / unobservable / uncertain), frames (the file names \
of the stills that show it) and one sentence describing what is visible. \
Leaving an error out means you could not judge it. That is allowed.
- Second person, plain sentences, no coaching slogans, no filler.
Return one JSON object with keys: headline (one line), narrative (short \
paragraphs), nextSession (one sentence on what to film or attempt next), \
movement ({"label": what you see, "agreesWithGeometry": true/false}), and \
observations (a list as described, possibly empty)."""


SECOND_MODEL = "qwen3.8-flash"


def _config() -> tuple[str, str, str] | None:
    """(base_url, key, model) when a vision endpoint is configured."""
    base = (os.environ.get("BARRA_VISION_BASE_URL")
            or os.environ.get("NAN_BASE_URL") or "").rstrip("/")
    key = os.environ.get("BARRA_VISION_API_KEY") or os.environ.get("NAN_API_KEY") or ""
    model = os.environ.get("BARRA_VISION_MODEL", "glm5.3-flash")
    if base and key.strip():
        return base, key.strip(), model
    return None


def _chat(base: str, key: str, model: str, system: str, content: list[dict],
          timeout: int = REQUEST_TIMEOUT) -> str | None:
    """One OpenAI-compatible call; None on any failure, never a raise."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": content}],
        "temperature": 0.3,
    }).encode()
    req = urllib.request.Request(
        f"{base}/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 # Same lesson as the objectives chat: a script-looking client
                 # is answered by the provider's edge with a 403.
                 "User-Agent": "barrapp-vision/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        text = data["choices"][0]["message"]["content"]
        return text if isinstance(text, str) else None
    except (urllib.error.URLError, KeyError, IndexError, TypeError,
            json.JSONDecodeError, TimeoutError, OSError):
        return None


def parse_json_object(text: str | None) -> dict | None:
    """The one JSON object in a model reply, or None. Tolerates a code fence
    and leading prose; refuses anything that is not a single object."""
    if not text or not isinstance(text, str):
        return None
    s = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", s, re.S)
    if fence:
        s = fence.group(1).strip()
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        start, end = s.find("{"), s.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            obj = json.loads(s[start:end + 1])
        except json.JSONDecodeError:
            return None
    return obj if isinstance(obj, dict) else None


def _images(paths) -> list[dict]:
    out = []
    for path in paths:
        try:
            encoded = base64.b64encode(Path(path).read_bytes()).decode()
        except OSError:
            continue
        out.append({"type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}})
    return out


# ---------------------------------------------------------------------------
# The evidence-grounded request
# ---------------------------------------------------------------------------
def _known_rules(report: dict | None) -> list[dict]:
    try:
        from barra.rules import rules_for
    except ImportError:
        return []
    movement = (report or {}).get("exercise") or ""
    return [{"errorId": r.id, "name": r.name, "phase": r.phase,
             "observable": r.observable} for r in rules_for(movement)]


def _rep_summary(rep: dict) -> str:
    parts = [f"{rep.get('label')}: {rep.get('startS')}-{rep.get('endS')}s"]
    phases = rep.get("phases") or {}
    if phases:
        parts.append("phases " + ", ".join(
            f"{k} {v[0]}-{v[1]}s" for k, v in phases.items()
            if isinstance(v, (list, tuple)) and len(v) == 2 and k != "rep"))
    observed = [a for a in rep.get("assessments") or [] if a.get("status") == "observed"]
    blocked = [a for a in rep.get("assessments") or [] if a.get("status") == "unobservable"]
    if observed:
        parts.append("geometry observed: " + "; ".join(
            f"{a['errorId']} ({a['evidence'].get('primitive')}="
            f"{a['evidence'].get('value')} {a['evidence'].get('unit', '')}".strip()
            + f", {a['evidence'].get('comparison')} {a['evidence'].get('threshold')})"
            for a in observed))
    if blocked:
        parts.append("geometry could not check: " + "; ".join(
            f"{a['errorId']} ({(a.get('availability') or {}).get('reason', '')})"
            for a in blocked))
    if rep.get("assessmentBlocked"):
        parts.append(f"whole rep blocked: {rep['assessmentBlocked']}")
    return " | ".join(parts)


def _user_text(art, report: dict | None) -> str:
    report = report or {}
    lines = []
    detected = report.get("detected") or {}
    lines.append(f"Movement recognised by the geometry: {report.get('exercise', 'unknown')}"
                 + (f" ({detected.get('reason')})" if detected.get("reason") else ""))
    variant = report.get("variant") or {}
    lines.append(f"Variant: {variant.get('name', 'unspecified')} "
                 f"(source: {variant.get('source', 'none')}). If unspecified, do not "
                 "assume a strict or kipping standard; describe what is visible.")
    view = report.get("view") or {}
    if view:
        lines.append(f"Camera: {view.get('bin', 'UNKNOWN')} "
                     f"({'knowable' if view.get('knowable') else 'not knowable'}; "
                     f"{view.get('why', '')})")
    lines.append(f"Clip trimmed to the technique: "
                 f"{art.clip.name if getattr(art, 'clip', None) else 'cut unavailable'}.")
    selected = set(getattr(art, "selected_reps", []) or [])
    reps = [r for r in report.get("reps") or [] if not selected or r.get("label") in selected]
    if reps:
        lines.append("Sampled repetitions (all times are in the source video):")
        for rep in reps:
            lines.append("- " + _rep_summary(rep))
    rules = _known_rules(report)
    if rules:
        lines.append("Technique errors you may report, by errorId (use these exactly):")
        for r in rules:
            lines.append(f"- {r['errorId']} [{r['phase']}]: {r['name']} - {r['observable']}")
    lines.append("Stills, in order (file: rep, phase, moment, timestamp):")
    for s in getattr(art, "frames", []):
        lines.append(f"- {s.path.name}: {s.rep or 'window'}, {s.phase}, {s.moment}, {s.t_s:.2f}s")
    lines.append("Assess the technique these stills show and return the JSON "
                 "object described in the system message.")
    return "\n".join(lines)


def validate_observations(raw, report: dict | None, art) -> tuple[list[dict], dict]:
    """Keep only observations that reference things the request contained.

    Returns (kept, dropped_counts). A rejected observation is counted by why
    it was rejected, so the invalid-response rate can be tracked per reason.
    """
    dropped = {"notAList": 0, "notAnObject": 0, "unknownError": 0,
               "unknownRep": 0, "badStatus": 0, "unknownFrame": 0,
               "unknownPhase": 0}
    if not isinstance(raw, list):
        dropped["notAList"] = 1
        return [], dropped
    rule_ids = {r["errorId"]: r for r in _known_rules(report)}
    reps = {str(r.get("label")): r for r in (report or {}).get("reps") or []}
    frames = {s.path.name for s in getattr(art, "frames", [])}
    phases = set()
    for r in reps.values():
        phases.update((r.get("phases") or {}).keys())
    phases.update({"setup", "lowering", "lifting", "transition", "support",
                   "turnaround", "hold", "onset", "sustained", "exit", "rep"})
    kept = []
    for obs in raw:
        if not isinstance(obs, dict):
            dropped["notAnObject"] += 1
            continue
        error_id = str(obs.get("errorId", ""))
        if error_id not in rule_ids:
            dropped["unknownError"] += 1
            continue
        rep = str(obs.get("rep", ""))
        if rep not in reps:
            dropped["unknownRep"] += 1
            continue
        status = str(obs.get("status", "")).strip().lower().replace(" ", "_")
        if status not in OBSERVATION_STATUSES:
            dropped["badStatus"] += 1
            continue
        refs = obs.get("frames") or []
        if not isinstance(refs, list):
            refs = [refs]
        refs = [str(f) for f in refs]
        if any(f not in frames for f in refs):
            dropped["unknownFrame"] += 1
            continue
        phase = str(obs.get("phase") or rule_ids[error_id]["phase"])
        if phase not in phases:
            dropped["unknownPhase"] += 1
            continue
        kept.append({
            "rep": rep,
            "errorId": error_id,
            "name": rule_ids[error_id]["name"],
            "phase": phase,
            "status": status,
            "frames": refs,
            "description": str(obs.get("description") or "").strip()[:300],
            "source": SOURCE_VISION,
        })
    return kept, dropped


def technique_note(art, report: dict | None = None) -> dict | None:
    """{headline, narrative, nextSession, visionObservations, visionMovement,
    visionValidation} from the stills and the evidence, or None.

    `report` is the measured payload. Without it the request still runs, but
    the model is told nothing about the geometry and no observation can be
    validated against it - which is why callers should pass it.
    """
    cfg = _config()
    if cfg is None or not art or not getattr(art, "stills", None):
        return None
    base, key, model = cfg

    content: list[dict] = [{"type": "text", "text": _user_text(art, report)}]
    content += _images(art.stills)
    if len(content) < 2:
        return None

    text = _chat(base, key, model, SYSTEM, content)
    parsed = parse_json_object(text)
    if parsed is None:
        return None

    note = {k: str(parsed.get(k) or "").strip() for k in
            ("headline", "narrative", "nextSession")}
    if not note["narrative"]:
        return None

    observations, dropped = validate_observations(parsed.get("observations"), report, art)
    note["visionObservations"] = observations
    note["visionValidation"] = {
        "model": model, "kept": len(observations), "dropped": dropped,
        "invalid": sum(dropped.values()),
    }
    movement = parsed.get("movement")
    geometry = (report or {}).get("exercise") or ""
    if isinstance(movement, dict):
        seen = str(movement.get("label") or "").strip()
        agrees = movement.get("agreesWithGeometry")
        note["visionMovement"] = {
            "label": seen[:80],
            "agreesWithGeometry": bool(agrees) if isinstance(agrees, bool) else None,
            "geometry": geometry,
            "review": bool(isinstance(agrees, bool) and not agrees),
        }
    return note


# ---- key moment 1: counting when the geometry found nothing ---------------

COUNT_SYSTEM = """You are counting repetitions of one calisthenics movement from stills taken across one video, in order. Rules:
- Count a repetition only where you can see the body having left the rest position and returned to it, or clearly mid-way through doing so.
- Half-seen reps count as one only if the body is visibly far from rest.
- Do not count setup, walking, adjusting grip, or resting between reps.
- Sparse stills cannot show every rep of a fast set; if you cannot tell, say so in the note and give your best count.
Return JSON exactly: {"reps": <int>, "note": "<one line>"}"""

COUNT_USER = ("These {n} stills are spread evenly across one clip of {move}, in order. "
              "Count the repetitions and return the JSON object.")


def parse_count(text: str | None) -> int | None:
    """The `reps` integer from a count reply, or None. Schema, not substring:
    a reply that says "I count 3 or 4" no longer becomes 3."""
    obj = parse_json_object(text)
    if obj is None:
        return None
    reps = obj.get("reps")
    if isinstance(reps, bool) or not isinstance(reps, (int, float)):
        return None
    if isinstance(reps, float) and not reps.is_integer():
        return None
    reps = int(reps)
    return reps if 0 <= reps <= 200 else None


def reconcile_counts(answers: dict[str, int]) -> dict | None:
    """Turn per-model counts into one explicit verdict.

    Two answers within one of each other: the LOWER is used and the range is
    recorded - a rep half out of frame is not assumed to be a rep. Two answers
    further apart: no count is claimed; the disagreement is the result. One
    answer: used, labelled single-sourced.
    """
    if not answers:
        return None
    values = sorted(answers.values())
    if len(values) >= 2:
        lo, hi = values[0], values[-1]
        if hi - lo <= 1:
            return {"reps": lo, "range": [lo, hi], "models": answers,
                    "agreement": ("both models agree" if hi == lo else
                                  "the models agree within one; the lower count is used"),
                    "usable": True}
        return {"reps": None, "range": [lo, hi], "models": answers,
                "agreement": f"the models disagree ({lo} vs {hi}); no count is claimed",
                "usable": False}
    (name, reps), = answers.items()
    return {"reps": reps, "range": [reps, reps], "models": answers,
            "agreement": f"single model answered ({name})", "usable": True}


def count_from_clip(video_path, out_dir) -> dict | None:
    """The two-model count over stills spread across the whole clip.

    Two models, because one model guessing is a coin with opinions. The result
    carries `usable`: False when they disagree by more than one, in which case
    `reps` is None and the caller must not report a count.
    """
    cfg = _config()
    if cfg is None:
        return None
    base, key, model = cfg
    try:
        from barra.frames import grab_stills
        import subprocess
        duration = float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(video_path)],
            capture_output=True, text=True).stdout.strip() or 0)
        if duration <= 0:
            return None
        moments = [duration * (i + 0.5) / 8 for i in range(8)]
        stills = grab_stills(video_path, moments, out_dir, prefix="count")
    except Exception:  # noqa: BLE001
        return None
    if not stills:
        return None

    content: list[dict] = [{"type": "text",
                            "text": COUNT_USER.format(n=len(stills), move="the movement")}]
    content += _images(stills)
    if len(content) < 2:
        return None

    answers: dict[str, int] = {}
    invalid: list[str] = []
    for m in dict.fromkeys((model, SECOND_MODEL)):
        text = _chat(base, key, m, COUNT_SYSTEM, content)
        if not text:
            continue
        reps = parse_count(text)
        if reps is None:
            invalid.append(m)
            continue
        answers[m] = reps
    out = reconcile_counts(answers)
    if out is not None and invalid:
        out["invalidResponses"] = invalid
    return out


# ---- key moment 2: a second opinion on the technique verdict ---------------

VERDICT_USER = ("From these stills of one set, give the overall technique verdict. "
                'Return JSON exactly: {"verdict": "clean" | "minor" | "major"}')

VERDICTS = ("clean", "minor", "major")


def parse_verdict(text: str | None) -> str | None:
    """clean / minor / major, or None. The JSON field first; failing that,
    exactly one distinct verdict word in the reply - "not clean, minor" is
    ambiguous and returns None rather than "clean"."""
    obj = parse_json_object(text)
    if obj is not None:
        v = str(obj.get("verdict", "")).strip().lower()
        return v if v in VERDICTS else None
    if not text:
        return None
    found = {w for w in re.findall(r"\b(clean|minor|major)\b", text.lower())}
    return found.pop() if len(found) == 1 else None


def technique_second_opinion(art) -> str | None:
    """clean / minor / major from the second model, for cross-reading the
    primary's verdict. None when it cannot answer."""
    cfg = _config()
    if cfg is None or not art or not getattr(art, "stills", None):
        return None
    base, key, _ = cfg
    content: list[dict] = [{"type": "text", "text": VERDICT_USER}]
    content += _images(art.stills)
    if len(content) < 2:
        return None
    return parse_verdict(_chat(base, key, SECOND_MODEL, SYSTEM, content))
