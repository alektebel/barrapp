"""The one client for every model call (nan.builders, OpenAI-compatible).

Vision, the objectives chat and the written report used to carry their own
HTTP code, and each lost failures its own way: vision swallowed a 401 for four
weeks as "an empty reply". Here, once:

* `complete()` never raises. It returns a `ChatResult` whose `error` names the
  cause ("401 This API key does not have access…", "empty reply",
  "model_missing: mimo-v2.5", "timeout: …").
* 4xx (except 429) is the provider saying no - not retried. 429, 5xx,
  transport errors and empty replies are retried.
* The model is checked against `/models` once per container, so a retired
  model is named before the call instead of after a 401.
* Each failure prints one line, `[barra] llm call failed model=… status=…`,
  for the CloudWatch metric.

Lives in api/ because the API zip is built from that folder alone; the worker
image copies api/*.py into its task root too.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

try:  # worker/task root and the API package both put nan_secret beside this
    from nan_secret import get_nan_key
except ImportError:  # tests / local dev with `server/` on the path
    from api.nan_secret import get_nan_key

DEFAULT_BASE = "https://api.nan.builders/v1"
TIMEOUT = 60
ATTEMPTS = 3
# Least worth starting another attempt for when a budget is set.
MIN_ATTEMPT_S = 8

# The provider's edge 403s clients that look like a script.
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")


@dataclass(frozen=True)
class ChatResult:
    model: str
    text: str | None = None
    error: str | None = None
    status: int | None = None

    @property
    def ok(self) -> bool:
        return self.text is not None


# Per container: a Lambda instance runs one job at a time.
_last_error: str | None = None
_listed: set[str] | None = None


def reset_state() -> None:
    """Forget the remembered failure and model list. Tests only."""
    global _last_error, _listed
    _last_error, _listed = None, None


def last_error() -> str | None:
    """The cause of the most recent failed call, None after a success."""
    return _last_error


def config() -> tuple[str, str] | None:
    """(base_url, key), or None when no key is configured."""
    key = (get_nan_key() or "").strip()
    if not key:
        return None
    base = (os.environ.get("NAN_BASE_URL") or DEFAULT_BASE).rstrip("/")
    return base, key


def model_listed(base: str, key: str, model: str) -> bool:
    """Is `model` served? A guard, not a gate: an unreadable listing lets the
    call go ahead, and the call's own error says what went wrong."""
    global _listed
    if _listed is None:
        req = urllib.request.Request(f"{base}/models", headers={
            "Authorization": f"Bearer {key}", "User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
            _listed = {str(m.get("id")) for m in data.get("data", []) if isinstance(m, dict)}
        except Exception:  # noqa: BLE001 - see docstring
            return True
    return model in _listed


def _http_cause(exc: urllib.error.HTTPError) -> str:
    try:
        body = json.loads(exc.read().decode() or "{}")
        message = (body.get("error") or {}).get("message") or ""
    except Exception:  # noqa: BLE001
        message = ""
    return f"{exc.code} {message or exc.reason}".strip()[:200]


def _fail(model: str, error: str, status: int | None = None) -> ChatResult:
    global _last_error
    _last_error = error
    print(f"[barra] llm call failed model={model} status={status or '-'} error={error}",
          flush=True)
    return ChatResult(model=model, error=error, status=status)


def complete(model: str, messages: list[dict], *, system: str | None = None,
             json_mode: bool = False, temperature: float = 0.3,
             timeout: int = TIMEOUT, attempts: int = ATTEMPTS,
             base: str | None = None, key: str | None = None,
             check_model: bool = True, budget: float | None = None) -> ChatResult:
    """One chat completion. `messages` is the OpenAI list; `system`, when
    given, is prepended. `base`/`key` default to config().

    `budget` (seconds) caps the WHOLE call, retries included: each attempt's
    timeout shrinks to what is left and no new attempt starts with less than
    MIN_ATTEMPT_S. Three 60 s timeouts in a row held a failing note for 183 s;
    with a budget a failure comes back at the budget, while the quick failures
    (empty reply, 5xx) still get all their attempts."""
    global _last_error
    if base is None or key is None:
        cfg = config()
        if cfg is None:
            return _fail(model, "not_configured")
        base, key = cfg
    # The preflight is useful for ordinary calls because it names retired
    # models clearly, but it can add a separate 15 s request on a cold worker.
    # Latency-critical callers may rely on the completion endpoint itself;
    # its 4xx error remains explicit and non-retried.
    if check_model and not model_listed(base, key, model):
        return _fail(model, f"model_missing: {model}")

    msgs = ([{"role": "system", "content": system}] if system else []) + list(messages)
    payload: dict = {"model": model, "messages": msgs, "temperature": temperature}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(
        f"{base}/chat/completions", data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": USER_AGENT},
        method="POST",
    )
    error, status = "no attempt made", None
    started = time.monotonic()
    for attempt in range(max(1, attempts)):
        attempt_timeout = timeout
        if attempt:
            time.sleep(0.8 * attempt)
        if budget is not None:
            left = budget - (time.monotonic() - started)
            if attempt and left < MIN_ATTEMPT_S:
                break
            attempt_timeout = max(MIN_ATTEMPT_S, min(timeout, left))
        try:
            with urllib.request.urlopen(req, timeout=attempt_timeout) as resp:
                data = json.loads(resp.read().decode())
            text = data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as exc:
            error, status = _http_cause(exc), exc.code
            if 400 <= exc.code < 500 and exc.code != 429:
                break
            continue
        except (TimeoutError, OSError) as exc:  # URLError is an OSError
            reason = getattr(exc, "reason", exc)
            timed_out = isinstance(exc, TimeoutError) or "timed out" in str(reason).lower()
            error, status = (f"timeout: {reason}" if timed_out else f"transport: {reason}"), None
            continue
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            error, status = f"malformed response: {type(exc).__name__}", None
            continue
        if isinstance(text, str) and text.strip():
            _last_error = None
            return ChatResult(model=model, text=text)
        error, status = "empty reply", None
    return _fail(model, error, status)
