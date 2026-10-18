# TIZA_NOTES — PROGRESO (diseño 2d)

Trabajado en: `app/src/main/java/com/barrapp/ui/tracker/TrackerProgress.kt` y
`app/src/main/java/com/barrapp/ui/tracker/SkillPath.kt` (+ sus tests). Compila
(`:app:compileDebugKotlin`) y los 128 tests unitarios pasan en verde.

## Qué he hecho

Pantalla Progreso rehecha según `TIZA_SPEC/2d.html` y sus notas «·»:

- **Selector de movimiento arriba**: chips mono en píldora con borde de 2px
  (seleccionada: tinta con texto papel; resto: blanco con tinta). Sólo si hay
  más de un movimiento.
- **Gráfico por movimiento**: tarjeta blanca con «CALIDAD MEDIA · N SEMANAS»
  (las semanas salen de las fechas reales de las sesiones), cambio «+11» en
  verde/rojo según suba o baje, la **media como banda horizontal sombreada**
  («BANDA = TU MEDIA», ±5 puntos alrededor de la media), línea de tinta de la
  calidad por sesión y un punto cuadrado de 8dp por sesión en el color de su
  banda (sin medir: no se dibuja punto, nunca 0 ni rojo). Etiquetas del eje
  («AGO», «SEP») sacadas del mes real de la primera/última sesión.
- **El historial vive en los puntos**: tocar cerca de un punto selecciona esa
  sesión (un anillo la marca) y despliega la tarjeta de la sesión: fecha
  humana, «N reps · X pts» o «sin puntuar», la nota y «ABRIR SESIÓN», que usa
  el callback existente `onOpenDay(date)` (abre el Sheet.SESSION de
  TrackerRoot). Tocar el mismo punto la suelta.
- **Dos datos**: «MÁX. REPS LIMPIAS» y «MEJOR REP» en tarjetas de 2 columnas.
- **CAMINO DE SKILLS como camino vertical** (componente nuevo
  `SkillPathSteps` en `SkillPath.kt`): cada paso con su marca — hecho (punto
  de tinta con ✓), siguiente (el único punto naranja) o bloqueado (punto
  papel, nombre en gris) — y la línea «Te falta: …» una sola vez en toda la
  app, bajo el paso siguiente. «VER COMPLETO» abre el camino entero
  (`onOpenSkills`, Sheet.SKILLS).
- **El calendario/historial en lista desaparece** de esta pantalla, como pide
  el diseño. También desaparecen las tarjetas de récords personales, de
  errores de 4 semanas y las 3 fichas sueltas (ver «No he podido / decisiones»).
- Estado vacío intacto: sin nada medido, tarjeta «SIN DATOS TODAVÍA» con el
  botón principal «Grabar un set» (única sombra dura de la pantalla).
- El título es «PROGRESO» a secas, como la maqueta (quité el eyebrow
  «BarrApp» que llevaba antes).

## Campos nuevos en `ProgressData` (todos con valor por defecto)

```kotlin
val movements: List<MovementSeries> = emptyList(),  // un gráfico por movimiento
val path: List<PathStep> = emptyList(),             // camino de skills vertical
```

Tipos nuevos: `SessionPoint(date, dateLabel, score, reps = 0, note = "")` y
`MovementSeries(id, label, sessions, average, delta, maxCleanReps, bestRep)`,
más `PathStep(id, name, note, state, next, missing)` en `SkillPath.kt`.
La firma pública de `TrackerProgress(...)` y `SkillPathScreen(...)` no cambia.

### De dónde deberían salir (para conectarlos en TrackerRoot)

- **`movements`**: un `MovementSeries` por movimiento entrenado, a partir de
  `state.days` medidos, agrupando por `byMovement`:
  - `sessions` en orden de fecha ascendente: `SessionPoint(day.date,
    shortDate(day.date), day.byMovement[mov]?.score, day.byMovement[mov]?.verified ?: 0,
    note = ...)`. El `score` por movimiento (`MovementDay.score`) es la media
    de las reps verificadas de ese movimiento ese día.
  - `note` de cada sesión: el fallo dominante de ese día en humano
    (`com.barrapp.faultEs(...)`), o "". Cada nota apunta al vídeo del día.
  - `average` = media de los `score` de las sesiones; `delta` = media de la
    2ª mitad − media de la 1ª («+11» del diseño).
  - `maxCleanReps` = máximo de `MovementDay.verified` en un día (reps limpias,
    no totales).
  - `bestRep` = mejor calidad de **una sola rep** jamás medida del movimiento
    (por eso el diseño muestra 86 con días de ~60: es rep, no día). Sale de
    las `RepRow.score` de los análisis guardados del movimiento. Si no hay
    datos por rep, pasar null (la ficha pinta «—», no inventa).
  - `id` estable (el exercise id, no el nombre) para que la selección del chip
    sobreviva a recomposiciones.
