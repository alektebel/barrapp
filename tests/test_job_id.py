from __future__ import annotations

import hashlib

from barra.job_id import job_id_for, normalize_content_hash


def test_normalize_accepts_full_sha256():
    h = "a" * 64
    assert normalize_content_hash(h) == h
    assert normalize_content_hash(h.upper()) == h
    assert normalize_content_hash("not-a-hash") is None
    assert normalize_content_hash("a" * 12) is None


def test_same_owner_same_bytes_same_id():
    h = hashlib.sha256(b"clip-bytes").hexdigest()
    a = job_id_for("owner-1", h)
    b = job_id_for("owner-1", h)
    assert a == b
    assert len(a) == 12
    assert all(c in "0123456789abcdef" for c in a)


def test_different_owners_different_ids():
    h = hashlib.sha256(b"clip-bytes").hexdigest()
    assert job_id_for("owner-a", h) != job_id_for("owner-b", h)


def test_different_bytes_different_ids():
    h1 = hashlib.sha256(b"clip-a").hexdigest()
    h2 = hashlib.sha256(b"clip-b").hexdigest()
    assert job_id_for("owner-1", h1) != job_id_for("owner-1", h2)
