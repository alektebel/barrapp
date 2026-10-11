# barrapp — Plan de alpha cerrado

> **Para mañana.** Documento de trabajo: estado real de la app al 2026‑10‑11 y
> los pasos concretos para el **primer alpha cerrado externo (15–30 testers
> reales, en gimnasio)**. No es marketing ni aspiracional: cada tarea lleva un
> criterio de aceptación. Si algo no está verificado, se dice que no lo está.

---

## 0. Definición de "alpha" para este plan

- **Tipo:** alpha cerrado externo, 15–30 testers con móvil real, grabando sus
  propios sets (calistenia: dominada, muscle‑up, fondos, sentadilla…).
- **Canal:** Play Console → *Internal testing* primero (máx. 100 por email,
  sin revisión, minutos para publicar) y, si el flujo aguanta, promover el
  **mismo release** a *Closed testing* sin reconstruir.
- **Objetivo del alpha, en una frase:** comprobar que el bucle
  *grabar → medir → ver un número honesto* funciona en manos que no son las de
  Diego, y que cuando falla se puede diagnosticar con el *trace id*.
- **NO objetivos:** marketing, reviews públicas, escalar usuarios, prometer
  precisión del score (ver §3).

---

## 1. Snapshot del repositorio (2026‑10‑11)

| Dato | Valor |
|---|---|
| Rama actual | `alektebel/ghostshark` |
| Posición | **26 commits por delante de `origin/main`** (main congelado en 2026‑09‑04, `9baa67c`) |
| HEAD | `400b99c` — *"Feedback from the app: a message, an optional clip, a route and a table for both"* (2026‑09‑13) |
| App | `versionName 1.3.0`, `versionCode 18`, `applicationId com.fitness.barrapp` |
| SDK | `minSdk 24`, `targetSdk 36`, `compileSdk 36`, AGP 8.9.1 |
| Kotlin | 57 archivos, `app/src/main/java/com/barrapp` |
| Backend | Python `barra/` + `server/` (Lambda `sam-app`, DynamoDB, S3). `measurementVersion 2` |
| API | `gogtzcttw6.execute-api.eu-west-1.amazonaws.com` (debug y release en `gradle.properties`) |
| Tags | hasta `v1.1.0`; **no hay tag `v1.3.0`** pese a que el build ya es 1.3.0 |
| Artefactos locales | `dist/` solo tiene `barrapp-1.0.5-debug.apk`; **falta el build actual** |
| CI | `.github/workflows/android-build.yml` construye APK debug en cada push |

---

## 2. Qué está construido y qué se considera que funciona

**Producto (según docs y CI):**

- Navegación completa: Privacy → Onboarding → Home (shell adaptativo, breakpoint
  840dp) + Coach / Replay / WorkLog / Diagnostics / Plan / Feedback.
- Flujo de subida con **4 etapas nombradas** (sin porcentaje falso), cola que
  sobrevive a la navegación, retry/dismiss de clips fallidos.
- **Coach aritmético local**: no inventa PRs ni tendencias; responde solo con lo
  medido. El modelo de prosa del servidor acota el reporte por clip.
- Revisión semanal por WorkManager (solo si hay algo que contar).
- **Veredicto de progresión** con el estándar escrito en la propia tarjeta
  ("8 reps verificadas en una sesión a 60+, en 2 días").
- **Diagnostics**: último trace id + comando `barra explain --replay <id>`,
  provenance, event log, *Copy report* sin datos personales.
- **Feedback desde la app** (commit más reciente): mensaje + clip opcional,
  ruta `/v1/feedback`, tabla en DynamoDB.
- Legal: `privacy.md`, borrado de cuenta (`eliminar-cuenta.html`), contacto real.
- Cuentas (1.2.0) + `X-Device-Id`; calendario local cachea para funcionar offline.

**Backend:**

- `server/process.py` sirve `measurementVersion 2` (assessments por rep,
  `variant`, `assessment.checks`).
- `barra/` documentado: segmentación, clasificación, métricas, fallos por reglas
  geométricas con ids estables, null distribution, `validate-quality`.
- Stores opcionales: Astra DB (`barra/astra_store.py`) para estado de evaluación.

---

## 3. Verificación: qué está probado y qué no

Esta es la tabla que decide si el alpha puede empezar. **Nada de la columna
derecha se puede asumir.**

