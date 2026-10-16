"""Herramienta local para valorar vídeos a mano (verdad humana de técnica).

    .venv/bin/python tools/evalweb/server.py [--port 8095]

Sólo biblioteca estándar. Escucha en 127.0.0.1. Las respuestas se añaden a
data/eval/human_technique.jsonl (una línea por guardado, la última gana).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
SEED = "evalweb-1"
SOURCE_RANK = {"repo": 0, "app": 1, "corpus": 2}
# (carpeta relativa, fuente). El raíz del repo se escanea sin recursión.
SCAN_DIRS = [("data/calisthenics/videos", "corpus"), ("server/data", "app"),
             ("data/prod", "app")]
MIME = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime",
        ".webm": "video/webm", ".mkv": "video/x-matroska"}


def _h(text: str) -> str:
    return hashlib.sha256((SEED + text).encode()).hexdigest()


MIN_BYTES = 64 * 1024


class Store:
    def __init__(self, root: Path, eval_file: Path, cache_file: Path,
                 scan_dirs=None, min_bytes: int = MIN_BYTES):
        self.root = Path(root)
        self.min_bytes = min_bytes
        self.eval_file = Path(eval_file)
        self.cache_file = Path(cache_file)
        self.scan_dirs = SCAN_DIRS if scan_dirs is None else scan_dirs
        self.lock = threading.RLock()
        self.files: list[tuple[str, str]] = []      # (rel, source)
        self.hashes: dict[str, str] = {}            # rel -> sha
        self.cache: dict[str, list] = {}
        self.hashed = 0
        self._load_cache()

    # ---- escaneo y hash ----
    def _load_cache(self):
        try:
            self.cache = json.loads(self.cache_file.read_text())
        except (OSError, ValueError):
            self.cache = {}

    def _save_cache(self):
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.cache))
            os.replace(tmp, self.cache_file)
        except OSError:
            pass

    def scan(self):
        found = []
        for p in sorted(self.root.glob("*")):
            if p.is_file() and p.suffix.lower() in EXTS and p.name.startswith("VID-"):
                found.append((p.relative_to(self.root).as_posix(), "repo"))
        for rel, src in self.scan_dirs:
            base = self.root / rel
            for dp, _, fns in os.walk(base):
                for fn in sorted(fns):
                    if Path(fn).suffix.lower() in EXTS:
                        found.append(((Path(dp) / fn).relative_to(self.root).as_posix(), src))
        # Restos de pruebas (un clip truncado de 20 KB en server/data/) no son
        # vídeos que valorar: ningún clip real pesa menos de 64 KB.
        found = [(rel, src) for rel, src in found
                 if (self.root / rel).stat().st_size >= self.min_bytes]
        with self.lock:
            self.files = found
            for rel, _ in found:      # reutiliza la caché ya válida
                self._from_cache(rel)

    def _from_cache(self, rel):
        try:
            st = (self.root / rel).stat()
        except OSError:
            return None
        c = self.cache.get(rel)
        if c and c[0] == st.st_size and c[1] == st.st_mtime_ns:
            self.hashes[rel] = c[2]
            return c[2]
        return None

    def hash_all(self, progress=None):
        """Hash de los ficheros pendientes; los pequeños/app primero."""
        with self.lock:
            todo = [r for r, _ in self.files if r not in self.hashes]
            total = len(self.files)
        rank = {r: SOURCE_RANK[s] for r, s in self.files}
        todo.sort(key=lambda r: (rank[r], r))
        last_save = time.time()
        for rel in todo:
            path = self.root / rel
            try:
                st = path.stat()
                d = hashlib.sha256()
                with open(path, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        d.update(chunk)
            except OSError:
                continue
            with self.lock:
                self.hashes[rel] = d.hexdigest()
                self.cache[rel] = [st.st_size, st.st_mtime_ns, d.hexdigest()]
                n = len(self.hashes)
            if progress:
                progress(n, total)
            if time.time() - last_save > 10:
                self._save_cache()
                last_save = time.time()
        self._save_cache()

    # ---- elementos ----
    def items(self):
        with self.lock:
            groups: dict[str, dict] = {}
            src_of = dict(self.files)
            for rel, sha in self.hashes.items():
                if rel not in src_of:
                    continue
                g = groups.setdefault(sha, {"sha256": sha, "paths": [], "sources": set()})
                g["paths"].append(rel)
                g["sources"].add(src_of[rel])
            total_files = len(self.files)
            hashed = sum(1 for r in self.hashes if r in src_of)
        out = []
        for g in groups.values():
            g["paths"].sort()
            source = min(g["sources"], key=SOURCE_RANK.get)
            folders = sorted({p.split("/")[3] for p in g["paths"]
                              if p.startswith("data/calisthenics/videos/")
                              and p.count("/") >= 4})
            out.append({"sha256": g["sha256"], "paths": g["paths"], "source": source,
                        "movementFolder": folders[0] if folders else ""})
        return self._order(out), total_files, hashed

    @staticmethod
    def _order(items):
        first = sorted((i for i in items if i["source"] != "corpus"),
                       key=lambda i: (SOURCE_RANK[i["source"]], i["paths"][0]
                                      if i["source"] == "repo" else _h(i["sha256"])))
        by: dict[str, list] = {}
        for i in items:
            if i["source"] == "corpus":
                by.setdefault(i["movementFolder"], []).append(i)
        for v in by.values():
            v.sort(key=lambda i: _h(i["sha256"]))
        names = sorted(by, key=_h)
        rest = []
        while any(by.values()):
            for n in names:
                if by[n]:
                    rest.append(by[n].pop(0))
        return first + rest

    def path_for(self, sha):
        with self.lock:
            for rel, s in self.hashes.items():
                if s == sha and any(r == rel for r, _ in self.files):
                    return self.root / rel
        return None

    # ---- respuestas ----
    def answers(self):
        latest = {}
        try:
            with open(self.eval_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(rec, dict) and rec.get("sha256"):
                        latest[rec["sha256"]] = rec
        except OSError:
            pass
        return latest

    def save(self, data: dict):
        sha = str(data.get("sha256", ""))
        with self.lock:
            paths = sorted(r for r, s in self.hashes.items() if s == sha)
        if not paths:
            raise ValueError("vídeo desconocido")
        folder = ""
        for p in paths:
            parts = p.split("/")
            if p.startswith("data/calisthenics/videos/") and len(parts) >= 5:
                folder = parts[3]
                break
        rating = data.get("rating")
        if rating is not None:
            rating = int(rating)
            if not 1 <= rating <= 5:
                raise ValueError("valoración fuera de rango")
        dur = data.get("durationS")
        rec = {"sha256": sha, "paths": paths, "movementFolder": folder,
               "movement": str(data.get("movement") or folder),
               "rating": rating, "unassessable": bool(data.get("unassessable")),
               "feedback": str(data.get("feedback") or ""),
               "savedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
               "durationS": round(float(dur), 2) if isinstance(dur, (int, float)) else None}
        self.eval_file.parent.mkdir(parents=True, exist_ok=True)
        with self.lock, open(self.eval_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec


def make_handler(store: Store):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, code, body: bytes, ctype="application/json", extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self):
            path = unquote(urlparse(self.path).path)
            if path in ("/", "/index.html"):
                return self._send(200, (HERE / "index.html").read_bytes(),
                                  "text/html; charset=utf-8",
                                  {"Cache-Control": "no-store"})
            if path == "/api/videos":
                items, total, hashed = store.items()
                ans = store.answers()
                for i in items:
                    a = ans.get(i["sha256"])
                    i["done"] = a is not None
                    i["answer"] = a
                body = json.dumps({"items": items, "totalFiles": total,
                                   "hashed": hashed}, ensure_ascii=False)
                return self._send(200, body.encode(), extra={"Cache-Control": "no-store"})
            m = re.fullmatch(r"/video/([0-9a-f]{64})", path)
            if m:
                return self._video(m.group(1))
            self._send(404, b'{"error":"no encontrado"}')

        do_HEAD = do_GET

        def do_POST(self):
            if urlparse(self.path).path != "/api/save":
                return self._send(404, b'{"error":"no encontrado"}')
            try:
                n = int(self.headers.get("Content-Length") or 0)
                rec = store.save(json.loads(self.rfile.read(n) or b"{}"))
            except (ValueError, TypeError) as e:
                return self._send(400, json.dumps({"error": str(e)}).encode())
            self._send(200, json.dumps(rec, ensure_ascii=False).encode())

        def _video(self, sha):
            p = store.path_for(sha)
            if p is None or not p.is_file():
                return self._send(404, b'{"error":"no encontrado"}')
            size = p.stat().st_size
            ctype = MIME.get(p.suffix.lower(), "application/octet-stream")
            start, end, code = 0, size - 1, 200
            rng = self.headers.get("Range")
            if rng:
                m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng.strip())
                if not m or not (m.group(1) or m.group(2)):
                    return self._send(416, b"", extra={"Content-Range": f"bytes */{size}"})
                if m.group(1):
                    start = int(m.group(1))
                    if m.group(2):
                        end = min(int(m.group(2)), size - 1)
                else:
                    start = max(0, size - int(m.group(2)))
                if start >= size or start > end:
                    return self._send(416, b"", extra={"Content-Range": f"bytes */{size}"})
                code = 206
            length = end - start + 1
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if self.command == "HEAD":
                return
            try:
                with open(p, "rb") as f:
                    f.seek(start)
                    left = length
                    while left > 0:
                        chunk = f.read(min(1 << 20, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

    return H


def make_server(store: Store, port=0, host="127.0.0.1"):
    return ThreadingHTTPServer((host, port), make_handler(store))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8095)
    a = ap.parse_args()
    store = Store(ROOT, ROOT / "data/eval/human_technique.jsonl",
                  ROOT / "out/evalweb/hashes.json")
    store.scan()
    pending = len(store.files) - len(store.hashes)
    print(f"{len(store.files)} ficheros; {pending} por calcular (en segundo plano)", flush=True)

    def prog(n, total):
        if n % 10 == 0 or n == total:
            print(f"\rhash {n}/{total}", end="", file=sys.stderr, flush=True)
    threading.Thread(target=store.hash_all, args=(prog,), daemon=True).start()
    srv = make_server(store, a.port)
    print(f"http://127.0.0.1:{a.port}/", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
