"""dedupe.py: el mismo clip recortado o recodificado se reconoce; otro no."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/evalweb"))

import dedupe  # noqa: E402


def _clip(seed: int, n: int = 60) -> np.ndarray:
    """Fondo fijo con una figura que se mueve: n fotogramas de 32x32."""
    rng = np.random.default_rng(seed)
    background = rng.integers(60, 200, (32, 32)).astype(np.float32)
    frames = []
    for t in range(n):
        f = background.copy()
        y = int(8 + 8 * np.sin(t / 3 + seed))
        x = int(10 + 6 * np.cos(t / 5 + seed))
        f[y:y + 10, x:x + 6] = 20
        frames.append(f)
    return np.clip(np.stack(frames), 0, 255).astype(np.uint8)



def test_copia_que_empieza_mas_tarde_y_recodificada():
    a = _clip(1)
    rng = np.random.default_rng(9)
    b = a[17:].astype(np.int16) + rng.integers(-3, 4, a[17:].shape)   # recorte + ruido
    b = np.clip(b, 0, 255).astype(np.uint8)
    cover, fid = dedupe.verify(dedupe.descriptors(a), dedupe.descriptors(b))
    assert cover >= dedupe.MIN_COVER
    assert fid >= dedupe.DELETE


def test_otro_movimiento_sobre_el_mismo_fondo_no_es_copia():
    a, b = _clip(1), _clip(1)
    # misma escena, la figura hace otra cosa
    b = b.copy()
    for t in range(len(b)):
        b[t, 20:30, 20:26] = 20
    cover, fid = dedupe.verify(dedupe.descriptors(a), dedupe.descriptors(b))
    assert not (cover >= dedupe.MIN_COVER and fid >= dedupe.SAME)


def test_bandas_uniformes_se_quitan_aunque_el_tramo_sea_otro():
    a = _clip(3)
    padded = np.zeros((len(a), 32, 40), np.uint8)
    padded[:, :, 4:36] = a
    da = dedupe.descriptors(a[:30])
    db = dedupe.descriptors(padded[10:])
    cover, fid = dedupe.verify(da, db)
    assert cover >= dedupe.MIN_COVER and fid >= dedupe.SAME