| Área | Estado |
|---|---|
| Compilación Android en este entorno | ✅ **Build real local** (2026‑10‑11, JDK 21 en `~/.local/jdk21`, SDK 36 instalado): `assembleDebug assembleRelease bundleRelease` OK. Release **sin firmar**: falta `keystore.properties`. `testDebugUnitTest` verde (119 checks) tras fijar el locale del test (fallaba en JVM `es_ES`: "5,8" vs "5.8"). |
| Tests Python | ✅ En `.venv`: **285 tests, OK** (2026‑10‑11, incluye el trabajo sin commitear del checkout principal). |
| Validez del score (`barra validate-quality`) | `CEILING FAIL` (control saturado). `RELIABILITY` y `SENSITIVITY` **NOT RUN**: no hay clips filmados para ello. **El diferenciador central está sin validar en datos reales.** |
| Worker desplegado | Los docs avisan de que el worker podía ser anterior a `measurementVersion 2`. El `Dockerfile` se arregló el 2026‑09‑13 (`c437ba1`) para incluir `api/auth.py`, `api/chat.py`. **Confirmar qué hay desplegado.** `GET /health` → `200 {"ok": true, "accounts": true}` (2026‑10‑11). No hay `aws`/`sam` en la máquina: la versión del worker **sigue sin confirmar**; requiere una medición real. |
| UI actual vs `feedback.md` | El feedback (2026‑09‑06) es de la UI **inglesa**. Desde entonces hay rediseño "Nocturne" en **español** (`ui/tracker/`). Los bugs críticos pueden estar resueltos, cambiados o seguir. **Re‑verificar, no asumir.** |
| End‑to‑end en móvil real | "Sube un clip y aparece una sesión" está documentado pero no reproducido en el build 1.3.0 actual. |

---

## 4. Riesgos y bloqueantes conocidos

### 4.1 Producto / UX
- **Idioma incoherente:** UI viva en **español hardcodeado** (`Tracker*.kt`), pero
  listing de Play y páginas legales en **inglés**. Hay que decidir mercado.
- **Bugs críticos reportados**, pendientes de re‑verificar en el build actual
  (fuente: `feedback.md` B1–B8, `qa-pass-2.md` N1–N9):
  - detalle de sesión que abre siempre la sesión vieja (B1);
  - flechas de calendario sin handler / meses inalcanzables (B8);
  - botón atrás de hardware que sacaba de la app (N1);
  - Coach sin estado *pendiente/error* (B2/N5);
  - contadores de reps contradictorios entre pantallas (M4/N2/N3);
  - "Watch the replay" muerto (B3), "?" que no es ayuda (B4), accesibilidad
    (content‑desc vacíos).
- **Score de calidad sin validar** (§3). No vender "supera tu ruido" todavía.

### 4.2 Backend / despliegue
- Confirmar worker = `measurementVersion 2` en producción.
- Dependencia de red para la subida; **no hay crash reporting ni analítica**
  (solo Diagnostics manual).

### 4.3 Algoritmo (evaluación 2026‑09‑07, P0 abiertos)
- **C1:** `squat/dip/push_up/pull_up` heredan reglas del muscle‑up con geometría
  de cadera → "dead hang" dispara siempre, "momentum" nunca.
- **C2:** medida ausente tratada como sana (`_f(x, 1.0)`) → fallos que nunca
  disparan. Viola la propia regla del repo.
- **C3/C4:** fallos derivados por regex de prosa + umbrales triplicados
  (incluido `Cues.kt`).
- Plan de consejo activo: `llm-council/runs/current-final-plan.md` (abstinencia
  honesta + arreglo de 3 confusiones + threading de vista).

### 4.4 Release / ops
- Todo el trabajo está **en rama, sin mergear a `main`**. Un alpha necesita base
  estable y trazable.
- No hay tag del 1.3.0 ni artefacto firmado actual en `dist/`.
- Cambio de `applicationId` (`com.alektebel.barrapp` → `com.fitness.barrapp`):
  instalaciones viejas de testers son **apps distintas**; hay que desinstalar /
  reinstalar.

---

## 5. Hoja de ruta

### P0 — Antes de reclutar un solo tester (≈1–2 semanas)

1. **Verde de verdad.**
   - Correr `python -m unittest discover -s tests` en el `.venv` correcto hasta
     el baseline (137). Arreglar lo que salga, no filtrarlo.
   - Compilar release localmente: `./gradlew assembleRelease bundleRelease`.
   - *Criterio:* suite verde + APK/AAB firmados que instalan en un móvil real.

