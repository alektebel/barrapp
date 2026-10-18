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
  a rule the detected movement defines for the clip's variant, a rep the
  payload contains and a phase the pipeline knows. A fault claimed as
  observed must cite stills the request actually sent, each showing the rep
  and phase the claim attributes it to, and say in words what is visible; an
  abstention needs no stills, but its reason must be stated. Anything else
  is dropped and counted. Malformed JSON degrades to "no note", never to a
  failed job.
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
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:  # worker/task root
    from nan_secret import get_nan_key
except ImportError:  # tests / local dev with `server/` on the path
    from api.nan_secret import get_nan_key

try:
    import llm
except ImportError:
    from api import llm

REQUEST_TIMEOUT = 60
SOURCE_VISION = "vision-advisory"

# Localization is the one place the model is asked about time, not technique:
# where in the clip the set actually happens. Defaults to MiMo, the model the
# offline labeller (scripts/label_calisthenics.py) measured this task with.
#
# One default for every vision pass. mimo-v2.5 was retired by nan.builders on
# or before 2026-09-17 and answered 401 for four weeks before anyone knew;
# tests/test_vision_errors.py pins this against template.yaml.
VISION_MODEL_DEFAULT = "mimo-v2.6-flash"
LOCALIZE_MODEL_DEFAULT = VISION_MODEL_DEFAULT
# Localization feeds fusion, which waits for it only until pose ends plus
# process.VISION_VOTE_WAIT_S (~80 s on a 20 s clip). One bounded try per
# model keeps both inside that: 120 s x 3 attempts on a slow primary used the
# whole budget, the fallback never ran, and 5-15% of jobs lost the vision vote
# (a clean push-up set came back "no hemos podido confirmar qué ejercicio es").
LOCALIZE_TIMEOUT = 30
LOCALIZE_ATTEMPTS = 1
MIN_WINDOW_S = 4.0
MAX_WINDOW_FRAC = 0.95

# Statuses an observation may carry. `uncertain` is the model's abstention on
# one specific check; leaving a check out entirely is abstention as well.
OBSERVATION_STATUSES = ("observed", "not_observed", "unobservable", "uncertain")

