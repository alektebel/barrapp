"""Deterministic job ids from the clip's content hash.

The same owner uploading the same bytes must land on the same primary key so
the latest upload replaces the previous measurement. Different owners never
share a key even when the bytes match (privacy + DynamoDB single-table id).

The API Lambda imports `server/api/job_id.py` (same body) because its zip has
no barra package. Keep the two files identical — see test_deploy_contract.
"""
from __future__ import annotations

import hashlib
import re

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def normalize_content_hash(raw: str | None) -> str | None:
    """Full lowercase SHA-256 hex, or None if the client sent garbage."""
    if not isinstance(raw, str):
        return None
    h = raw.strip().lower()
    return h if _SHA256_HEX.match(h) else None


def job_id_for(owner: str, content_hash: str) -> str:
    """12-hex id: sha256(owner:content_hash)[:12].

    Scoping by owner keeps two accounts from colliding on an identical clip
    while still making a re-upload of the same file by the same athlete
    overwrite the prior job.
    """
    h = normalize_content_hash(content_hash)
    if not h:
        raise ValueError("contentHash must be a 64-char sha256 hex digest")
    owner = (owner or "").strip()
    if not owner:
        raise ValueError("owner is required to derive a job id")
    return hashlib.sha256(f"{owner}:{h}".encode("utf-8")).hexdigest()[:12]
