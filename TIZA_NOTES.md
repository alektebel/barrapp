# TIZA_NOTES.md — tarea: RESULTADOS de una serie (2b + 3a) + fases de grabación

Ficheros tocados: `app/src/main/java/com/barrapp/ui/tracker/TrackerRecord.kt`,
`app/src/main/java/com/barrapp/ui/tracker/Fixes.kt` y un test nuevo
`app/src/test/java/com/barrapp/ui/tracker/ResultsTizaTest.kt` (los «tests de estos
ficheros»). Ningún test existente cambió de texto; todos pasan, igual que
`:app:compileDebugKotlin`.

## Qué he hecho

**ResultsPhase (2b):**
- Cabecera de resultados: «DOMINADA · SERIE 1» (Archivo Black 20) sobre
  «HOY 18:42 · 6 REPS» (mono 11), con «←» en caja de 44dp sólo si llega
  `onBack`. Sustituye al «BarrApp / ANÁLISIS» sólo en RESULTS.
- El clip sigue primero con `RepReplay` tal cual (sin tocar).
- Línea de tiempo: fila de barras, una por rep, altura = nota (tope 44dp),
  color por banda (`scoreInk`), rep sin medir = tope gris (`Tk.locked`) con
  «—», nunca 0. Punto naranja con borde de tinta sobre las reps con fallo
  (el «dónde caen» de 3a) y etiqueta mono «LÍNEA DE TIEMPO · 0:24»
  (`clockMmSs` sobre `analysis.durationS`). Tocar una barra la selecciona
  (borde de tinta + número en semibold) y salta el vídeo con
  `RepReplayState.showRep(index)`; debajo aparece «REP 4 · 0:14   59 ·
  INESTABLE» con `liveRegion` para lectores de pantalla.
- Nota grande: número en Archivo Black 52 («—» gris si no hay nota),
  etiqueta de banda (`scoreLabel`) en el color de la banda, y la comparación
  «+4 respecto a tu media de dominada». Si no hay media, la línea se omite;
  mientras `vsAverage` no esté conectado, cae a la línea cualitativa
  («Por encima/debajo de tu media») si `aboveAverage` lo sabe.
- Pie: `COMPARTIR` (secundario, sólo si llega `onShare`) y `SIGUIENTE SERIE`
  (losa de tinta, `onDone`). Con 0 reps: «Volver al inicio».
- «Ver detalle» se conserva (prosa del servidor + tarjetas por rep). La lista
  ámbar «Errores detectados» del detalle se quitó: la sustituye la tarjeta de
  fallos 3a, siempre visible.

**ResultsPhase (3a):**
- Tarjeta naranja con borde de tinta y sombra dura (`TkCard(accent = true)`):
  «3 FALLOS DETECTADOS» (número grande + titular), «En las reps 4, 5 y 6.» y,
  si los datos lo respaldan, «Las 3 primeras están limpias.» (frases puras:
  `faultRepsSentence` / `leadingCleanSentence`; una rep sin medir nunca
  cuenta como limpia). Miniaturas (3 columnas): recuadro oscuro de 92dp con
  borde de tinta, glifo de play naranja y chip con la hora de la rep, «REP n»
  y el nombre del fallo debajo; tocar una llama `onOpenFault(i)` (i = índice
  del fix en `ResultsData.fixes`). Botón principal de tinta «REVISAR FALLOS»
  → `onOpenFault(0)` (sin sombra propia: ya la lleva la tarjeta). Debajo,
  secundario «VER VÍDEO COMPLETO · 0:24» → `onExpandReplay`, sólo con fallos
  y clip reproducible.
- Serie sin fallos medidos: tarjeta blanca «Serie limpia — Ningún fallo
  medido en esta serie.» y SIN botón REVISAR FALLOS. Set contado pero sin
  juzgar: la nota de `unjudged` (vía `FixesCard`, como antes) sustituye al
  bloque entero para que jamás lea «limpia».

**FixesCard («LO QUE MEJORAR · TOCA PARA VERLO»):**
- Ya no es tarjeta naranja: etiqueta mono y filas blancas con borde de 2dp —
  tag «REP N» (la rep que lo demuestra, `FixItem.repIndex`; si no hay, el
  número), título, cue y «en N de M repeticiones», flecha «→». La fila
  entera es clicable → `onShowRep(repIndex)` y la fila de la rep que está
  sonando se tiñe `Tk.orangeSoft` (el estado `sel` del mock). El «toca para
  verlo» del eyebrow sólo aparece cuando hay a dónde llevar. Naranja y
  sombra dura fuera de aquí (regla global). El uso antiguo de la sheet de
  sesión en TrackerRoot sigue compilando: los parámetros nuevos llevan default.