SYSTEM = """You are barrapp's technique analyst. You look at stills that walk \
through the phases of a few representative repetitions (or holds) of one \
calisthenics set, alongside what a pose-estimation pipeline measured.

LANGUAGE: write every free-text value (headline, narrative, nextSession and \
each observation's description) in Spanish from Spain, second person. Keep \
JSON keys, rule ids, rep labels, frame names and status values exactly as \
specified - they are codes, not prose.

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
of the stills that show it) and description (one sentence saying what is \
visible). Leaving an error out means you could not judge it. That is allowed.
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
    key = (os.environ.get("BARRA_VISION_API_KEY") or get_nan_key()).strip()
    model = os.environ.get("BARRA_VISION_MODEL", VISION_MODEL_DEFAULT)
    # The key comes from nan.builders; an unset base should mean that provider,
    # not "vision off". A deployment that pointed BARRA_VISION_BASE_URL
    # elsewhere still wins, because that variable is checked first.
    if not base:
        base = "https://api.nan.builders/v1"
    if key:
        return base, key, model
    return None


# The provider's edge 403s clients that look like a script. The labellers use a
# browser UA for exactly this reason; the vision calls do too.
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

# Empty replies are a real, observed failure of the reasoning model: it spends
# the completion budget on reasoning tokens and returns a 200 whose content is
# "". Retrying is cheap next to dropping the pass.
CHAT_ATTEMPTS = 3


# Every call goes through the one client (api/llm.py): the cause of a failure,
# the retry policy, the /models guard and the metric line all live there.
ChatResult = llm.ChatResult
last_error = llm.last_error
reset_state = llm.reset_state


def skip_reason() -> str:
    """Why a vision pass produced nothing, for the trace: unconfigured, a call
    that failed (with its cause), or a reply that did not parse."""
    if _config() is None:
        return "not_configured"
    if llm.last_error():
        return f"call_failed: {llm.last_error()}"
    return "no_usable_reply"


def _chat_result(base: str, key: str, model: str, system: str, content: list[dict],
                 timeout: int = REQUEST_TIMEOUT, attempts: int = CHAT_ATTEMPTS,
                 check_model: bool = True) -> ChatResult:
    return llm.complete(model, [{"role": "user", "content": content}], system=system,
                        base=base, key=key, timeout=timeout, attempts=attempts,
                        check_model=check_model)


def _chat(base: str, key: str, model: str, system: str, content: list[dict],
          timeout: int = REQUEST_TIMEOUT, attempts: int = CHAT_ATTEMPTS,
          check_model: bool = True) -> str | None:
    """The reply text, or None; the cause of a None is in last_error()."""
    return _chat_result(base, key, model, system, content, timeout, attempts,
                        check_model=check_model).text


def _strip_keys(obj):
    """Whitespace around a JSON key is never intentional - MiMo emitted
    `" narrative"` on a real reply, which silently failed every `.get(
    "narrative")` and dropped the whole note. Normalized once, here."""
    if isinstance(obj, dict):
        return {(k.strip() if isinstance(k, str) else k): _strip_keys(v)
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_keys(v) for v in obj]
    return obj


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
    return _strip_keys(obj) if isinstance(obj, dict) else None


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
    report = report or {}
    movement = report.get("exercise") or ""
    variant = (report.get("variant") or {}).get("name") or ""
    # `applies` is the registry's own verdict for the clip's variant, the one
    # the geometry assesses under: a rule written for another standard cannot
    # be reported against this clip, whatever the model saw in the stills.
    return [{"errorId": r.id, "name": r.name, "phase": r.phase,
             "observable": r.observable, "correction": r.correction,
             "applies": r.applies_to(variant)}
            for r in rules_for(movement)]


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
    # The per-rep biometrics the geometry produced. These are what the model
    # is meant to reason over: a rubric question ("is the lockout complete?")
    # answered with the number the camera measured behind it, not a stranger's
    # impression of a few stills. They stay evidence, never ground truth.
    metrics = rep.get("metrics") or []
    if metrics:
        parts.append("measured: " + "; ".join(str(m) for m in metrics))
    if rep.get("score") is not None:
        parts.append(f"rep score {rep['score']}/100 ({rep.get('band', '')})".strip())
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
    if report.get("sessionScore") is not None:
        lines.append(f"Session score: {report['sessionScore']}/100 "
                     f"({report.get('sessionBand', '')}).")
    if report.get("consistency"):
        lines.append("Set consistency (coefficient of variation): "
                     + json.dumps(report["consistency"]))
    rules = _known_rules(report)
    if rules:
        lines.append("Technique errors you may report, by errorId (use these exactly):")
        for r in rules:
            lines.append(f"- {r['errorId']} [{r['phase']}]: {r['name']} - "
                         f"{r['observable']} Fix: {r['correction']}")
    lines.append("Stills, in order (file: rep, phase, moment, timestamp):")
    for s in getattr(art, "frames", []):
        lines.append(f"- {s.path.name}: {s.rep or 'window'}, {s.phase}, {s.moment}, {s.t_s:.2f}s")
    lines.append("Assess the technique these stills show and return the JSON "
                 "object described in the system message.")
    return "\n".join(lines)


def _frame_shows(still, rep: str, phase: str) -> bool:
    """Whether a still can back a claim about `rep` in `phase`: it must be a
    still of that rep, showing that phase - except for the rules scoped to
    the whole rep or hold (phase "rep"/"hold"), whose claim covers every
    moment of it, so any still of that rep shows what they claim."""
    if (still.rep or "") != rep:
        return False
    return phase in ("rep", "hold") or still.phase == phase


def validate_observations(raw, report: dict | None, art) -> tuple[list[dict], dict]:
    """Keep only observations that reference things the request contained, and
    whose evidence corresponds to the claim.

    Returns (kept, dropped_counts). A rejected observation is counted by why
    it was rejected, so the invalid-response rate can be tracked per reason.

    A fault claimed as `observed` is the strong case: it must cite at least
    one still the request actually sent, every still it cites must show the
    rep and the phase the claim attributes it to, and it must state the
    visible fact in words. The abstentions (`not_observed`, `unobservable`,
    `uncertain`) are held to less - no stills required, but the reason is.
    """
    dropped = {"notAList": 0, "notAnObject": 0, "unknownError": 0,
               "variantMismatch": 0, "unknownRep": 0, "badStatus": 0,
               "noFrames": 0, "unknownFrame": 0, "frameMismatch": 0,
               "unknownPhase": 0, "noDescription": 0}
    if not isinstance(raw, list):
        dropped["notAList"] = 1
        return [], dropped
    rule_ids = {r["errorId"]: r for r in _known_rules(report)}
    reps = {str(r.get("label")): r for r in (report or {}).get("reps") or []}
    frames = {s.path.name: s for s in getattr(art, "frames", [])}
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
        if not rule_ids[error_id]["applies"]:
            dropped["variantMismatch"] += 1
            continue
        rep = str(obs.get("rep", ""))
        if rep not in reps:
            dropped["unknownRep"] += 1
            continue
        status = str(obs.get("status", "")).strip().lower().replace(" ", "_")
        if status not in OBSERVATION_STATUSES:
            dropped["badStatus"] += 1
            continue
        phase = str(obs.get("phase") or rule_ids[error_id]["phase"])
        if phase not in phases:
            dropped["unknownPhase"] += 1
            continue
        refs = obs.get("frames") or []
        if not isinstance(refs, list):
            refs = [refs]
        refs = [str(f) for f in refs]
        if status == "observed" and not refs:
            dropped["noFrames"] += 1
            continue
        if any(f not in frames for f in refs):
            dropped["unknownFrame"] += 1
            continue
        if any(not _frame_shows(frames[f], rep, phase) for f in refs):
            dropped["frameMismatch"] += 1
            continue
        description = str(obs.get("description") or "").strip()[:300]
        if not description:
            dropped["noDescription"] += 1
            continue
        kept.append({
            "rep": rep,
            "errorId": error_id,
            "name": rule_ids[error_id]["name"],
            "phase": phase,
            "status": status,
            "frames": refs,
            "description": description,
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

    models = list(dict.fromkeys((model, SECOND_MODEL)))

    def ask(m: str) -> tuple[str, int | None, bool]:
        # The completion endpoint is authoritative for model availability.
        # Skip the standalone /models request and ask both independent count
        # models concurrently; this path is already a last-resort rescue.
        text = _chat(base, key, m, COUNT_SYSTEM, content, check_model=False)
        reps = parse_count(text)
        return m, reps, bool(text and reps is None)

    answers: dict[str, int] = {}
    invalid: list[str] = []
    with ThreadPoolExecutor(max_workers=len(models)) as pool:
        for m, reps, invalid_response in pool.map(ask, models):
            if invalid_response:
                invalid.append(m)
            elif reps is not None:
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


# ---- localizing the exercise inside the raw clip --------------------------
# The offline labeller (scripts/label_calisthenics.py) already does this with
# MiMo: sample timestamped frames and ask for the window where the technique
# is actually performed, excluding intros and talking heads. This is that same
# question, asked in the worker so the stored clip can be the set and not the
# walk to the bar.

LOCALIZE_SYSTEM = """You find where an exercise is actually performed inside \
one training clip.

