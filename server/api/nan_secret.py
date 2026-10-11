"""Where the nan.builders key comes from.

The key is not a CloudFormation parameter and is not in the Lambda environment:
it lives in AWS Secrets Manager as `barrapp/nan-api-key` (JSON
`{"NAN_API_KEY": "..."}`). `NAN_SECRET_ID` names that secret in the cloud; a
local checkout sets neither and simply reads `NAN_API_KEY` from the
environment, which is what the dev server and the test suite already do.

The lookup is cached per process for the life of a container. A failed lookup
is NOT cached, so a transient Secrets Manager error retries on the next call
instead of disabling the model for the rest of the container's life.
"""
from __future__ import annotations

import json
import os

_cache: str | None = None


def get_nan_key() -> str:
    """The nan.builders API key, or "" when none is configured."""
    global _cache
    if _cache is not None:
        return _cache

    secret_id = os.environ.get("NAN_SECRET_ID", "").strip()
    if secret_id:
        try:
            import boto3

            raw = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)
            text = (raw.get("SecretString") or "").strip()
            # Accept either a bare key or the JSON object the secret holds.
            try:
                obj = json.loads(text)
                if isinstance(obj, dict):
                    text = str(obj.get("NAN_API_KEY") or "").strip()
            except ValueError:
                pass
            if text:
                _cache = text
                return _cache
        except Exception:  # noqa: BLE001 - fall back to the env, never raise
            pass

    env = os.environ.get("NAN_API_KEY", "").strip()
    if env:
        _cache = env
    return env


def reset_cache() -> None:
    """Forget a resolved key. Only tests need this."""
    global _cache
    _cache = None