2. **Consolidar la rama.**
   - Mergear `alektebel/ghostshark` → `main` (o crear tag de alpha).
   - *Criterio:* un tag/commit concreto del que cuelga el build que verán los
     testers, y `dist/` con el artefacto de esa versión.

3. **Verificar el backend desplegado.**
   - `sam build && sam deploy` si el worker no es el actual.
   - `curl "$ApiUrl/health"` y una medición end‑to‑end desde un móvil real.
   - *Criterio:* el payload real trae `measurementVersion 2` y **todas** las
     claves que lee el cliente Kotlin.

4. **Re‑QA sobre el build actual (no sobre el feedback viejo).**
   - Repasar B1–B8 y N1–N9 contra 1.3.0 y marcar cada uno **fixed / open /
     ya no aplica** en una tabla.
   - *Criterio:* ningún P0 de UI en estado "open" sin decisión (arreglar,
     deshabilitar con motivo, o aceptar explícitamente).

5. **Decidir idioma.**
   - Todo español (calistenia ES) o todo inglés. Para el alpha, **no mezclar**.
   - *Criterio:* UI, notificaciones, listing y legal en el mismo idioma.

### P1 — Para que el alpha produzca información (≈2–4 semanas)

6. **Encender la validación del score.**
   - Filmar el protocolo de `barra validate-quality --protocol`: mismo set con
     2 móviles (reliability), set al fallo (degradation), set a medio rango y
     jerky (sensitivity). Cerrar los tres checks.
   - Mientras no esté: etiquetar el score como **experimental** en la UI.
   - *Criterio:* `barra validate-quality` con veredicto distinto de `NOT RUN`.

7. **Cerrar los P0 del algoritmo de fallos.**
   - C2 primero (medida ausente nunca = sana), luego C1 (clasificador `squat()`
     propio) y C3/C4 (campos numéricos estructurados + umbrales en
     `config.py` con parity test contra `Cues.kt`).
   - *Criterio:* tests de invariantes + `Cues.kt` parity verde.

8. **Observabilidad mínima.**
   - Crash reporting (Crashlytics o Sentry) + el feedback de la app ya presente.
   - Enlazar cada reporte con el `run <trace-id>` (la id ya viaja en 4 sitios).
   - *Criterio:* un fallo de tester llega con traza reproducible.

### P2 — Durante el alpha

9. Correr `scripts/pipeline_eval.py` + `scripts/train_model.py` sobre el corpus
   y publicar `docs/PIPELINE-EVAL.md` con los buckets
   `correct / honestAbstention / fabricated`.
10. Afinar la taxonomía de errores por ejercicio a partir de los fallos reales
    que reporten los testers.

---

## 6. Plan de testers (alpha cerrado)

- **Número:** 15–30. Perfil: calistenia real (no solo gimnasio), dispuestos a
  grabar y a reportar.
- **Canal:** Play internal testing → opt-in link. Los que no tengan cuenta Google
  en el móvil: APK release por transferencia directa.
- **Aviso obligatorio al tester:** el `applicationId` cambió; si probaron una
  build anterior (`com.alektebel.barrapp`), es otra app — desinstalar.
- **Qué pedirles, exactamente tres cosas** (de `docs/RELEASE.md`):
  1. la línea `run <trace-id>` del final de la lista de reps cuando un número
     les chirríe;
  2. un clip lateral y otro frontal, para verificar los motivos de "no se pudo
     comprobar";
  3. si el estándar que declararon volvió a aparecer en la página de sesión.
- **Qué NO prometer:** precisión del score, ni que "sabe si mejoras". El alpha
  evalúa el bucle, no el veredicto de calidad.

---

## 7. Decisiones pendientes (para tomar mañana)

- [ ] ¿Mercado/idioma del alpha: ES o EN?
- [ ] ¿Merge a `main` o tag de alpha sobre la rama?
- [ ] ¿El score entra al alpha como "experimental" o se retrasa hasta validarlo?
- [ ] ¿Crash reporting ya, o solo feedback+Diagnostics?
- [ ] ¿Ventana del alpha (fechas) y quién recluta a los testers?

---

## 8. Re‑QA de B1–B8 / N1–N9 contra la UI viva (2026‑10‑11)