You are shown stills sampled at fixed timestamps from a single clip, in time \
order. Clips often open or close with an intro, a talking head, a title card, \
a person walking to the equipment, or resting. Return the time window that \
contains ONLY the active performance of the exercise.

Rules:
- technique_start is the first sampled timestamp where the person is visibly \
performing the exercise.
- technique_end is the last sampled timestamp where the exercise is still \
visible.
- Exclude intros, talking heads, text cards, rest between sets, and walking.
- If the exercise is never performed, set detected_exercise to "none" and \
technique_start = technique_end = 0.
- Both timestamps must come from the list of frame timestamps you were given.
Return ONE JSON object, no markdown fences:
{"detected_exercise": "<movement name or none>", "agrees": true|false, \
"technique_start": <seconds>, "technique_end": <seconds>, \
"reps_estimate": <integer>, "description": "<one sentence: viewpoint, \
equipment, what happens>"}"""


CLASSIFY_SYSTEM = """You identify a calisthenics movement from stills of one \
clip, by answering ONE question at a time.

You are shown frames sampled in time order from a single clip. Answer only the \
question you are asked, from the options given, describing what the frames \
actually show. Do not name the exercise; later questions will narrow it down.

Choose "unclear" whenever the frames do not settle the question. That is a \
real answer and a useful one - a wrong confident choice sends every later \
question down the wrong branch, and there is no way back up."""


def classify_movement(frames, log=None) -> dict | None:
    """Name the movement by walking the decision tree, one small question each.

    Returns the walk as a dict - the skill id when it reached one, and always
    the path of questions and answers that got there - or None when no vision
    endpoint is configured.

    The path is the reason this exists. The single-shot classifier it replaces
    answered with a free-text name and a confidence, so a wrong answer could
    not be attributed to anything; here a muscle-up misread as a pull-up is
    visibly a wrong answer to "what is happening while hanging", which is a
    question you can improve.

    `frames` is a list of image paths, already sampled. `log` is an optional
    callable for one line per question, which the labelling tools use to show
    the reasoning as it happens.
    """
    from barra.movement_tree import prompt_for, walk

    cfg = _config()
    if cfg is None:
        return None
    base, key, model = cfg
    images = _images(list(frames))
    if not images:
        return None

    def ask(node) -> str:
        content = [{"type": "text", "text": prompt_for(node)}] + images
        text = _chat(base, key, model, CLASSIFY_SYSTEM, content)
        parsed = parse_json_object(text) or {}
        choice = str(parsed.get("choice") or "").strip()
        if log:
            log(f"{node.id}: {choice or '(no answer)'} "
                f"- {str(parsed.get('why') or '')[:80]}")
        return choice

    result = walk(ask)
    out = result.as_trace()
    out["model"] = model
    return out


def _as_float(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def window_from_verdict(parsed: dict, duration: float,
                        model: str = "") -> dict:
    """Turn a localization reply into a window, or a `usable: False` record.

    The window must be a real stretch of footage (at least MIN_WINDOW_S) that
    is meaningfully shorter than the clip - a reply covering the whole clip is
    not a localization and trimming to it would only re-encode for nothing.
    """
    start = _as_float(parsed.get("technique_start"))
    end = _as_float(parsed.get("technique_end"))
    detected = str(parsed.get("detected_exercise")
                   or parsed.get("detected_trick") or "").strip()
    out = {
        "exercise": detected,
        "startS": start,
        "endS": end,
        "durationS": round(float(duration), 2),
        "repsEstimate": (int(parsed["reps_estimate"])
                         if isinstance(parsed.get("reps_estimate"), (int, float))
                         and not isinstance(parsed.get("reps_estimate"), bool)
                         else None),
        "description": str(parsed.get("description") or "").strip()[:300],
        "model": model,
        "agrees": (bool(parsed["agrees"])
                   if isinstance(parsed.get("agrees"), bool) else None),
        "usable": False,
    }
    if start is None or end is None or duration <= 0:
        return out
    start = max(0.0, min(start, duration))
    end = max(0.0, min(end, duration))
    out["startS"], out["endS"] = round(start, 2), round(end, 2)
    span = end - start
    out["usable"] = bool(MIN_WINDOW_S <= span < duration * MAX_WINDOW_FRAC)
    return out


def locate_exercise(video_path, out_dir, movement: str | None = None) -> dict | None:
    """Where the exercise is: MiMo's window over sampled stills, or None.

    Reads duration with OpenCV and grabs frames with the same decoder the pose
    path uses, so it needs no ffmpeg/ffprobe. Any failure - no endpoint, no
    frames, malformed reply - returns None and the caller keeps the raw clip.
    """
    cfg = _config()
    if cfg is None:
        print("[barra] locate: no vision endpoint/key; keeping the raw clip",
              flush=True)
        return None
    if os.environ.get("BARRA_LOCALIZE", "1").strip().lower() in (
            "0", "false", "no", "off"):
        return None
    base, key, _ = cfg
    model = os.environ.get("BARRA_LOCALIZE_MODEL", LOCALIZE_MODEL_DEFAULT)
    try:
        from barra.frames import grab_frames
        from barra.ingest import probe_video
    except ImportError:
        return None

    try:
        info = probe_video(Path(video_path))
        duration = float(info.get("duration_s") or 0.0)
        if not info.get("ok") or duration <= 0:
            return None
        n = 10 if duration > 40 else 6
        moments = [round(duration * (i + 0.5) / n, 2) for i in range(n)]
        grabbed = grab_frames(Path(video_path), moments, Path(out_dir), prefix="locate")
        if not grabbed:
            return None
        frames = sorted(((moments[i], p) for i, p in grabbed), key=lambda x: x[0])
    except Exception as exc:  # noqa: BLE001 - localization is best-effort
        print(f"[barra] locate: could not sample frames: {exc}", flush=True)
        return None

    frame_list = "\n".join(f"  frame {i + 1}: t={t}s"
                           for i, (t, _) in enumerate(frames))
    claimed = (f'\nThe athlete says the movement is "{movement}".'
               if movement and movement != "auto" else "")
    user = (f"These frames were sampled at fixed timestamps from ONE clip, in "
            f"time order (claimed duration {duration:.1f}s):\n{frame_list}{claimed}\n\n"
            "Return the JSON object described in the system message.")
    content: list[dict] = [{"type": "text", "text": user}]
    content += _images([p for _, p in frames])
    if len(content) < 2:
        return None
    text = _chat(base, key, model, LOCALIZE_SYSTEM, content,
                 timeout=LOCALIZE_TIMEOUT, attempts=LOCALIZE_ATTEMPTS, check_model=False)
    parsed = parse_json_object(text)
    if parsed is None:
        print(f"[barra] locate: no JSON in the {model} reply "
              f"({len(text or '')} chars)", flush=True)
        # The reasoning model sometimes returns an empty 200 even after the
        # retries; without a second opinion the vision vote is lost.
        if model != SECOND_MODEL:
            text = _chat(base, key, SECOND_MODEL, LOCALIZE_SYSTEM, content,
                         timeout=LOCALIZE_TIMEOUT, attempts=LOCALIZE_ATTEMPTS,
                         check_model=False)
            parsed = parse_json_object(text)
            if parsed is None:
                print(f"[barra] locate: no JSON in the {SECOND_MODEL} reply "
                      f"({len(text or '')} chars)", flush=True)
                return None
            model = SECOND_MODEL
            print(f"[barra] locate: answered by fallback {model}", flush=True)
        else:
            return None
    out = window_from_verdict(parsed, duration, model)
    print(f"[barra] locate: {out.get('exercise') or '?'} "
          f"{out.get('startS')}-{out.get('endS')}s of {duration:.1f}s "
          f"usable={out['usable']}", flush=True)
    return out
