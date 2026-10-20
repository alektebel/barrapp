# Encargo: versión iOS de BarrApp

Pega esto como primer mensaje de una sesión nueva de Claude Code abierta en
`/home/diego/Desarrollo/barrapp`.

---

Vas a preparar la versión iOS de BarrApp, la app que analiza series de
calistenia a partir de un vídeo (cuenta repeticiones, puntúa cada una, señala
fallos y los enseña sobre el propio vídeo). La app Android y el backend ya
existen y están en producción; tu trabajo es una app iOS nativa que hable con
el MISMO backend y ofrezca la misma experiencia. Trabaja de forma autónoma; pregúntame
sólo lo que de verdad sea decisión mía (abajo están marcadas).

## Restricciones que no puedes saltarte

1. **Esta máquina es Linux (Arch). No hay Mac, ni Xcode, ni Swift instalado.**
   No puedes compilar ni ejecutar iOS aquí. Plan:
   - La lógica pura (modelos, cliente HTTP, línea de tiempo de reps, fallos,
     progresión) va en un **paquete Swift (SwiftPM) sin dependencias de UIKit**,
     que sí compila y se testea en Linux. Instala el toolchain de Swift sin root
     (p. ej. `swiftly` en `$HOME`) para `swift test` local.
   - La app (SwiftUI) se compila y se testea en **GitHub Actions con un runner
     `macos-15`** (`xcodebuild test` en el simulador, capturas del simulador como
     artefacto). `gh` está autenticado como `alektebel`; el repo es
     `alektebel/barrapp` y ya tiene `.github/workflows/android-build.yml`.
   - **Nada se ha subido nunca a GitHub desde esta rama.** Antes del primer
     `git push` pregúntame (decisión mía: rama, y si el repo puede recibirla).
2. **Todo el texto que ve el usuario va en español** (incluidos errores del
   servidor, que ya llegan en español). Nada de ids tipo `PUSH_UP`, fechas ISO
   ni inglés en pantalla.
3. **No toques** `app/` (Android), `server/` ni `barra/` (backend). Si algo del
   backend falta para iOS, escríbelo en `docs/ios/NOTAS.md`; no lo despliegues.
4. **Commits**: rama propia (p. ej. `ios/app`), mensajes en español,
   `git -c user.name="Diego Rodriguez" -c user.email="dratencia@gmail.com" commit`,
   terminados con la línea `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
   Hay ficheros sin commitear que no son tuyos (`scripts/scrape_top_up.py`,
   `data/calisthenics/hashes.csv`, `metadata.csv`, `dist/…`): no los toques ni
   los incluyas.
5. **No afirmes que algo compila o pasa tests sin verlo**: `swift test` con su
   salida, o el run de GitHub Actions en verde con su enlace. (En esta máquina
   ya pasó que un filtro `grep` ocultó que la herramienta ni se ejecutaba.)
6. **Nada de cuentas ni dinero sin mí**: cuenta de Apple Developer (99 $/año),
   App Store Connect, TestFlight y firma son decisiones mías. Prepara todo lo
   demás y dime exactamente qué necesitas.

## El backend (mismo para Android e iOS)

- Base: `https://api.barrapp.fit` (`GET /health` → `{"ok": true, ...}`).
- Identidad: cabecera **`X-Device-Id`** con un UUID aleatorio generado una vez y
  guardado en el dispositivo. Cuenta opcional con `Authorization: Bearer …`
  (`POST /v1/auth/{signup,confirm,resend,login,refresh,forgot,reset,claim}`).
- Flujo de un vídeo (cliente de referencia exacto: `scripts/e2e_pipeline.py`;
  el de Android: `app/src/main/java/com/barrapp/data/BarraApi.kt` y
  `upload/UploadQueue.kt`):
  1. `POST /v1/jobs` `{"exercise": "auto"}` → `{id, …}`.
  2. Subida: ≤ 8 MiB → `POST /v1/jobs/{id}/upload-url` y `PUT` al URL firmado;
     si no, multipart: `POST /v1/jobs/{id}/upload/start` → `{uploadId, partSize}`,
     por cada parte `POST …/upload/part` `{partNumber}` → `{url}` y `PUT` del
     trozo (guarda el `ETag`), y `POST …/upload/complete` con las partes;
     `…/upload/abort` para cancelar; `…/upload/event` para registrar eventos.
  3. `POST /v1/jobs/{id}/submit`.
  4. Sondeo `GET /v1/jobs/{id}` hasta `status == "done"` (o `failed`);
     `result` es el análisis. La prosa del coach puede llegar después
     (`proseStatus: "pending"` → seguir sondeando un poco).
  5. Otros: `GET /v1/jobs`, `GET /v1/history`, `DELETE /v1/jobs/{id}` (borra
     también los vídeos), `POST /v1/chat` (coach), `POST /v1/feedback`,
     `GET /v1/referral`, `POST /v1/referral/redeem`, `GET /v1/me`.
- Forma del análisis: la verdad es `app/src/main/java/com/barrapp/data/Models.kt`
  (`Analysis`, `RepRow` con `startS/turnS/endS`, `score` que puede ser `null`
  = «sin medir», `faults: [MeasuredFault]` con `value/threshold/unit/intervalS`,
  `topFixes`, `countStatus`, `blockers`, `sessionScore`, `sessionBand`…).
  Todos los campos nuevos tienen valor por defecto: el payload antiguo sigue
  siendo válido. Fixture de partida: `app/src/main/assets/sample_report.json`
  (payload real) y el contrato en `app/src/test/java/com/barrapp/PayloadContractTest.kt`.
  Para uno actual con la nota nueva, lanza un trabajo contra
  producción con un `X-Device-Id` desechable (`eval-<uuid>`) y el clip
  `VID-20260827-WA0020.mp4` (19 flexiones), guárdalo como fixture de tests y
  **borra el trabajo después** (`DELETE`).
