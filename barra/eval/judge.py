"""LLM-as-a-judge for the prose surfaces, with a reference-check before it.

Two layers, deliberately cheap first:

  * reference_check - deterministic, free, always runs. The prose must quote
    the payload's own numbers and must not invent any. A write-up that
    claims "8 reps" for a 2-rep payload never reaches the judge: it has
    already failed, on evidence, without spending a cent.
  * judge - one nan model grades another's write-up against a rubric,
    returning strict JSON: per-criterion {id, score 0-2, quote, why}, an
    overall verdict, and the specific claims it could not verify. The
    judge is told what the grader cannot know (the clip itself) and is
    made to abstain per claim rather than guessing.

The judge never sees a score to agree with and is never asked for a
1-10 number; rubric scores are 0-2 per criterion (fail / partial / pass),
which is the granularity a rubric can actually defend.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

REQUEST_TIMEOUT = 90

JUDGE_MODEL = os.environ.get("BARRA_JUDGE_MODEL", "glm5.3-flash")

RUBRIC = [
    {"id": "faithful_numbers",
     "criterion": "Every number in the write-up appears in the measured "
                  "payload. No invented rep counts, scores or times."},
    {"id": "no_unsupported_claim",
     "criterion": "No claim the measurement does not support: no progress "
                  "claims from one session, no causes attributed to numbers, "
                  "no technique verdict presented as measured."},
    {"id": "honest_abstention",
     "criterion": "When the payload says a check was unobservable or the "
                  "clip produced no reps, the write-up says so instead of "
                  "papering over it."},
    {"id": "actionable",
     "criterion": "nextSession names one concrete thing to do or film, "
                  "grounded in what the payload measured."},
    {"id": "plain_language",
     "criterion": "Second person, plain sentences, no coaching slogans, "
                  "no filler, no metric dumps."},
]

SYSTEM = """You grade a short training write-up against its measured data. \
You are strict and evidence-bound: every judgment you make must quote the \
exact sentence that earned it. If the data does not contain something, the \
write-up claiming it is a fault - do not imagine the data being generous.

Score each criterion 0, 1 or 2: 0 = violated, 1 = partially, 2 = satisfied. \
For each, give `quote`: the exact fragment of the write-up you judged, and \
`why`: one sentence. Then give `verdict`: "pass" (all criteria >= 1 and \
faithful_numbers = 2), "borderline", or "fail" (faithful_numbers = 0). \
Finally `unverifiable`: claims a grader without the video cannot check - \
abstain there rather than penalising.

