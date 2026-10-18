# TIZA_NOTES — pantalla INICIO (diseño 2a)

## Qué he hecho

Todo en `app/src/main/java/com/barrapp/ui/tracker/TrackerHome.kt` (más el fixture de
`TrackerScreenshotTest.kt`, que es el test de esa pantalla). La firma pública de
`TrackerHome(...)` no cambia; `TrackerRoot` no hace falta tocarlo.

- **Cabecera 2a**: fecha de hoy en mono («DOMINGO 18 OCT», la calcula la pantalla con
  `SimpleDateFormat` en español) y «HOLA, <NOMBRE>» en Archivo Black 30, con el avatar
  de iniciales (44dp, borde 2px, esquina 12dp) a la derecha. Fuera el badge de fuego
  de la racha: la racha vive ahora en la franja.
- **UNA franja de 3 datos** con separadores de 2px de tinta (racha · NV/XP total ·
  sesiones de la semana), borde 2px y esquinas 14dp. Desaparecen la tarjeta de XP y la
  de semana; la celda de la semana abre el calendario (`onOpenCalendar`) y en el XP se
  muestra el total con agrupación española («411 XP», «1.240»…).
- **Misión de hoy**: `TkCard(accent = true)` con sombra dura (la única de la pantalla)
  y el botón de tinta «GRABAR SERIE» dentro (`TkPrimaryButton(..., shadow = false)`
  para no duplicar la sombra; el cursor del diseño está en el botón, así que la tarjeta
  entera ya no es clicable). Misma misión de siempre (`data.mission`): título
  «N REPS · MOVIMIENTO», el foco del coach como texto, segmentes de progreso y la nota
  de reps medidas hoy. Los segmentos van de tinta sobre naranja: antes se rellenaban
  de naranja sobre tarjeta naranja y desaparecían; el track es `Tk.orangeSoft`.
- **Última sesión como clip**: etiqueta «ÚLTIMA SESIÓN · <fecha corta>» con «VER»
  subrayado a la derecha; debajo, tarjeta-clip (blanca, borde 2px, padding 8) con el
  fotograma oscuro de 88dp, el movimiento en Archivo Black, la nota en 22 coloreada con
  `scoreInk` (gris y «—» si no se puntuó), la línea «8 REPS · 3 SERIES» y **una barra
  por rep** (altura ∝ nota, color = banda con `scoreInk`; rep sin medir = tope gris de
  3dp, nunca 0 ni rojo). La tarjeta entera abre la sesión (`onOpenSession`).
- **SIGUIENTE LOGRO**: fila con borde 2px **discontinuo** (`Modifier.border` no hace
  dash; lo dibuja `drawBehind` + `PathEffect.dashPathEffect`), número grande, título
  humano, `Meter` de tinta y contador «5/8»; abre `onOpenLadder`. Sin dato, la fila no
  se pinta.
- **Estado vacío**: ceros reales (0, NV 1, 0 XP, 0/4), tarjeta-clip vacía con texto que
  invita a filmar (abre GRABAR), sin fila de logro. Nada inventado.
- **Quitado de Inicio**: la tarjeta de logros (badges) y la fila de «top fault → VER
  COACH». El diseño 2a no las tiene; ver «Cambios que el supervisor debe validar».

## Campos nuevos (todos con valor por defecto; TrackerRoot y el test compilan sin tocarlos)

- `HomeData.nextGoal: NextGoalData? = null` — el peldaño actual de la escalera.
  Debería salir de `Progression.verdicts(days, focus)` igual que `LadderSheet`:
  primer verdict con `step != null && qualifyingDays.size < step.days`, con
  `label` humano (p. ej. «8 dominadas por encima de 70»), `done = qualifyingDays.size`,
  `target = step.days`. Con `null` o `target <= 0` la fila no aparece.
- `HomeData.weekTarget: Int = 0` — sesiones objetivo por semana, para el «3/4» del
  diseño. Derivarlo de `Profile.activity` (Occasional→2, Regular→4, Daily→5…) o del
  modelo de objetivos. Con 0 la celda muestra sólo el contador de la semana.
- `LastSessionData.repScores: List<Int?> = emptyList()` — nota por rep del último clip,
  en orden de rep, `null` donde el modelo no leyó. Fuente: los `RepRow` del análisis del
  último job (`Analysis`/traceId en el estado del VM; el día guarda `traces`). Mientras
  esté vacío, la tira cae a la nota agregada (un `Meter`) — no se dibuja nada no medido.
- `LastSessionData.sets: Int = 1` — clips (series) que suma la sesión, para la línea
  «8 REPS · 3 SERIES». Saldría de `day.jobIds.size` (o 1 cuando la tarjeta describe un
  único clip).

## Lo que NO he podido hacer (y por qué)

- **Fotograma real del clip**: no hay thumbnail ni acceso al vídeo en los datos que
  recibe la pantalla. Dibujo el fondo oscuro de 88dp con la barra insinuada
  (`Tk.dark`/`Tk.darkLine`) y lo marco decorativo para TalkBack. Si el supervisor pasa
  un `Painter`/bitmap por `LastSessionData`, la caja ya está en su sitio.
- **Esqueleto animado sobre la miniatura** (el SVG de la maqueta): sin datos de pose en
  Inicio; no se puede dibujar sin inventarlo.
- **Barras por rep reales en producción**: dependen de `repScores`, que el supervisor
  debe conectar (arriba). El fallback honesto es el `Meter` de la nota agregada.
- **«ÚLTIMA SESIÓN · AYER»**: `LastSessionData.date` llega como fecha corta («8 sept»).
  Para la fecha relativa del diseño hace falta calcularla del ISO del día
  (`shortDateEs` vive en Coach.kt; sería natural añadir un `dateLabel` con «AYER»/«HOY»
  en `TrackerRoot.homeData`).
- **onOpenCoach queda sin usar en Inicio**: el 2a no tiene ninguna entrada al coach
  (la pista del fault ya vive en la tarjeta de Coach). Mantengo el parámetro para no
  romper la firma; si nadie lo quiere, sobra.
- **Título de misión literal del diseño** («3 SERIES DE 6 DOMINADAS SIN BALANCEO»):
  `Mission` no tiene series ni un foco corto; con los datos reales el título es
  «N REPS · MOVIMIENTO» y el foco va como línea de texto.

## Cambios que el supervisor debe validar

- **Los badges ya no se pintan en Inicio** (el 2a no los muestra; el camino de logros
  es la escalera, que sigue abriéndose desde «SIGUIENTE LOGRO»). `HomeData.badges`
  sigue llegando y `Gamification.badges` sigue computándolos; si se quieren en otro
  sitio, PROGRESO es el candidato.
- **La fila de «top fault» desaparece de Inicio**; `LastSessionData.topFault` sigue
  llegando (ahora sin consumir). El foco correctivo ya está en la misión y en COACH.
- **Test actualizado**: el fixture de `TrackerScreenshotTest.sampleHome` ahora pasa
  `repScores`, `sets`, `nextGoal` y `weekTarget` para que la captura muestre las partes
  nuevas. Ningún test comprobaba textos de Inicio, así que no hubo aserciones que
  cambiar.

Verificado: `./gradlew -q :app:compileDebugKotlin` ✓ y `./gradlew -q
:app:testDebugUnitTest` ✓ (capturas en `app/build/screenshots/tracker-home*.png`).
