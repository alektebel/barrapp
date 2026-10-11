# barrapp — Plan de arreglo del backend (pre‑alpha)

> 2026‑10‑11. Cada fase tiene: causa verificada → tests primero → cambio →
> puerta de salida. Nada se despliega sin pasar la puerta. Complementa
> `docs/ALPHA-PLAN.md` (P0.3 y la decisión de idioma: **todo en español**).

---

## 0. Diagnóstico (verificado en producción con la CLI de AWS)

| # | Problema | Causa raíz | Evidencia |
|---|---|---|---|
| D1 | **La visión no aporta nada desde el 17‑09** (ni localización, ni nota técnica, ni segunda opinión) | nan.builders **retiró `mimo-v2.5`**: responde `401 "This API key does not have access to the requested model"`. Nuestro cliente lo trata como respuesta vacía, y la traza escribe *"no vision endpoint configured"*, que es falso. | Logs del worker: `locate: no JSON in the mimo-v2.5 reply (0 chars)` desde el 09‑17. `/v1/models` lista `mimo-v2.6-flash`, que **sí funciona con imágenes** (probado hoy, responde en español). |
| D2 | El informe escrito nunca usa un LLM | `DEEPSEEK_API_KEY` vacío en las dos Lambdas → siempre el *fallback* fijo **en inglés** ("19 push-up reps - none verified"). | Variables de entorno de las Lambdas. NaN ofrece `deepseek-v4-flash` y `qwen3.8-flash` con la misma clave. |
| D3 | **Todo el texto que genera el servidor está en inglés** | Titulares, *blockers*, etapas ("receiving the clip"), errores ("the clip was never finished uploading. Retry."), fallback del informe. | `handler.py`, `sweeper.py`, `process.py`, `deepseek.py`, `barra/*` (movement_tree, rules, summary, recommend…). |
| D4 | El usuario ve un mensaje de desarrollador con movimientos no medibles | El clasificador nombra a propósito movimientos sin perfil (deadlift, bench_press…), lo cual está bien, pero el *blocker* que llega al móvil es el `SystemExit` crudo: `unknown movement 'deadlift'. Known: bulgarian_split_squat, …`. Además: ¿esos 5 clips eran de verdad peso muerto? | 5 jobs `done` con 0 reps y ese texto. |
| D5 | **0 reps en 27 de 58 jobs terminados** | Sin verificar. *Blockers* más comunes: "no turnaround stood out from the noise" (6), "66 % del clip colgado quieto" (7), "no se ve al atleta en el aparato" (2), D4 (5). Puede ser mezcla de clips de prueba legítimos y falsos negativos. | Tabla Jobs. |
| D6 | 20 de 78 jobs fallidos | Casi todos "the clip was never finished uploading" (el *sweeper* los cerró). Los errores de import (`auth`, `faults_taxonomy`) dejaron de salir con el deploy del 13‑09. | Tabla Jobs + logs. |
| D7 | Ningún resultado se puede atar a un build | `provenance.commit = "unknown"`: el contenedor no tiene `.git`. | Todas las trazas. |
| D8 | Lo desplegado ≠ lo que hay en el repo | Worker = `c437ba1` (13‑09). Hay ~2.300 líneas sin commitear (`fusion`, `fault_select`, `kinematics`, `movement_tree`…) que **cambian el comportamiento** y no han pasado por producción. | `git status`, fechas de las Lambdas. |

---

## 1. Principios para todas las fases

- **TDD**: primero el test que reproduce el fallo (en rojo), después el arreglo
  y después el refactor. Cada bug de producción queda como test de regresión.
- **Corpus dorado antes de tocar el algoritmo**: ningún cambio en
  segmentación o clasificación sin comparar contra un *baseline* congelado.
- **Fallar en voz alta**: un 401/404 o una respuesta vacía del modelo es un
  *error con causa* en la traza y en una métrica, nunca un `None` silencioso.
- **Un solo cliente LLM**: visión, chat e informe pasan por el mismo módulo
  (clave, UA, reintentos, timeouts, registro del modelo usado).
- **El LLM nunca manda sobre la medida** (regla existente, se mantiene).
- **Códigos estables + texto en español**: lo que el móvil muestra lleva un
  `code` estable (para tests, analítica y lógica de la app) más `text` en
  español sacado de un catálogo. El texto no se escribe suelto por el código.
- **Despliegue reversible**: se anota el *digest* de la imagen anterior antes
  de cada `sam deploy`, y el *smoke test* de `deploy.sh` es obligatorio.

---

## 2. Fases (en orden)

### Fase 0 — Línea base (sin cambiar comportamiento)
1. **Commitear el trabajo pendiente** en commits lógicos (algoritmo, scripts
   de etiquetado, server, tests). Suite verde (hoy 285 OK).
