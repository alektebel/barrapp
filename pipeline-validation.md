# barrapp — Validación del pipeline + endurecimiento (a prueba de balas)

- **Fecha:** 2026-09-06, stack `sam-app` (eu-west-1), dispositivo `0d8a253e-...`
- **Arquitectura:** App (Android) → API Gateway `gogtzcttw6.execute-api.eu-west-1.amazonaws.com`
  → ApiFunction (Lambda, python3.11) → S3 (multipart) → WorkerFunction (Lambda imagen,
  3 GB, mediapipe) → paquete `barra` (measurement).

---

## 1. ¿El backend procesa realmente los videos? — SÍ (verificado)

Test end-to-end con un clip real de 3.3 MB (`VID-20260827-WA0010.mp4`):

1. `POST /v1/jobs {"exercise":"auto"}` → job `629bd93adb1b` + presigned S3 PUT
2. `PUT` del clip al S3 → HTTP 200
3. `POST /v1/jobs/{id}/submit` → `queued`
4. Poll → `processing | estimating the pose` → **`done`** en ~60 s

**Resultado devuelto (JSON):**
```
status: done
exercise: muscle_up   n_reps: 2.0   session: 2026-09-06   score: 56.0   band: solid
detected: muscle_up @ 0.98   duration_s: 15.29
trim: {startS: 1.73, endS: 15.06}
provenance: barra 0.1.0
```
Conclusión: **el backend procesa videos de verdad** (pose + score + trim + provenance).
El fallo que veía el teléfono ("Lost contact with the server") era doble: (a) DNS del
teléfono sin resolver, y (b) la imagen del worker estaba rota (ver §3).

---

## 2. Causa raíz de que los jobs quedaran en `queued` para siempre

`ModuleNotFoundError: No module named 'vision'` en el worker, **en tiempo de import**
(`from process import process_job` en `handler.py`), que estaba **fuera** del try/except.
La invocación async (Event) se traga el error → el job nunca se marca `failed`, se queda
en `queued` eterno y el teléfono muestra un spinner que nadie responde.

Causa del import roto: `process.py` importa `vision`, pero el `Dockerfile` **no copiaba
`vision.py`** a la imagen:
```
COPY api/handler.py process.py deepseek.py ${LAMBDA_TASK_ROOT}/   # faltaba vision.py
```

---

## 3. Bugs corregidos

| # | Archivo | Cambio |
|---|---|---|
| 1 | `server/Dockerfile` | `vision.py` añadido al `COPY` |
| 2 | `server/api/handler.py` | `worker()` reescrito: el `import process_job` y el download **dentro** del try; cualquier muerte marca el job `failed` con el error real (`_fail`). Se añade chequeo de clip vacío. |
| 3 | `server/api/handler.py` | **Reaper lazy** `_reap_stale()`: jobs en `queued`/`processing` > 30 min se marcan `failed("the worker never picked this up. Retry.")` al leerse. |
| 4 | `server/template.yaml` | `WorkerDLQ` (SQS) + `AWS::Lambda::EventInvokeConfig` (retry 2, max age 1 h, OnFailure→DLQ) + permiso `sqs:SendMessage`. |
| 5 | `server/vendor_barra.sh` | **Bug crítico de auto-recursión**: `SRC` resolvía a la raíz del repo y el destino (`server/vendor/barra`) estaba **dentro** del origen → rsync se copiaba a sí mismo. Se excluye `server/vendor` y artefactos pesados (`.gradle`, `build`, `*.mp4`, `*.pt`, `*.log`…). Resultado: `vendor/barra` pasó de **235 GB → 34 MB**. |

---

## 4. Robustez verificada tras el fix

- **Worker roto ya no cuelga jobs:** al probar con una imagen que fallaba el import, el
  job devolvió `failed | No module named 'barra.faults_taxonomy'` (se marcó `failed`, no
  quedó en `queued`). Esto ya no debería pasar (vendor correcto), pero el mecanismo de
  error está probado.
- **Clip inválido se maneja con gracia:** subí un archivo de 20 bytes (no es video) →
  `done`, `n_reps: 0`, headline "No movement barra can measure", `blockers: ["Could not
  open the clip: cannot open"]`. El worker no crashea.

---

## 5. Pendiente (lado cliente / infra)

- **Teléfono:** el DNS del teléfono no resuelve el endpoint (WiFi sin internet/captive).
  No es del pipeline; se resuelve con la red del teléfono.
- **App Android:** el cliente ya tiene Retry por clip; falta un watchdog que muestre un
  estado claro cuando el server no responde (hoy muestra "Lost contact with the server").
  Revisar `BarrappViewModel`/`WorkStore` para un timeout de polling + estado "worker down".
- **Dependencia del modelo:** `vendor/barra` incluye `models/pose_landmarker_heavy.task`
  (34 MB). Si el repo crece (app/build), el vendor volverá a inflar la imagen — vigilar
  los `exclude` de `vendor_barra.sh`.

## Cómo desplegar (después de tocar el server)

```
cd server
bash deploy.sh                # vendor + imagen worker + sam build + sam deploy
```

`deploy.sh` construye la imagen del worker **fuera de SAM**, a propósito. Docker 29
con el snapshotter de containerd sube un **OCI image index** con attestations, y
Lambda solo acepta un manifest Docker v2 schema 2:

```
The image manifest, config or layer media type for the source image ... is not supported
```

Eso hizo fallar el deploy del 6-sep (16:32) y provocó rollback. Como el rollback
restaura una imagen que funciona, el pipeline seguía corriendo y la rotura solo
aparecía en el siguiente deploy. El script usa `--provenance=false --sbom=false
--output type=docker,oci-mediatypes=false` y **verifica el media type antes de
tocar el stack**.

## Cuentas (email + contraseña)

Cognito guarda las credenciales; la app nunca lleva el SDK de AWS ni el client id.
El teléfono manda email/contraseña a `/v1/auth/*` y la API hace de proxy.

- Identidad: `Authorization: Bearer <token>` → `owner = "u:<sub>"`;
  si no, `X-Device-Id` → `owner = "<uuid>"`. Las dos conviven, así que una
  instalación anónima anterior sigue funcionando igual.
- `POST /v1/auth/claim {deviceId}` mueve las sesiones `done` de un device id a la
  cuenta. Solo las `done`: la clave S3 de un clip en vuelo es `<owner>/<job>.mp4`,
  y reescribir el owner apuntaría al worker a una clave que no existe.
- Pool: `eu-west-1_cPTuu3rP2`, client `1q40tqke0a32fpfhr29bjumtck`.

## Tests E2E

```
python3 scripts/e2e_pipeline.py --negative --auth   # 44 checks contra la API real
bash scripts/e2e_device.sh [--reset]                # 7 checks en el teléfono por adb
```
