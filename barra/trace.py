"""A record of how a decision was reached.

Every number this project reports is the end of a chain: frames become
keypoints, keypoints become a tracking signal, the signal becomes rep
boundaries, boundaries become metrics, metrics become a score. When one of
those numbers looks wrong, the only useful question is *which link broke*, and
answering it by re-reading the code is slow and unreliable.

So each stage records what it decided, the evidence it used, and the threshold
it compared that evidence against. Three things make this worth having rather
than being logging for its own sake:

  * **The threshold is recorded next to the value.** "rejected: wrist travel
    2.63 > 0.80 torso" is debuggable. "rejected candidate" is not.
  * **Rejections are first class.** The interesting failure is almost always
    something that was *nearly* a rep, and a log that only records successes
    cannot show it.
  * **It is always on.** A trace you have to enable is a trace you do not have
    when the thing you needed it for happened.

Cheap by construction: a few hundred small dicts per clip, no I/O unless asked,
and no numpy in the record itself so it serialises without special-casing.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = 1


def _plain(v: Any) -> Any:
    """Make a value JSON-safe without importing numpy at module scope.

    NaN and infinity are written as null: they are real outcomes here (a metric
    that could not be measured), and a trace that crashes on serialising one is
    a trace you lose exactly when it mattered.
    """
    if v is None or isinstance(v, (bool, str)):
        return v
    # numpy scalars subclass the Python numeric types, so an isinstance check
    # passes them straight through and they render as "np.float64(8.43)".
    # Convert explicitly rather than trusting the type test.
    if isinstance(v, int):
        return int(v)
    if isinstance(v, float):
        f = float(v)
        return f if f == f and abs(f) != float("inf") else None
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    for attr in ("item", "tolist"):                 # numpy scalars, then arrays
        if hasattr(v, attr):
            try:
                return _plain(getattr(v, attr)())
            except Exception:
                continue                            # .item() raises on arrays
    return str(v)


@dataclass
class Entry:
    stage: str
    kind: str                    # step | decision | reject | note | error
    at_ms: int
    message: str = ""
    data: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = {"stage": self.stage, "kind": self.kind, "atMs": self.at_ms}
        if self.message:
            d["message"] = self.message
        if self.data:
            d["data"] = self.data
        return d


class Trace:
    """Ordered record of one clip's journey through the pipeline."""

    def __init__(self, trace_id: str, subject: str = "", **context: Any) -> None:
        self.id = trace_id
        self.subject = subject
        self.context = _plain(context)
        self.entries: list[Entry] = []
        self._t0 = time.monotonic()
        self._stage = "start"

    # -- recording ---------------------------------------------------------
    def _add(self, kind: str, message: str, data: dict) -> None:
        self.entries.append(Entry(
            stage=self._stage, kind=kind,
            at_ms=int((time.monotonic() - self._t0) * 1000),
            message=message, data=_plain(data),
        ))

    def stage(self, name: str) -> "Trace":
        self._stage = name
        self._add("step", f"entered {name}", {})
        return self

    def step(self, message: str, **data: Any) -> None:
        self._add("step", message, data)

    def decision(self, outcome: str, why: str, **evidence: Any) -> None:
        """A choice, the reason for it, and the numbers behind the reason."""
        self._add("decision", why, {"outcome": outcome, **evidence})

    def reject(self, what: str, why: str, **evidence: Any) -> None:
        """Something that could have been a result and was not. The most
        valuable kind of entry: it is what you look for when a rep is missing."""
        self._add("reject", why, {"what": what, **evidence})

    def note(self, message: str, **data: Any) -> None:
        self._add("note", message, data)

    def error(self, message: str, **data: Any) -> None:
        self._add("error", message, data)

    # -- reading -----------------------------------------------------------
    @property
    def rejections(self) -> list[Entry]:
        return [e for e in self.entries if e.kind == "reject"]

    @property
    def errors(self) -> list[Entry]:
        return [e for e in self.entries if e.kind == "error"]

    def of_stage(self, name: str) -> list[Entry]:
        return [e for e in self.entries if e.stage == name]

    def as_dict(self) -> dict:
        return {
            "schema": SCHEMA,
            "traceId": self.id,
            "subject": self.subject,
            "context": self.context,
            "durationMs": self.entries[-1].at_ms if self.entries else 0,
            "counts": {
                k: sum(1 for e in self.entries if e.kind == k)
                for k in ("step", "decision", "reject", "note", "error")
            },
            "entries": [e.as_dict() for e in self.entries],
        }

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict(), indent=2))
        return path

    # -- rendering ---------------------------------------------------------
    def render(self, width: int = 96, show: str = "all") -> str:
        """Human-readable. `show="decisions"` drops the bookkeeping and leaves
        the choices and rejections, which is what you want nine times in ten."""
        return render(self.as_dict(), width=width, show=show)


def render(data: dict, width: int = 96, show: str = "all") -> str:
    """Render a trace from its dict form - live or read back off disk.

    One renderer, deliberately. There used to be two, and they had already
    drifted: replaying a trace printed 0.947131335735321 where the live run
    printed 0.9471. Since diffing two runs is one of the reasons traces are
    written at all, a formatting difference between the run and its replay
    shows up as a diff in every float on the clip.
    """
    keep = {"all": None, "decisions": {"decision", "reject", "error"},
            "problems": {"reject", "error"}}[show]
    out = [f"trace {data.get('traceId', '?')}  ·  {data.get('subject', '')}"]
    if data.get("context"):
        out.append("  " + "  ".join(f"{k}={v}" for k, v in data["context"].items()))
    stage = None
    for e in data.get("entries", []):
        if keep is not None and e["kind"] not in keep:
            continue
        if e["stage"] != stage:
            stage = e["stage"]
            out.append(f"\n[{stage}]")
        mark = {"decision": "->", "reject": " x", "error": " !",
                "note": "  ", "step": "  "}[e["kind"]]
        out.append(f" {e['atMs']:>5}ms {mark} {e.get('message', '')}"[:width])
        for k, v in (e.get("data") or {}).items():
            if k in ("outcome", "what"):
                continue
            out.append(f"            {k} = {_fmt(v)}"[:width])
    return "\n".join(out)


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.4g}"
    if isinstance(v, list) and len(v) > 8:
        return f"[{len(v)} values]"
    return str(v)


class NullTrace(Trace):
    """A trace that records nothing, for call sites that do not want one.

    Exists so every function can take a trace unconditionally instead of
    guarding each call with `if trace is not None`, which is where tracing
    quietly stops happening.
    """

    def __init__(self) -> None:
        super().__init__("null", "")

    def _add(self, kind: str, message: str, data: dict) -> None:
        return


def new_id(seed: str = "") -> str:
    """Short, sortable, and unique enough. Time-ordered so that traces from one
    session sort into the order they happened."""
    import hashlib

    stamp = f"{time.time():.6f}{seed}"
    return time.strftime("%y%m%d-%H%M%S") + "-" + \
        hashlib.sha256(stamp.encode()).hexdigest()[:6]