Por **lectura de código** de la UI viva (`BarrappApp` → `ui/tracker/TrackerRoot`),
no en dispositivo: no había móvil ni emulador conectados. Hay que confirmarlo
en un móvil antes de cerrar P0.4.

| Bug | Estado | Nota |
|---|---|---|
| B1 sesión vieja | **arreglado hoy** | La tarjeta y el que abre ya usaban el mismo selector (días descendentes). Quedaba: `selectDate` dejaba la sesión anterior en pantalla mientras cargaba (y para siempre si fallaba la red), y una respuesta lenta podía pisar la siguiente. Ahora se limpia antes y se descarta la respuesta si cambió la fecha. |
| B2/N5 Coach sin estado | fixed | Coach local: `coachThinking` + "…" + mensaje de error en `catch`. El mensaje de error está **en inglés** (ver idioma). |
| B3 replay muerto | fixed | `onWatchReplay` es null sin job → el botón no se muestra. |
| B4 "?" | ya no aplica | No hay "?" en la UI tracker. |
| B5/B6 layout | probablemente fixed | Comentario explícito de pitch constante en `CalendarScreen`; confirmar en móvil. |
| B7/N9 "Still needed" | fixed | La UI tracker usa su propia copia en español. |
| B8 flechas mes | fixed | `onPrevMonth/onNextMonth` con offset. |
| N1 atrás | fixed | `BackHandler` en `BarrappApp` y en `TrackerRoot` (sheets → tab → Home). |
| **N2 mes filtra mal** | **arreglado hoy** | Seguía abierto: filas y totales del calendario eran de *todos* los meses, y al tocar una fila el día se resolvía contra el mes visible (fila "5 sept" vista en octubre → abría 5 oct o nada). Ahora filas y totales son del mes visible. |
| **Calendario → sesión** | **arreglado hoy** (nuevo) | Tocar un día medido llamaba `selectDate` y **cerraba** el calendario sin abrir la sesión. Ahora abre la hoja de sesión. |
| N3/M4 deriva de números | sin verificar | Los números salen de `SessionStore.days`; requiere reproducir en móvil con clips re‑medidos. |
| N4 input del Coach tapado | probablemente fixed | Fila de entrada fija con `imePadding()` + `safeDrawingPadding()`. Confirmar. |
| N6 formatos de fecha | probablemente fixed | `shortDate()` en la UI tracker; confirmar. |
| N7 hoy sin marcar | parcial | Hoy solo se marca si tiene medición; un hoy vacío sale plano. |
| Accesibilidad | sin verificar | 0 `contentDescription` vacíos en `ui/tracker`, pero hay que auditarlo con TalkBack. |

**Idioma (para la decisión P0.5):** la UI tracker está en español, pero las
sugerencias del Coach (`vm.suggestions()`), sus respuestas (`Coach.answer`) y el
mensaje de error del Coach siguen **en inglés**. Mezcla visible en la primera
pantalla de chat.

## 9. Log de avance

- **2026‑10‑11:** P0.1 hecho salvo la firma (Python 285 OK; Android debug,
  release y AAB compilan; unit tests verdes). P0.3 parcial (`/health` OK; la
  versión del worker sigue sin confirmar). P0.4 por lectura de código: B1
  residual, N2 y la apertura de sesión desde el calendario, arreglados. Los
  cambios están sin commitear en el checkout principal
  (`claude/barra-deviation-detection-l509c9`).
- **Siguiente:** `keystore.properties` → APK/AAB firmados; una medición real
  desde el móvil para confirmar `measurementVersion 2`; pasada en dispositivo
  de la tabla del §8; decisiones del §7 (sobre todo idioma y merge/tag).

## 10. Referencias

- Estado de la app: `README.md`, `docs/APP.md`, `docs/RELEASE.md`, `docs/PLAY.md`
- Validación del score: `docs/QUALITY.md`, `docs/FINDINGS.md`, `docs/PROGRESS.md`
- Algoritmo: `feedback.md` (evaluación), `docs/EVALUATION_FINDINGS.md`,
  `docs/PIPELINE-EVAL.md`, `llm-council/runs/current-final-plan.md`
- QA en dispositivo: `feedback.md`, `qa-pass-2.md`, `ux-tree.md`
- Debugging / trazas: `docs/DEBUGGING.md`, `tools/debugweb/README.md`
- Infra: `docs/AWS.md`, `docs/AWS_RUNBOOK.md`, `docs/ASTRA.md`