2. **Sello de build (D7)**: `deploy.sh` pasa `--build-arg BARRA_COMMIT=$(git rev-parse HEAD)`;
   `provenance.git_commit()` usa `BARRA_COMMIT` si no hay `.git`; `deploy.sh`
   se niega a desplegar con el árbol sucio (o lo sella con `+dirty`).
   *Test:* `git_commit()` devuelve la env var cuando no hay repo.
3. **Corpus dorado** (`scripts/replay_corpus.py`): bajar los 20 clips de S3 +
   los `VID-*.mp4` locales + `data/calisthenics` etiquetados; ejecutar
   `process_job` offline (sin LLM) y guardar por clip `exercise, n_reps,
   blockers, sessionScore` en `data/golden/baseline.json`. Este es el
   *baseline* contra el que se mide todo lo demás.
   *Ojo:* los clips son datos de usuarios. Se quedan en local, fuera de git.

**Puerta:** árbol limpio, suite verde, baseline generado, commit sellado.

### Fase 1 — Recuperar la visión (D1) · máximo valor, mínimo riesgo
0. ✅ 2026‑10‑11: el secreto `barrapp/nan-api-key` se actualizó con la clave
   de `~/.bashrc` (era otra). Con la clave nueva, `mimo-v2.5` **sigue** dando
   401 y no aparece en `/v1/models`, así que el cambio de modelo hace falta igual.
1. *Tests rojos:* un `_chat` que recibe 401 lanza `VisionUnavailable("401 …")`,
   no `""`; la traza distingue `not_configured` de `call_failed:<código>`.
2. Modelo configurable en un solo sitio: `BARRA_VISION_MODEL=mimo-v2.6-flash`
   y `BARRA_LOCALIZE_MODEL` en `template.yaml` (hoy está duplicado).
3. **Comprobación al arrancar**: en el primer uso por contenedor, verificar
   que el modelo está en `GET /v1/models`. Si no está, se emite un log
   `[barra] vision model missing: …` y una métrica.
4. Métrica CloudWatch `VisionCallFailed` + alarma en el topic SNS existente,
   para que la próxima retirada de un modelo avise el mismo día y no a las 4 semanas.
5. Revisar los prompts de visión con `mimo-v2.6-flash` sobre 5–10 clips del
   corpus (que el JSON siga validando: `visionValidation.dropped` ≈ 0).

**Puerta:** tests verdes; en el corpus, la localización y la nota técnica
funcionan en ≥ 90 % de los clips con atleta visible; cero 401.

### Fase 2 — Un cliente LLM único + informe con LLM (D2)
1. `server/llm.py` (o `api/nan_client.py`): `chat(model, messages, *, json=True,
   timeout, attempts)`. Usa la clave de `nan_secret`, el UA de navegador y
   reintentos ante respuesta vacía, y devuelve también el modelo y la latencia.
   `vision.py`, `api/chat.py` y el informe lo usan.
2. Sustituir `deepseek.py` por un informe vía NaN (`deepseek-v4-flash`, con
   `qwen3.8-flash` de respaldo). Prompt **en español**, mismas reglas
   ("nunca inventar un score ni un PR", citar números reales).
3. Validar la salida: JSON con `headline/narrative/nextSession`; si falta algo
   o cita un número que no está en el payload → fallback determinista (en
   español, Fase 3).
4. Quitar `DEEPSEEK_*` de `template.yaml`.

**Puerta:** tests del cliente (vacío, 401, timeout, JSON roto → fallback); en
el corpus el informe sale del LLM en ≥ 95 % de los casos y nunca cita un
número ausente del payload.

### Fase 3 — Todo en español (D3)
1. Catálogo `barra/i18n.py`: `MESSAGES = {code: "plantilla en español {param}"}`
   y `t(code, **params)`. Locale por defecto `es`; la estructura permite
   añadir `en` más adelante sin tocar el código.
2. Los *blockers* pasan de `str` a `{code, text, params}`. Durante la
   transición se mantiene `blockers: [str]` (ya en español) para la app
   actual, y se añade `blockerCodes`. Hay que confirmar qué campos lee
   el cliente Kotlin.
3. Traducir, por superficie visible: etapas del worker, errores de
   `handler.py`/`sweeper.py`, titulares y fallback del informe, rechazos de
   `movement_tree`/`rules`, nombres de movimiento.
4. *Tests:*
   - completitud: todo `code` usado existe en el catálogo;
   - **test de idioma** sobre el corpus dorado: ningún campo visible del
     payload contiene inglés (lista de palabras centinela: *the, rep, clip,
     never, retry, verified…*);
   - snapshot de mensajes clave.