**IdlePhase / AnalyzingPhase (misma lógica, sistema Tiza):**
- Grabar: disco naranja con borde de tinta 2dp y sombra dura (es la acción
  principal), aros interiores en `Tk.onInk` (antes degradado + `Color.White`),
  y `contentDescription` «Grabar un set».
- Analizando: el disco de la cámara pasa a blanco con borde de tinta (era
  naranja translúcido, que violaba «naranja sólo para lo que pide acción»).

**Datos reales:** todo lo que se pinta sale de `ResultsData` / `Analysis`
(notas, bandas, startS, durationS, fixes con `repIndex`); los números de la
maqueta no aparecen en ningún sitio. `FaultChip`, `ScoreRing`, `TkCard`,
botones y formas son los de `TrackerParts`.

## Campos nuevos (todos con valor por defecto; el supervisor los conecta)

| Campo | Tipo | De dónde debería salir |
| --- | --- | --- |
| `ResultsData.vsAverage` | `Int? = null` | Nota de esta serie − media del mismo movimiento: mismo cálculo que `ResultComparison.aboveAverage` pero devolviendo la diferencia (`a.sessionScore − sum/verified`) en lugar del booleano. |
| `ResultsData.seriesLabel` | `String = ""` | «Serie N»: posición del clip actual dentro del día (`state.current?.id` en `day.jobIds`, +1). Sin él, la cabecera muestra sólo el movimiento. |
| `ResultsData.whenLabel` | `String = ""` | «Hoy 18:42» formateado desde `Job.createdAt` o `Analysis.sessionDate` (mismo espíritu que `shortDateEs`, con hora). Sin él, la cabecera muestra sólo «N REPS». |
| `TrackerRecord.onBack` | `(() -> Unit)? = null` | El «←» de la cabecera (p. ej. `showResults = false` + volver al idle). Sin él no se dibuja. |
| `TrackerRecord.onShare` | `(() -> Unit)? = null` | Compartir el resumen de la sesión. Hoy no existe callback de share; sin él, el botón COMPARTIR no aparece y SIGUIENTE SERIE ocupa el ancho. |
| `TrackerRecord.onOpenFault` | `((Int) -> Unit)? = null` | Lo pide la tarea: conectarlo a `FaultViewer(faults, i, clip, onClose)`. OJO: el orden de los fallos del visor debe ser el de `ResultsData.fixes` — la miniatura i y «REVISAR FALLOS» (i = 0) apuntan ahí. |

## Lo que NO he podido hacer (y por qué)

- **`RepReplayState.seekTo(rep.startS)`** (lo que nombra la tarea): no existe;
  `RepReplayState` sólo tiene `showRep(index)` y `RepReplay.kt` no es mío.
  `showRep` aterriza en el turnaround de la rep y pausa — la misma intención,
  un pelín mejor incluso (ahí es donde se ve el fallo).
- **El pill «REP n · 0:14» sobre el vídeo**: lo dibuja `RepReplay` (contador +
  veredicto) y no es tocable desde aquí. La selección se muestra bajo la fila
  de barras, no encima del clip.
- **Fotogramas reales en las miniaturas de fallo**: necesitaría extraer frames
  (MediaMetadataRetriever por miniatura) o tocar código fuera de mi alcance.
  La miniatura lleva el contenido que la tarea exige (rep + nombre corto) más
  la hora de la rep sobre recuadro oscuro y el glifo de play.
- **Nombres cortos de fallo** («BALANCEO», «CODOS», «RECORRIDO»): no existen
  en los datos; las miniaturas usan `faultEs(name)` completo con `maxLines = 2`
  y elipsis.
- **«REVISAR FALLOS · 15 S»**: no hay ningún dato de «duración del recorrido
  de fallos»; se queda en «REVISAR FALLOS». «VER VÍDEO COMPLETO · 0:24» usa
  `analysis.durationS` (duración que manda el servidor); si es 0, el sufijo se
  omite. Puede diferir en décimas de lo que el reproductor muestra, porque la
  duración exacta la sabe el player, dentro de `RepReplay`.
- **Sombra dura en las filas de corrección** (el mock 2b la pinta en filas no
  seleccionadas): la regla global del brief manda sombra dura SÓLO en la
  acción principal de la pantalla; no la apliqué.
- **«Guardar sesión (+N XP)»**: el diseño pide «SIGUIENTE SERIE» → `onDone` y
  así está. `ResultsData.xp` se queda sin sitio en esta pantalla; si importa,
  hay que recolocarlo (no quise inventar ubicación).
- **`aboveAverage`** sigue en `ResultsData` (es público y tiene tests) pero la
  nota ya no lo pinta salvo como fallback cualitativo mientras no llegue
  `vsAverage`. Cuando el supervisor conecte `vsAverage`, `aboveAverage` puede
  jubilarse.
