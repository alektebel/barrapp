# TIZA_NOTES — tarea COACH (diseño 2e)

## Qué he hecho

`TrackerCoach` (`app/src/main/java/com/barrapp/ui/tracker/TrackerCoach.kt`) deja de ser
el resumen de focos/reglas/ejercicios y es ahora la conversación del diseño `2e.html`:

- **Cabecera**: «COACH» en Archivo Black y «RESPONDE CON TUS DATOS · N SESIONES»
  (mono 11, muted) sobre borde inferior de 2dp de tinta, como la maqueta. Con 1 sesión
  dice «· 1 SESIÓN» y con 0 se queda en «RESPONDE CON TUS DATOS».
- **Conversación**: pregunta del usuario en burbuja de tinta con texto papel alineada a
  la derecha (máx. 280dp, el 78 % del diseño); respuesta en tarjeta blanca con borde de
  2dp alineada a la izquierda (máx. 320dp, el 90 %).
- **PRUEBA**: cada respuesta puede llevar una fila «PRUEBA · Rep 2 de ago vs rep 2 de
  hoy» (caja oscura de vídeo con triángulo play dibujado + etiqueta), tocable; llama a
  `onOpenProof(proof)`.
- **Regla B2 (pensar siempre)**: mientras `thinking` es true se muestra la burbuja
  «REVISANDO N SESIONES» con los tres puntos animados del diseño (`dotPulse`, 1 s,
  desfase 0/150/300 ms). Y el caso de fallo queda cubierto por construcción: si la
  última entrada es una pregunta y NO está pensando, aparece una tarjeta
  «Sin respuesta» con texto humano («Ahora mismo no he podido leer tus sesiones para
  contestar…») y botón «Reintentar», que reenvía la misma pregunta por `onSend`. Nunca
  queda una pregunta sin respuesta visible.
- **Chips sugeridos** sobre el campo, en FlowRow (el visual es la píldora de 36dp del
  diseño, con objetivo táctil de 48dp alrededor, como pide el brief).
- **Campo** «Pregunta sobre tus series…» (BasicTextField en caja blanca de 48dp con
  borde 2dp; toda la caja es el tap target, patrón del chat existente) y **botón enviar
  (↑) naranja** de 48dp con borde de tinta y esquinas de 12dp. `imePadding` para que el
  teclado no lo tape.
- **Estados honestos**: `notice` (última sesión sin puntuar) se muestra como tarjeta
  «SIN PUNTUAR» al principio de la conversación; sin conversación hay una tarjeta
  «Tu coach» que explica con qué contesta, y si `sessions == 0` lleva el botón principal
  «Grabar una serie» (única acción con sombra dura de la pantalla). Chips de reserva
  sólo si hay sesiones.
- Sin colores sueltos ni `Color.White`: todo por tokens (`Tk.ink`, `Tk.onInk`,
  `Tk.surface`, `Tk.dark`, `Tk.primary`, `Tk.locked`…).

Firma pública intacta: `TrackerCoach(data, onAskCoach, onRecord, modifier)` — sólo
añadí `onSend` y `onOpenProof`, ambos con valor por defecto. `CoachRule`, `CoachFocus` y
el resto de campos de `CoachData` siguen existiendo (TrackerRoot los construye), pero
esta pantalla ya no los pinta.

Tests: reescribí `TrackerScreenshotTest.coach` (conversación con PRUEBA) y añadí
`coachThinking` (burbuja REVISANDO) y `coachEmpty` (vacío con CTA de grabar). Compila y
`./gradlew -q :app:testDebugUnitTest` pasa entero.

## Campos nuevos que necesita la pantalla (y de dónde deberían salir)

Todos añadidos a `CoachData` **con valor por defecto**, así que compila sin tocar
`TrackerRoot`. Para que la pantalla muestre datos reales, el supervisor debe conectar:

