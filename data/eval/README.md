# Evaluación humana de técnica

`human_technique.jsonl` es la **verdad humana**: el entrenador ve cada vídeo sin
ninguna salida del pipeline y escribe en texto libre cómo fue la técnica. Sirve
para evaluar el pipeline (hallazgo #7 de `docs/AUDITORIA-TECNICA.md`).

## Cómo usar la herramienta

    .venv/bin/python tools/evalweb/server.py [--port 8095]

Abre http://127.0.0.1:8095/. Escanea `data/calisthenics/videos/**`, `server/data/`,
`data/prod/` y los `VID-*` de la raíz, y deduplica por sha256 del contenido. Los
hashes se cachean en `out/evalweb/hashes.json` (la primera vez se calculan en
segundo plano y los vídeos van apareciendo). Atajos: espacio, `,` `.` (fotograma),
`1`–`5` (nota), Ctrl+Enter (guardar y siguiente).

## Formato (una línea JSON por guardado; la última de cada `sha256` gana)

    {"sha256", "paths": [rutas relativas conocidas], "movementFolder",
     "movement" (respondido o carpeta), "rating" (1-5 o null),
     "unassessable": bool, "feedback": texto, "savedAt": ISO8601, "durationS"}

El fichero es de sólo añadir: no se edita a mano; corregir = guardar de nuevo.

## Advertencia

Estas etiquetas sirven para **evaluar** el pipeline. No las uses para ajustar
umbrales sobre los mismos clips sin un reparto de reserva (held-out): ajustar y
medir sobre los mismos vídeos infla el resultado.
