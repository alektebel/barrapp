# Ronda 3 — velocidad sin tocar ningún número (2026-10-29)

Objetivo: que el procesamiento sea mucho más rápido sin bajar reps, ejercicio
detectado ni notas. Regla de la ronda: **solo entra lo que deja el payload
idéntico**; lo que lo mueve se documenta y queda fuera (ver "Decisiones").

## 1. Dónde se va el tiempo (jobs reales de producción, 8 últimos con traza)

Fuente: `Uploads` + `Traces` en DynamoDB, leídos con `scripts/job_timing.py`
(solo lectura). Clips de móvil 1080x1920, 31–48 s, 366–1193 fotogramas, 31–122 MB.

| Etapa | Rango observado | Notas |
|---|---|---|
| Subida del móvil | 2,7–10 s con buena red; 148 y 206 s con mala | El APK instalado sube el original; el recorte (`e68c246`) no está instalado en estos jobs |
| submit → worker entra | 1,2–2,2 s | invocación asíncrona + import del módulo |
| Descarga S3 | 0,3–0,6 s | despreciable |
| **Arranque en frío** | **hasta ~30 s** | job `44268cdeec26` (primero tras inactividad): 9,8 s de `provenance` (hash de 30 MB leídos del contenedor) + 20,2 s de imports (cv2/mediapipe/scipy) antes de empezar la pose. En caliente: 0,3 s + 1,0 s |
| Decodificar+redimensionar | ~3 ms/fotograma local (1080p) | entre dos llamadas del landmarker |
| **Pose (MediaPipe heavy, secuencial)** | **42–107 s** (47–115 ms/fotograma) | 85–95 % de la ruta crítica; el mismo clip varía 78–102 s según el host |
| Clasificar+fusionar+segmentar+puntuar | 0,1–2,2 s | el locator ya terminó cuando fusión lo pide (0,002 s) |
| Escritura `done` | 0,06–0,2 s | |
| **Tras el resultado, en serie (antes)** | | |
| · recorte guardado (ffmpeg re-encode + subida) | 13–24 s | |
| · nota de visión (LLM, 2 llamadas en paralelo) | 14–183 s (≈124 s típico; 183 s = 3×60 s de timeout) | |
| · prosa del coach (LLM) | 20–181 s | esperaba a la visión |

Resultado en el teléfono hoy: `done` a 50–150 s de acabar la subida; la nota de
visión llega 14–204 s después y la prosa 38–330 s después (media 161 s).

## 2. Cambios

| Commit | Cambio | Efecto medido | Números |
|---|---|---|---|
| `0cd52d8` | Tras `done`, recorte guardado / nota de visión / prosa corren **a la vez** (`handler._after_result`); cada rama publica sus claves al llegar y se fusionan bajo candado | Con los tiempos reales de los 8 jobs: prosa de 161 s → 49 s de media tras el resultado (peor caso 330 → 181 s); nota de visión −17 s de media (ya no espera el recorte); fin de todo −2,5 min en el peor caso (330 → 181 s). La prosa deja de esperar a la visión | idénticos: la prosa solo lee claves medidas (`report.digest`); cada rama escribe sus claves, `_changed` fusiona solo diferencias; tests |
| `7202273` | Pose: decodificado+resize+RGB en un hilo por delante del landmarker (`BARRA_POSE_PREFETCH=0` lo apaga) | −7 % de tiempo de pose en 1080p (local); ~1 % en clips pequeños | **puntos clave idénticos bit a bit** (`scripts/pose_prefetch_check.py`) y payload completo idéntico en el corpus (`scripts/corpus_gate.py`) |
| `7202273` | `server/api/prewarm.py`: el worker lee en paralelo los ficheros fríos (modelo de pose, `.so` de mediapipe/cv2/numpy/scipy) mientras baja el clip | **No medido** (solo se ve en un arranque en frío real; mirar `probe@` e `imports` en la traza con `job_timing.py`) | no puede cambiar ningún valor: solo lee bytes |

## 3. Evidencia de fiabilidad

Corpus propio (8 clips de `VID-20260827-WA00xx.mp4`), pipeline de producción
(`process.measure_job`, modelos remotos apagados), payload completo con
`BARRA_POSE_PREFETCH=0` frente a `=1` (`scripts/corpus_gate.py`):

| Clip | ejercicio | reps | score | pose+medida antes / después | payload |
|---|---|---|---|---|---|
| WA0010 | pull_up | 2 | 56 | 17,2 / 15,9 s | idéntico |
| WA0011 | knee_raise | 0 | — | 7,8 / 7,8 s | idéntico |
| WA0012 | muscle_up | 1 | 59 | 12,4 / 12,4 s | idéntico |
| WA0014 | muscle_up | 0 | — | 50,8 / 45,9 s | idéntico |
| WA0017 | muscle_up | 2 | 48 | 26,5 / 26,5 s | idéntico |
| WA0018 | muscle_up | 0 | — | 10,8 / 10,7 s | idéntico |
| WA0019 | knee_raise | 2 | 50 | 11,3 / 11,2 s | idéntico |
| WA0020 | muscle_up | 0 | — | 19,6 / 20,4 s | idéntico |

Los clips del corpus son 478x850 (decodificar casi no cuesta), por eso la
ganancia local es pequeña; con 1080x1920 (el móvil) `pose_prefetch_check.py`
da −7 % (15,5 → 14,3 s sobre 367 fotogramas) con puntos clave idénticos.
Los ejercicios/reps/scores coinciden con los de la puerta secuencial de la
ronda 2.

Tests: suite completa en verde salvo los 2 fallos que ya fallaban antes de
tocar nada (`tests/test_mimo.py`, nombre de modelo en el entorno).

## 4. Decisiones que no tomé (cambian números o cuestan dinero/despliegue)

Ver el informe final de la sesión; resumen:

1. **Pose en trozos (`BARRA_POSE_WORKERS=6`)**: −60–70 % de pose, pero la puerta
   de la ronda 2 dice DEVIATES (flip pull_up→muscle_up, un blocker nuevo, 5/7
   scores movidos). Sigue apagado.
2. **App: cola en segmentos** (hoy `consumeQueue` espera al resultado del clip 1
   antes de subir el 2): con N clips el total pasa de ≈N×T a ≈T + (N−1)×(subida+pose).
   Es un cambio de la app sin cambio de números; no lo hice porque no es de
   subida/compresión y no se puede verificar en el teléfono desde aquí.
3. **Instalar el APK con recorte** (`e68c246`): la pose escala con los
   fotogramas subidos.
4. **Visión: reducir timeout/reintentos o el esfuerzo de razonamiento del
   modelo**: 124 s típicos y 183 s en fallo; cambia cuántas notas llegan.
5. **Calentar el contenedor** (EventBridge cada 5 min o provisioned
   concurrency): quita ~30 s del primer clip tras inactividad; cuesta dinero y
   toca AWS.