5. App (aparte, Kotlin): sugerencias y respuestas del Coach y su mensaje de
   error → español (está en `ALPHA-PLAN.md` §8).

**Puerta:** el test de idioma está verde sobre todo el corpus y los nombres
técnicos (`code`) no cambian.

### Fase 4 — Movimientos no medibles (D4)
1. *Test rojo:* un clip clasificado como `deadlift` devuelve un *blocker*
   `movement_unsupported` con el texto "Hemos detectado peso muerto; todavía
   no lo medimos. Graba dominadas, fondos, flexiones…", nunca el `SystemExit`.
2. `process.py` captura `SystemExit` de `movements.resolve` en un único sitio
   y lo convierte en ese código.
3. **Análisis de error**: mirar los 5 clips "deadlift". Si no lo son,
   etiquetarlos y añadirlos al corpus como falsos positivos del clasificador
   (eso va a la Fase 5).

**Puerta:** test verde; ningún texto con "Known:" en el corpus.

### Fase 5 — Los 0 reps (D5) · trabajo de ML, con datos
1. **Etiquetar** los clips del corpus con 0 reps: reps reales y movimiento
   (con `scripts/label_reps.py` / `label_faults.py`, que ya existen).
2. **Agrupar** los fallos: (a) clip de prueba legítimo, sin ejercicio →
   abstención correcta; (b) falso negativo de segmentación (umbral de ruido);
   (c) regla del "66 % colgado" demasiado estricta; (d) detección de aparato;
   (e) error del clasificador.
3. Una **hipótesis falsable por grupo**, con su cambio en `barra/config.py`
   (nada de umbrales sueltos) y su test.
4. **Puertas de promoción** (fallan cerradas, `scripts/fault_eval.py` /
   `classify_eval.py`):
   - `fabricated` (reps inventadas en clips sin ejercicio) = **0**;
   - exactitud del conteo (±0) ≥ baseline, y ningún grupo empeora;
   - la abstención honesta se mantiene en los clips del grupo (a).
5. Cada clip arreglado queda como test de regresión.

**Puerta:** la tabla antes/después por grupo está en `docs/PIPELINE-ACCURACY.md`.

### Fase 6 — Subidas que no terminan (D6)
1. Leer la tabla `Uploads` de los 17 jobs atascados: ¿qué parte fue la última?,
   ¿hubo `client:*` de error?, ¿tamaño del clip?, ¿red?
2. Según la causa: reintento de partes en la app, aviso "la subida se
   reanudará", o un tamaño o duración máximos con un mensaje claro en español.
3. *Test:* el `sweeper` ya cubre el cierre; se añade el caso detectado.

**Puerta:** causa documentada y caso cubierto por un test.

### Fase 7 — Despliegue y verificación
1. Árbol limpio y suite completa (Python + `testDebugUnitTest`).
2. Anotar el digest de la imagen actual (para el *rollback*).
3. `deploy.sh` (con el sello de commit) → *smoke test* automático.
4. **E2E real**: subir 2–3 clips conocidos y comprobar en la traza:
   `commit` real, `vision observations kept > 0`, informe del LLM, todo el
   texto en español, `measurementVersion 2`.
5. **Rollback**: `sam deploy --parameter-overrides WorkerImageUri=<digest anterior>`.

### Fase 8 — Observabilidad mínima (en paralelo con la 7)
- Métricas por versión: tasa de 0 reps, tasa de fallo de visión, latencia del
  worker, subidas no terminadas. Alarma SNS en visión y en errores del worker.
- Un `scripts/prod_report.py` que saque esta misma tabla del §0 a demanda.

---

## 3. Decisiones que necesito

1. **¿Commitear el trabajo pendiente** del checkout tal cual (Fase 0), o lo
   revisas antes? Va a producción en el próximo deploy.
2. **Formato del español**: catálogo en el servidor con `code` + `text` en
   español (recomendado), frente a solo códigos que traduce la app.
3. **Modelo del informe**: `deepseek-v4-flash` (recomendado) o `qwen3.8-flash`.
4. **Permiso para desplegar** a producción al final de las Fases 1–4 (las
   5 y 6 pueden ir en un segundo deploy).

## 4. Orden y tamaño estimado

| Fase | Tamaño | ¿Despliegue? |
|---|---|---|
| 0 Línea base | S | — |
| 1 Visión | S | sí (deploy 1, puede ir solo y ya) |
| 2 Cliente LLM + informe | M | deploy 2 |
| 3 Español | M–L | deploy 2 |
| 4 No medibles | S | deploy 2 |
| 5 Los 0 reps | L (necesita etiquetas) | deploy 3 |
| 6 Subidas | S–M | deploy 3 |
| 7–8 Verificación y observabilidad | S | en cada deploy |
