"""Encuentra vídeos repetidos aunque estén recodificados o recortados.

    .venv/bin/python tools/evalweb/dedupe.py            # informe
    .venv/bin/python tools/evalweb/dedupe.py --delete   # borra las copias

El sha256 del etiquetador sólo junta copias idénticas byte a byte. El mismo clip
bajado a otra resolución, recomprimido o recortado tiene otros bytes, así que un
hash de bytes (ni uno plano ni un árbol de Merkle) no lo ve. Aquí cada vídeo se
resume en una huella perceptual: un dHash de 64 bits por fotograma a 2 fps. Dos
vídeos son el mismo si, con algún desfase, la mayoría de fotogramas que se
solapan difieren en pocos bits. Eso aguanta recodificación, cambio de tamaño y
recortes por delante o por detrás.

De cada grupo se queda uno: el que ya tiene valoración humana; si no, el de la
fuente preferida (repo > app > corpus) y, a igualdad, el de más resolución y
más largo. Un clip de menos de la mitad de duración que el que queda es un
extracto (o al revés, la fuente) y tampoco se borra. --delete sólo borra ficheros del corpus (data/calisthenics/videos);
los de la app o del repo se informan pero no se tocan, y un clip valorado
nunca se borra.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/evalweb"))

from server import SOURCE_RANK, Store  # noqa: E402

CACHE = ROOT / "out/evalweb/fingerprints.json"
THUMBS = ROOT / "out/evalweb/thumbs"
FPS = 2
FRAME_BITS = 10        # fotogramas a ≤ 10/64 bits se consideran iguales
MIN_OVERLAP = 6        # fotogramas solapados (3 s) para poder afirmar nada
MIN_MATCH = 0.8        # fracción de fotogramas solapados que deben coincidir
MIN_COVER = float(os.environ.get("DEDUPE_MIN_COVER", 0.6))       # y cubrir al menos esto del clip más corto
MAX_FRAMES = 1200      # 10 min a 2 fps; lo de después no hace falta


def probe(path: Path) -> tuple[int, int, float]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=False).stdout
    try:
        d = json.loads(out)
        s = d["streams"][0]
        return int(s["width"]), int(s["height"]), float(d["format"].get("duration") or 0)
    except (ValueError, KeyError, IndexError):
        return 0, 0, 0.0


def fingerprint(path: Path) -> list[int]:
    """dHash de 64 bits por fotograma: gris 9x8, bit = píxel > vecino derecho."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-an", "-frames:v", str(MAX_FRAMES),
         "-vf", f"fps={FPS},scale=9:8:flags=area,format=gray", "-f", "rawvideo", "-"],
        capture_output=True, check=False).stdout
    frames = np.frombuffer(raw, dtype=np.uint8)
    frames = frames[: len(frames) // 72 * 72].reshape(-1, 8, 9).astype(np.int16)
    bits = (frames[:, :, :-1] > frames[:, :, 1:]).reshape(len(frames), 64)
    weights = 1 << np.arange(64, dtype=np.uint64)
    return [int(x) for x in (bits.astype(np.uint64) * weights).sum(axis=1)]


THUMB = 32
CORR = float(os.environ.get("DEDUPE_CORR", 0.9))            # correlación mínima entre fotogramas para darlos por iguales
SAME = 0.96            # fidelidad mínima para ser el mismo vídeo (se oculta)
DELETE = 0.98          # y para borrarlo del disco, con margen
EXCERPT = 0.5          # un clip de menos de la mitad del otro es un extracto


def thumbs(path: Path) -> np.ndarray:
    """Fotogramas en gris de 32x32 a 2 fps, para la verificación fina."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-an", "-frames:v", str(MAX_FRAMES),
         "-vf", f"fps={FPS},scale={THUMB}:{THUMB}:flags=area,format=gray",
         "-f", "rawvideo", "-"], capture_output=True, check=False).stdout
    n = len(raw) // (THUMB * THUMB)
    return np.frombuffer(raw[: n * THUMB * THUMB], dtype=np.uint8).reshape(n, THUMB, THUMB)


def descriptors(frames: np.ndarray) -> np.ndarray:
    """Quita las bandas uniformes (negras o de color), reescala a 32x32 y
    normaliza: media cero, norma uno.
    Así un fondo blanco común no hace parecidos dos ejercicios distintos."""
    f = frames.astype(np.float32)
    if len(f) == 0:
        return np.zeros((0, 256), np.float32)
    # Banda = fila o columna de un solo color en todos los fotogramas. No vale
    # "lo que no se mueve": eso depende de qué tramo del vídeo se ve, y dos
    # cortes distintos del mismo clip acabarían recortados distinto.
    rows = np.where(f.std(2).max(0) > 4)[0]
    cols = np.where(f.std(1).max(0) > 4)[0]
    if len(rows) >= 8 and len(cols) >= 8:
        f = f[:, rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]
    import cv2  # noqa: PLC0415 - sólo aquí
    small = np.stack([cv2.resize(x, (THUMB, THUMB), interpolation=cv2.INTER_AREA) for x in f])
    d = small.reshape(len(small), -1)
    d = d - d.mean(1, keepdims=True)
    norm = np.linalg.norm(d, axis=1, keepdims=True)
    return np.where(norm > 1e-3, d / np.maximum(norm, 1e-3), 0)


def verify(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """Como similarity(), pero con correlación de fotogramas sin bandas.

    Devuelve (cobertura, fidelidad): cuánto del clip más corto coincide y la
    mediana de la correlación en ese tramo. Una recodificación da ≥ 0,97; otra
    toma del mismo ejercicio en el mismo sitio (la pesa en la otra mano) se
    queda en ~0,94 aunque cubra todo."""
    va, vb = a[np.linalg.norm(a, axis=1) > 0], b[np.linalg.norm(b, axis=1) > 0]
    if len(va) < MIN_OVERLAP or len(vb) < MIN_OVERLAP:
        return 0.0, 0.0
    corr = va @ vb.T
    close = corr >= CORR
    best, fidelity, (na, nb) = 0.0, 0.0, close.shape
    for off in range(-(na - MIN_OVERLAP), nb - MIN_OVERLAP + 1):
        diag = np.diagonal(close, offset=off)
        if len(diag) >= MIN_OVERLAP and diag.mean() >= MIN_MATCH:
            cover = float(diag.sum()) / min(na, nb)
            if cover > best:
                best, fidelity = cover, float(np.median(np.diagonal(corr, offset=off)))
    return best, fidelity


def _popcount(x: np.ndarray) -> np.ndarray:
    x = x.copy()
    n = np.zeros(x.shape, dtype=np.uint8)
    while x.any():
        n += (x & np.uint64(1)).astype(np.uint8)
        x >>= np.uint64(1)
    return n


def _bits(fp: list[int]) -> np.ndarray:
    a = np.array(fp, dtype=np.uint64)
    return np.unpackbits(a.view(np.uint8).reshape(-1, 8), axis=1).astype(bool)


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Mejor fracción de fotogramas coincidentes sobre todos los desfases.

    `a` y `b` son matrices (n, 64) de bits. Un fotograma casi uniforme (negro,
    fundido) tiene un dHash pobre y coincide con cualquier otro: se ignora."""
    if len(a) < MIN_OVERLAP or len(b) < MIN_OVERLAP:
        return 0.0
    ia = a[(a.sum(1) > 4) & (a.sum(1) < 60)]
    ib = b[(b.sum(1) > 4) & (b.sum(1) < 60)]
    if len(ia) < MIN_OVERLAP or len(ib) < MIN_OVERLAP:
        return 0.0
    # distancia de Hamming de todos contra todos: (na, nb)
    d = (ia[:, None, :] != ib[None, :, :]).sum(2)
    close = d <= FRAME_BITS
    # Un desfase cuenta si casi todo lo solapado coincide; la puntuación es
    # cuánto del clip más corto cubre esa coincidencia. Sin esto, la misma
    # cabecera de canal de 3 s une vídeos distintos.
    best = 0.0
    na, nb = close.shape
    for off in range(-(na - MIN_OVERLAP), nb - MIN_OVERLAP + 1):
        diag = np.diagonal(close, offset=off)
        if len(diag) >= MIN_OVERLAP and diag.mean() >= MIN_MATCH:
            best = max(best, float(diag.sum()) / min(na, nb))
    return best


def purge_corpus_index(paths: list[str]) -> None:
    """Quita los clips borrados de los índices versionados del corpus (CSV,
    labels_export.json y la etiqueta por clip): una copia en el entrenamiento
    y otra en la evaluación del clasificador es una fuga entre particiones."""
    base = ROOT / "data/calisthenics"
    rels = {(ROOT / p).relative_to(base).as_posix() for p in paths}   # videos/dip/x.mp4
    names = {Path(p).name for p in paths}
    for csv_file in sorted(base.glob("*.csv")):
        with open(csv_file, encoding="utf-8", newline="") as f:   # conserva CRLF
            lines = f.read().splitlines(keepends=True)
        kept = [l for l in lines if l.split(",", 1)[0] not in rels | names]
        if len(kept) != len(lines):
            with open(csv_file, "w", encoding="utf-8", newline="") as f:
                f.write("".join(kept))
    export = base / "labels_export.json"
    if export.exists():
        rows = json.loads(export.read_text(encoding="utf-8"))
        kept = [r for r in rows if r.get("file") not in rels]
        if len(kept) != len(rows):
            export.write_text(json.dumps(kept, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    for rel in rels:
        (base / "labels" / Path(rel).with_suffix(".json")).unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--delete", action="store_true", help="borra las copias del corpus")
    ap.add_argument("--jobs", type=int, default=8)
    args = ap.parse_args()

    store = Store(ROOT, ROOT / "data/eval/human_technique.jsonl",
                  ROOT / "out/evalweb/hashes.json")
    store.dup_file = Path(os.devnull)    # ver también lo que el etiquetador oculta
    store.scan()
    store.hash_all()
    items, _, _ = store.items()
    labelled = set(store.answers())

    try:
        cache = json.loads(CACHE.read_text())
    except (OSError, ValueError):
        cache = {}

    def fp_of(item):
        sha = item["sha256"]
        if sha not in cache:
            path = ROOT / item["paths"][0]
            w, h, dur = probe(path)
            cache[sha] = {"w": w, "h": h, "dur": dur, "fp": fingerprint(path)}
        return cache[sha]

    with ThreadPoolExecutor(args.jobs) as ex:
        list(ex.map(fp_of, items))
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache))

    bits = {i["sha256"]: _bits(cache[i["sha256"]]["fp"]) for i in items}
    desc: dict[str, np.ndarray] = {}

    def desc_of(sha):
        if sha not in desc:
            f = THUMBS / f"{sha[:16]}.npy"
            if f.exists():
                t = np.load(f)
            else:
                t = thumbs(ROOT / by_sha[sha]["paths"][0])
                THUMBS.mkdir(parents=True, exist_ok=True)
                np.save(f, t)
            desc[sha] = descriptors(t)
        return desc[sha]
    by_sha = {i["sha256"]: i for i in items}
    # Candidatos baratos primero: un fotograma central de uno debe estar cerca
    # de algún fotograma del otro. Sólo esos pares pasan a la alineación.
    parent = {i["sha256"]: i["sha256"] for i in items}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    shas = [i["sha256"] for i in items]
    pairs = []
    for x in range(len(shas)):
        for y in range(x + 1, len(shas)):
            a, b = bits[shas[x]], bits[shas[y]]
            if len(a) < MIN_OVERLAP or len(b) < MIN_OVERLAP:
                continue
            probe_rows = a[np.linspace(0, len(a) - 1, 5).astype(int)]
            if ((probe_rows[:, None, :] != b[None, :, :]).sum(2) <= FRAME_BITS).any(1).sum() < 3:
                continue
            if similarity(a, b) < MIN_COVER:
                continue
            s, fid = verify(desc_of(shas[x]), desc_of(shas[y]))
            if s >= MIN_COVER and fid >= SAME:
                pairs.append((shas[x], shas[y], s, fid))
                parent[find(shas[x])] = find(shas[y])

    groups: dict[str, list[str]] = {}
    for s in shas:
        groups.setdefault(find(s), []).append(s)
    dup_groups = [g for g in groups.values() if len(g) > 1]

    def keep_key(sha):
        it, c = by_sha[sha], cache[sha]
        return (sha not in labelled, SOURCE_RANK[it["source"]], -(c["w"] * c["h"]), -c["dur"])

    report, to_delete, excerpts, hide = [], [], [], []
    for g in sorted(dup_groups, key=lambda g: by_sha[g[0]]["paths"][0]):
        g.sort(key=keep_key)
        keep = g[0]
        # Un clip mucho más corto (o más largo) que el que queda es un extracto
        # o la fuente: no es una copia, y borrarlo perdería material.
        dur = lambda s: cache[s]["dur"] or 1e-9
        fid = lambda s: max((p[3] for p in pairs if {p[0], p[1]} == {keep, s}), default=0.0)
        drop = [s for s in g[1:] if min(dur(s), dur(keep)) / max(dur(s), dur(keep)) >= EXCERPT
                and fid(s) >= DELETE]
        excerpts += [by_sha[s]["paths"][0] for s in g[1:] if s not in drop]
        # Para etiquetar, un extracto es el mismo material: se oculta igual.
        hide += [s for s in g[1:] if s not in labelled]
        if sum(s in labelled for s in g) > 1:
            print(f"! varias valoradas en el mismo grupo: {[by_sha[s]['paths'][0] for s in g]}")
        report.append({"keep": by_sha[keep]["paths"], "drop": [by_sha[s]["paths"] for s in drop]})
        print(f"\nqueda  {by_sha[keep]['paths'][0]}  {cache[keep]['w']}x{cache[keep]['h']} "
              f"{cache[keep]['dur']:.0f}s{'  [valorado]' if keep in labelled else ''}")
        for s in g[1:]:
            tag = ("fuera" if s in drop else "extracto (se queda)"
                   if fid(s) >= DELETE else "parecido (se oculta, no se borra)")
            sim = max((p[2] for p in pairs if {p[0], p[1]} == {keep, s}), default=None)
            print(f"  {tag} {by_sha[s]['paths'][0]}  {cache[s]['w']}x{cache[s]['h']} "
                  f"{cache[s]['dur']:.0f}s  sim={sim if sim is None else round(sim, 2)} "
                  f"fid={round(fid(s), 3)}"
                  f"{'  [valorado]' if s in labelled else ''}")
    # Las copias exactas (mismo sha, varias rutas) también sobran.
    exact = [p for i in items for p in i["paths"][1:]]
    for g in report:
        for paths in g["drop"]:
            to_delete += paths
    for i in items:
        if len(i["paths"]) > 1 and not any(i["paths"] in g["drop"] for g in report):
            to_delete += i["paths"][1:]
    rated = {p for s in labelled for i in items if i["sha256"] == s for p in i["paths"]}
    corpus = [p for p in to_delete if p.startswith("data/calisthenics/videos/")
              and p not in rated]
    other = [p for p in to_delete if p not in corpus]
    size = sum((ROOT / p).stat().st_size for p in corpus if (ROOT / p).exists())
    print(f"\n{len(excerpts)} extractos o tomas muy parecidas: se ocultan en el "
          "etiquetador, pero no se borran.")
    print(f"{len(dup_groups)} grupos de vídeos repetidos (recodificados o recortados); "
          f"{len(exact)} copias exactas en otras rutas.")
    print(f"Sobran {len(corpus)} ficheros del corpus ({size / 1e9:.1f} GB)"
          + (f" y {len(other)} fuera del corpus, que no se tocan" if other else ""))
    (ROOT / "out/evalweb/duplicates.json").write_text(
        json.dumps({"groups": report, "delete": corpus, "untouched": other, "hide": hide},
                   ensure_ascii=False, indent=1))
    if args.delete:
        for p in corpus:
            (ROOT / p).unlink(missing_ok=True)
        purge_corpus_index(corpus)
        print(f"Borrados {len(corpus)} ficheros y sus filas en los índices del corpus.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