Return ONE JSON object, no prose around it:
{"criteria": [{"id": "...", "score": 0, "quote": "...", "why": "..."}],
 "verdict": "pass|borderline|fail",
 "unverifiable": ["..."]}"""


def _config() -> tuple[str, str] | None:
    base = (os.environ.get("BARRA_JUDGE_BASE_URL")
            or os.environ.get("NAN_BASE_URL") or "").rstrip("/")
    key = (os.environ.get("BARRA_JUDGE_API_KEY")
           or os.environ.get("NAN_API_KEY") or "")
    return (base, key) if base and key.strip() else None


def _chat(base: str, key: str, model: str, system: str, user: str) -> str | None:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.1,
    }).encode()
    req = urllib.request.Request(
        f"{base}/chat/completions", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": "barrapp-eval-judge/1.0"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode())["choices"][0]["message"]["content"]
    except (urllib.error.URLError, KeyError, IndexError, TypeError,
            json.JSONDecodeError, TimeoutError, OSError):
        return None


def parse_json_object(text: str | None) -> dict | None:
    """The one JSON object in a reply, or None. Tolerates fences."""
    if not text:
        return None
    s = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", s, re.S)
    if fence:
        s = fence.group(1).strip()
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        start, end = s.find("{"), s.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            obj = json.loads(s[start:end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None


# ---------------------------------------------------------------------------
# layer 1: deterministic reference check
# ---------------------------------------------------------------------------
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _payload_facts(payload: dict) -> set[str]:
    """The numbers the payload actually measured, as bare strings.

    Rep count, per-rep score boundaries, rep timings, metric values and the
    session score - the numbers a faithful write-up is allowed to quote.
    Deliberately generous: extra candidates only make the check weaker,
    never a false accusation, because layer 2 judges context.
    """
    facts: set[str] = set()
    def put(v) -> None:
        if isinstance(v, bool):
            return
        if isinstance(v, int):
            facts.update({str(v)})
        elif isinstance(v, float):
            facts.update({str(int(v)) if v == int(v) else f"{v:.2f}".rstrip("0").rstrip("."),
                          f"{v:.1f}", f"{v:.2f}", f"{v:.3f}"})
    put(payload.get("n_reps"))
    put(payload.get("sessionScore"))
    put(payload.get("duration_s"))
    for r in payload.get("reps") or []:
        for k in ("score", "startS", "turnS", "endS", "transition_s", "concentric_s"):
            put(r.get(k))
    return facts


def reference_check(payload: dict, prose: dict) -> dict:
    """Every number in the write-up must exist in the payload's facts.

    Returns {ok, invented: [{number, where}], quoted: n}. `ok` is False
    the moment one number appears in the prose that the payload never
    measured - that is hallucination caught deterministically.
    """
    facts = _payload_facts(payload)
    invented, quoted = [], 0
    for key in ("headline", "narrative", "nextSession"):
        text = prose.get(key) or ""
        for num in _NUM_RE.findall(text):
            if num in facts:
                quoted += 1
            else:
                invented.append({"number": num, "where": key})
    return {"ok": not invented, "invented": invented, "quoted": quoted}


# ---------------------------------------------------------------------------
# layer 2: the judge
# ---------------------------------------------------------------------------
def judge_writeup(payload: dict, prose: dict) -> dict:
    """Grade one write-up. Free deterministic check first, judge second.

    Without a configured judge endpoint, returns the reference check plus
    {"judged": False, "why": ...} - the layer still gates on hallucinated
    numbers, which need no model.
    """
    ref = reference_check(payload, prose)
    out: dict = {"reference": ref, "judged": False}
    if not ref["ok"]:
        out["verdict"] = "fail"
        out["why"] = "reference check: numbers in the prose the payload never measured"
        return out

    cfg = _config()
    if cfg is None:
        out["why"] = "no judge endpoint configured (NAN_BASE_URL / NAN_API_KEY)"
        return out
    base, key = cfg

    rubric = "\n".join(f"- {c['id']}: {c['criterion']}" for c in RUBRIC)
    user = (
        "The measured payload (the only ground truth):\n"
        + json.dumps(_measured_view(payload), indent=1, ensure_ascii=False)
        + "\n\nThe write-up to grade:\n"
        + json.dumps({k: prose.get(k) or "" for k in ("headline", "narrative", "nextSession")},
                     indent=1, ensure_ascii=False)
        + "\n\nRubric:\n" + rubric
    )
    raw = _chat(base, key, JUDGE_MODEL, SYSTEM, user)
    parsed = parse_json_object(raw)
    if parsed is None:
        out["why"] = "judge reply was not a JSON object"
        return out
    scores = {c.get("id"): c.get("score") for c in parsed.get("criteria") or []
              if isinstance(c, dict)}
    out.update({
        "judged": True,
        "model": JUDGE_MODEL,
        "scores": scores,
        "meanScore": (round(sum(s for s in scores.values() if isinstance(s, (int, float)))
                            / len(scores), 3) if scores else None),
        "verdict": parsed.get("verdict"),
        "unverifiable": parsed.get("unverifiable") or [],
        "criteria": parsed.get("criteria") or [],
    })
    return out


def _measured_view(payload: dict) -> dict:
    """The slice of the payload a judge needs: counts, scores, checks,
    blockers - not raw pose arrays."""
    reps = []
    for r in payload.get("reps") or []:
        reps.append({
            "label": r.get("label"), "score": r.get("score"),
            "band": r.get("band"),
            "startS": r.get("startS"), "endS": r.get("endS"),
            "transition_s": r.get("transition_s"), "concentric_s": r.get("concentric_s"),
            "faults": [f if isinstance(f, str) else f.get("errorId")
                       for f in (r.get("faults") or [])],
            "unmeasured": r.get("unmeasured"),
        })
    return {
        "exercise": (payload.get("detected") or {}).get("exercise") or payload.get("exercise"),
        "n_reps": payload.get("n_reps"),
        "sessionScore": payload.get("sessionScore"),
        "duration_s": payload.get("duration_s"),
        "blockers": payload.get("blockers") or [],
        "reps": reps,
    }