- **`path`**: en `TrackerRoot` ya existe todo lo necesario
  (`SkillsSheet` hace lo mismo):
  ```kotlin
  val spd = skillPathData(graph, target, graph.verifiedFrom(state.days), goal)
  path = spd?.let { pathSteps(it, missingForNext(graph, it.next, state.days)) }.orEmpty()
  ```
  `pathSteps(...)` construye los pasos («Completado» / «Hecho» /
  «Ahora: <estándar>» / «Bloqueado hasta completar el anterior») y
  `missingForNext(graph, next, days)` calcula el hueco real con los días
  medidos («2 repeticiones más en una sesión (vas por 4), y calidad 60 o más
  (mejor hasta ahora: 55), y 1 día más que cumpla»). Sin ese argumento la
  línea «Te falta» no se pinta: nunca se inventa un hueco.

### Puente mientras `movements` no esté conectado

Si `movements` viene vacío, la pantalla **pliega `history`** (que TrackerRoot
ya rellena) en series por movimiento (`movementSeriesFrom`, interna, con
tests). Así la página muestra datos reales del atleta y no una maqueta; en
cuanto conectes `movements`, el puente deja de usarse solo.

## Qué NO he podido hacer / decisiones que el supervisor debe revisar

1. **`onOpenLadder` queda sin uso.** El diseño 2d quita el historial y su
   enlace «VER ESCALERA»; la escalera (Sheet.LADDER) sigue existiendo pero
   nada de esta pantalla enlaza a ella. Mantengo el parámetro por compatibilidad
   (la firma no cambia). Si nadie debe enlazarla, quitarlo en su día.
2. **`bests`, `faults`, `trend` y `history` siguen en `ProgressData` pero esta
   pantalla ya no pinta récords personales ni barras de errores**: el diseño
   2d no los incluye. No he borrado los campos (TrackerRoot los construye y no
   puedo tocarlo). `history` además alimenta el puente. Si el supervisor los
   da por muertos, limpiar campos y `progressData`.
3. **«Te falta» por defecto no aparece hasta conectar `missingForNext`**: con
   un `Set<String>` de skills verificadas no se puede calcular el hueco (falta
   el detalle de reps/calidad por día). He dejado la función lista y probada;
   hay que pasarla en el `pathSteps(...)` de TrackerRoot (arriba).
4. **Chips de 48dp en vez de los 36px de la maqueta**: la regla de calidad del
   encargo pide objetivos táctiles ≥48dp y ganó. La píldora y los colores son
   los del diseño.
5. **Ancho de la banda = media ±5 puntos**: en la maqueta la banda es
   decorativa (no coincide con la media de sus datos de ejemplo); la intención
   «tu media como banda» se cumple con una tolerancia fija y legible.
6. **Sesiones sin puntuar**: no tienen punto en el gráfico (no hay calidad que
   dibujar) pero sí se pueden seleccionar y su tarjeta dice «sin puntuar».
7. La nota «Ahora: …» del paso siguiente sale del estándar de la skill
   (`nextStandard` sin la coletilla «barra lo verifica…»); el «vas por 3» del
   mock entra por `missing`/`note` cuando el supervisor conecte los días.

## Tests

- `ProgressPathTest` (nuevo, 9 tests): plegado de history → series, media/delta,
  título de semanas reales, meses del eje, `dayNumber` (algoritmo de Hinnant,
  rechaza fechas imposibles como 2026-02-31), `pathSteps` (marca el siguiente
  una sola vez, nadie más dice «Te falta»), `missingForNext` (hueco real,
  nada medido, estándar cumplido, skill no medible).
- `TrackerScreenshotTest.progress` actualizado: ahora alimenta `movements` y
  `path` (captura `tracker-progress.png`); añadido `progressBridge` para el
  estado puente (`tracker-progress-bridge.png`). Ambas en `app/build/screenshots`.
- Ningún test existente comprobaba textos que el diseño haya cambiado (el
  resto de la suite pasa sin tocarla).