- Nota y bandas: una rep limpia ronda 95-100; cada fallo medido resta 20 (máx.
  50). Bandas: fuerte ≥ 85, sólida ≥ 70, inestable ≥ 50, rota < 50
  (`barra/quality.py`, `Progression.kt`). Una rep sin medir es «—» gris, nunca 0.

## Qué construir, en este orden

Hazlo pantalla a pantalla siguiendo la app Android, que es la referencia de
comportamiento (`app/src/main/java/com/barrapp/ui/tracker/*`):

1. **Núcleo (paquete Swift, tests en Linux)**: modelos + decodificación JSON
   tolerante, cliente HTTP con el flujo de subida completo, y la lógica pura
   portada con tests de paridad contra los de Kotlin:
   `ui/replay/ReplayTimeline.kt`, `ui/tracker/Fixes.kt`,
   `ui/tracker/FaultViewer.kt` (`faultSlides`, `regionFor`),
   `ui/tracker/RepCorrection.kt` (`repCorrections`), `Progression.kt`,
   `Gamification.kt`, `data/SkillGraph.kt` (usa el mismo
   `app/src/main/assets/skills.json`), `CuesEs.kt` (nombres en español de
   fallos y movimientos). Los tests Kotlin están en `app/src/test/`.
2. **Onboarding** (`TrackerOnboarding.kt` + la pantalla de privacidad): nombre,
   ejercicio principal, objetivo, frecuencia.
3. **Grabar/subir**: elegir vídeo (PhotosPicker) o grabar (cámara), y **subida
   en segundo plano** con `URLSession` de fondo; la tarjeta «EN CURSO» y las
   cuatro etapas con nombre («Enviando el clip», «Reconociendo el movimiento»,
   «Recortando la serie», «Contando y midiendo reps»). Guarda una copia local
   del clip: la reproducción usa la copia del teléfono, el servidor no la
   devuelve. Notificación local al terminar.
4. **Resultado** (`TrackerRecord.kt` ResultsPhase): el vídeo con AVPlayer y el
   contador de reps que sube al cruzar cada `endS`, tira de reps por banda,
   nota grande + banda + «±N respecto a tu media», tarjeta de fallos con
   miniaturas, «Revisar fallos».
5. **Visor de fallos** (3b) y **corrección de una rep** (2c): fotograma clave con
   `AVAssetImageGenerator` en `atS`, zoom a la región, valor medido y objetivo,
   avance tipo historias cada 4 s; la corrección compara tu peor rep con la
   mejor. Sin esqueleto dibujado: el teléfono no recibe keypoints.
6. **Inicio, Progreso, Coach** y la ayuda «¿Cómo filmar?».

## Diseño: sistema «Tiza»

Mismo aspecto que Android. Tokens en `app/src/main/java/com/barrapp/ui/theme/Tracker.kt`
y componentes en `ui/tracker/TrackerParts.kt`; diseño original y notas en
`docs/tiza/`. Resumen: fondo papel `#F1EEE6`, tinta `#141414`, gris `#5A564E`,
naranja `#FF4F1A` sólo para lo que pide acción, verde `#1E9E63` (fuerte),
azul `#2F6BFF` (sólida), ámbar `#E39A00` (inestable), rojo `#D7263D` (rota);
tarjetas blancas con borde de 2 pt de tinta y radio 14; sombra dura sólo en la
acción principal. Tipografías: Archivo Black (titulares), IBM Plex Mono (datos),
Archivo (texto); los TTF y sus licencias OFL están en `app/src/main/res/font/` y
`app/src/main/assets/licenses/`. Dynamic Type y VoiceOver deben funcionar.

## Detalles de iOS que no debes olvidar

- `Info.plist` en español: `NSPhotoLibraryUsageDescription`,
  `NSCameraUsageDescription`, `NSMicrophoneUsageDescription` si grabas con
  audio; subida en segundo plano con sesión de fondo de `URLSession`.
- Bundle id propuesto `com.fitness.barrapp` (el mismo que Android; confírmalo
  conmigo). iOS 17+ salvo que haya motivo para bajar.
- Privacidad: los vídeos se borran del servidor a los 30 días; borrar una
  sesión borra sus vídeos (`DELETE /v1/jobs/{id}`). Política en `docs/privacidad.md`.

## Cómo trabajar

- Si te resulta útil, reparte trabajo en workers con modelos ligeros (Sonnet, o
  GLM 5.3 de nan vía `opencode run -m nan/glm5.3-flash`, clave en
  `~/.config/opencode`) y actúa como supervisor: revisa cada diff y compila o
  testea tú antes de aceptarlo. Los workers suelen afirmar que algo compila sin
  haberlo hecho: compruébalo siempre.
- Escribe el estado en `docs/ios/NOTAS.md` al cerrar cada fase: qué funciona,
  qué está verificado (con enlace al run de CI) y qué falta.

## Hecho significa

- `swift test` del paquete núcleo en verde (salida pegada en NOTAS.md).
- Workflow de GitHub Actions que compila la app y pasa los tests en el
  simulador, con capturas de onboarding, resultado y visor de fallos como
  artefacto (tras mi permiso para hacer push).
- Una prueba de punta a punta contra producción desde el simulador: onboarding
  → subir `VID-20260827-WA0020.mp4` → resultado con 19 reps → visor de fallos;
  el trabajo de prueba borrado al final.
- Lista exacta de lo que necesitas de mí para TestFlight (cuenta, certificados,
  App Store Connect).
