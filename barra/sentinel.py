"""The sentinel: check a stage's output against its contract, and say so.

    verdict = sentinel.watch(trace, "segments", {"found": found},
                             inputs={"frames": n}, n_frames=n)

Every call writes one `sentinel` entry to the trace: the stage, a compact
summary of what went in and what came out, and the verdict with its
violations. That is what `barra explain --replay` shows per stage, so "what
did this step receive and return, and was it sane" has an answer for every
run in production, not only the ones someone was watching.

BARRA_SENTINEL selects what a violation does:
  strict  raise SentinelError - tests, the corpus and the canary clips, where
          a broken invariant must fail the run that produced it;
  record  (default) record it, print one parseable log line for the
          CloudWatch metric, and return; the caller decides what to do with
          a fatal one.
A check that crashes is itself a violation (`check_crashed`): in strict mode
it raises, in record mode it never takes a job down.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable

from .contracts import CONTRACTS, Violation

_MAX_LIST = 12
_MAX_STR = 200


class SentinelError(AssertionError):
    """A stage broke its contract while BARRA_SENTINEL=strict."""


@dataclass(frozen=True)
class Verdict:
    stage: str
    violations: list[Violation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    @property
    def fatal(self) -> bool:
        return any(v.fatal for v in self.violations)


def mode() -> str:
    m = os.environ.get("BARRA_SENTINEL", "record").strip().lower()
    return m if m in ("strict", "record") else "record"


def summarise(value: Any, depth: int = 0) -> Any:
    """A trace-sized picture of a value: arrays become their shape, long lists
    their length and head, long strings their prefix."""
    shape = getattr(value, "shape", None)
    if shape is not None and hasattr(value, "dtype"):
        if getattr(value, "ndim", 0) == 0:
            return value.item()
        return {"type": "ndarray", "shape": [int(s) for s in shape]}
    if isinstance(value, dict):
        if depth >= 3:
            return {"type": "dict", "keys": len(value)}
        return {str(k): summarise(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        if len(value) > _MAX_LIST or depth >= 3:
            return {"type": "list", "len": len(value),
                    "head": [summarise(v, depth + 1) for v in list(value)[:3]]}
        return [summarise(v, depth + 1) for v in value]
    if isinstance(value, str) and len(value) > _MAX_STR:
        return value[:_MAX_STR] + "…"
    return value


def watch(trace, stage: str, outputs: dict, *, inputs: dict | None = None,
          check: Callable[..., list[Violation]] | None = None,
          subject: Any = None, **context: Any) -> Verdict:
    """Run `check` (default: the registered contract for `stage`) on the
    stage's output and record the verdict.

    `outputs` is what the stage produced, as a dict for the trace; the value
    handed to the check is `subject` when given, else the single value of
    `outputs`, else `outputs` itself. `context` goes to the check only.
    """
    fn = check or CONTRACTS.get(stage)
    if subject is None:
        subject = next(iter(outputs.values())) if len(outputs) == 1 else outputs
    try:
        violations = list(fn(subject, **context)) if fn else []
    except Exception as exc:  # noqa: BLE001 - a broken check is a finding, not a crash
        violations = [Violation(stage, "check_crashed", f"{type(exc).__name__}: {exc}"[:_MAX_STR])]
    verdict = Verdict(stage, violations)

    if trace is not None:
        trace.sentinel(stage, ok=verdict.ok,
                       inputs=summarise(inputs or {}),
                       outputs=summarise(outputs),
                       violations=[v.as_dict() for v in violations])
    if not verdict.ok:
        rules = ",".join(sorted({v.rule for v in violations}))
        print(f"[barra] sentinel stage={stage} ok=false rules={rules} "
              f"fatal={str(verdict.fatal).lower()} "
              f"trace={getattr(trace, 'id', '-')}", flush=True)
        if mode() == "strict":
            raise SentinelError(f"{stage}: " + "; ".join(
                f"{v.rule} ({v.detail})" for v in violations))
    return verdict
