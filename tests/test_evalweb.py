"""Herramienta de valoración manual (tools/evalweb)."""
from __future__ import annotations

import http.client
import importlib.util
import json
import threading
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "evalweb_server", Path(__file__).resolve().parents[1] / "tools/evalweb/server.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)

BODY = bytes(range(256)) * 40


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "repo"
    d = root / "data/calisthenics/videos/push_up"
    d.mkdir(parents=True)
    (d / "a.mp4").write_bytes(BODY)
    (root / "VID-1.mp4").write_bytes(BODY)          # mismo contenido
    (d / "b.mp4").write_bytes(b"otro" * 100)
    (tmp_path / "secret.mp4").write_bytes(b"x")
    store = ev.Store(root, root / "data/eval/h.jsonl", tmp_path / "c.json", min_bytes=0,
                     scan_dirs=[("data/calisthenics/videos", "corpus")])
    store.scan()
    store.hash_all()
    srv = ev.make_server(store, 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield store, srv.server_address[1], root
    srv.shutdown()


def get(port, path, headers=None, method="GET"):
    c = http.client.HTTPConnection("127.0.0.1", port)
    c.request(method, path, headers=headers or {})
    r = c.getresponse()
    return r.status, r.read(), r


def test_dedupe_by_content(env):
    store, port, _ = env
    items, total, hashed = store.items()
    assert total == 3 and hashed == 3 and len(items) == 2
    dup = next(i for i in items if len(i["paths"]) == 2)
    assert dup["source"] == "repo" and dup["movementFolder"] == "push_up"
    assert items[0] is dup or items[0]["source"] == "repo"


def test_range_206(env):
    store, port, _ = env
    sha = store.items()[0][0]["sha256"]
    for it in store.items()[0]:
        if len(it["paths"]) == 2:
            sha = it["sha256"]
    st, data, r = get(port, "/video/" + sha, {"Range": "bytes=10-99"})
    assert st == 206 and data == BODY[10:100]
    assert r.getheader("Content-Range") == f"bytes 10-99/{len(BODY)}"
    st, data, _ = get(port, "/video/" + sha, {"Range": "bytes=-5"})
    assert st == 206 and data == BODY[-5:]
    st, data, _ = get(port, "/video/" + sha)
    assert st == 200 and data == BODY


def test_path_traversal_refused(env):
    _, port, _ = env
    for p in ("/video/../../secret.mp4", "/video/%2e%2e/secret.mp4",
              "/video/" + "0" * 64, "/video/..%2fsecret.mp4"):
        assert get(port, p)[0] == 404


def test_save_appends_and_latest_wins(env):
    store, port, root = env
    sha = next(i["sha256"] for i in store.items()[0] if len(i["paths"]) == 2)

    def post(fb, rating):
        c = http.client.HTTPConnection("127.0.0.1", port)
        c.request("POST", "/api/save", json.dumps(
            {"sha256": sha, "feedback": fb, "rating": rating, "durationS": 3.5}))
        r = c.getresponse()
        r.read()
        return r.status

    assert post("uno", 2) == 200 and post("dos", 4) == 200
    lines = (root / "data/eval/h.jsonl").read_text().splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert rec["paths"] == ["VID-1.mp4", "data/calisthenics/videos/push_up/a.mp4"]
    assert rec["movement"] == "push_up" and rec["durationS"] == 3.5
    store2 = ev.Store(root, root / "data/eval/h.jsonl", store.cache_file, min_bytes=0,
                      scan_dirs=[("data/calisthenics/videos", "corpus")])
    assert store2.answers()[sha]["feedback"] == "dos"
    st, body, _ = get(port, "/api/videos")
    done = [i for i in json.loads(body)["items"] if i["done"]]
    assert len(done) == 1 and done[0]["answer"]["rating"] == 4
    c = http.client.HTTPConnection("127.0.0.1", port)
    c.request("POST", "/api/save", json.dumps({"sha256": "f" * 64}))
    assert c.getresponse().status == 400