1. `conversation: List<CoachMessage>` ← `state.chat` mapeado:
   `ChatTurn(fromUser, text) → CoachMessage(fromUser, text)`.
   `CoachMessage(text, proof)` y `CoachProof(label, sessionDate, repIndex)` son clases
   nuevas en `TrackerCoach.kt`.
2. `thinking: Boolean` ← `state.coachThinking`. **Crítico**: si no se conecta, cada
   pregunta sin respuesta mostrará la tarjeta de reintento (es la regla B2 del diseño).
3. `suggestions: List<String>` ← `vm.suggestions()` (ya existe, `Coach.suggestions`).
   Si viene vacía, la pantalla saca 3 chips genéricos de `data.movement`
   («¿Estoy mejorando en Dominada?», «¿Qué mostró realmente mi última sesión?», «¿Por qué
   algunas repeticiones no tienen puntuación?» — todas rutean bien en `Coach.answer`).
4. `sessions` ← **quitar el `coerceAtMost(4)`** de `coachData` en TrackerRoot (línea
   ~667): la cabecera y el burbujeo «REVISANDO» deben decir el número real de sesiones
   del diseño («14 SESIONES»), no un tope de 4.
5. `onSend: (String) -> Unit` ← `vm::ask`. Su valor por defecto hoy hace puente a
   `onAskCoach()` (abre el sheet de chat antiguo) para que el botón nunca esté muerto,
   pero pierde el texto tecleado: hay que cablearla de verdad.
6. `onOpenProof: (CoachProof) -> Unit` ← abrir la sesión `sessionDate` (sheet SESSION)
   y, con `repIndex > 0`, el replay de esa rep (`RepReplayState.seekTo`). Necesita saber
   qué clip de ese día es la prueba.
7. `CoachMessage.proof` ← el pipeline de respuestas tiene que adjuntar la evidencia.
   Hoy `Coach.answer` devuelve un `String` plano, así que **no saldrá ninguna fila
   PRUEBA** hasta que las respuestas sean estructuradas. Los datos para construir el
   `label` ya existen: `RepRow`/`MeasuredFault.intervalS` y `shortDateEs` para
   «Rep 2 de ago vs rep 2 de hoy».

## Qué NO he podido hacer y por qué

- **La conversación real no está cableada** (no puedo tocar `TrackerRoot.kt` ni
  `BarrappViewModel.kt`): la pantalla pinta lo que llegue en `conversation`; con los
  valores por defecto muestra la intro y los chips de reserva. Ver puntos 1–5 arriba.
- **Filas PRUEBA con datos reales**: igual que el punto 6 — el modelo de datos de las
  respuestas no existe todavía; dejé la UI lista y el `CoachProof` documentado.
- **Negritas dentro de las respuestas** («pasó de **58 a 69**» en la maqueta): las
  respuestas llegan como `String` plano; marcado tipo Markdown habría que acordarlo con
  el generador de respuestas antes de renderizarlo.
- **Botón de enviar gris con el campo vacío**: la maqueta lo pinta siempre naranja; lo
  dejo deshabilitado en `Tk.locked` cuando no hay texto (patrón de `TkPrimaryButton`),
  porque el naranja es para lo que pide acción y un botón deshabilitado no actúa. Si el
  supervisor prefiere el naranja constante, es una línea.
- **El contenido antiguo (foco de hoy, reglas, ejercicios) ya no está en esta pestaña**:
  el 2e es sólo conversación. Las clases siguen en el fichero porque el origen de datos
  las construye; si ese contenido tiene que vivir en otra pantalla (el historial/reglas
  del 2d), hace falta decidirlo y moverlo ahí.
- **El sheet CHAT antiguo** (`Sheet.CHAT` → `ui.CoachScreen`, estilo Nocturne) sigue
  existiendo en TrackerRoot: fuera de mis ficheros. Cuando `onSend` esté cableado a
  `vm::ask`, ese sheet sobra para esta pestaña.
