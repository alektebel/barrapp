# TIZA_NOTES — VISOR DE FALLOS (3b) y CORRECCIÓN DE UNA REP (2c)

## Qué he hecho

Sólo ficheros nuevos, nada existente tocado (ni TrackerRoot, ni Models, ni el tema):

- `app/src/main/java/com/barrapp/ui/tracker/FaultViewer.kt` — diseño 3b.
- `app/src/main/java/com/barrapp/ui/tracker/RepCorrection.kt` — diseño 2c.
- Tests JVM: `app/src/test/java/com/barrapp/ui/tracker/FaultViewerTest.kt` (15) y
  `RepCorrectionTest.kt` (7). Toda la lógica pura (slides, regiones, avance con
  vuelta, zoom, formato de números, porqués, comparaciones) es función testeable
  sin Android; los composables son finos.

`./gradlew -q :app:compileDebugKotlin` compila y `./gradlew -q :app:testDebugUnitTest`
pasa entero (140 tests, 22 nuevos).

### FaultViewer (3b)

Historias a pantalla completa sobre `Tk.ink`: barras de progreso arriba (una por
fallo, la actual se llena en tiempo real), «FALLO 1 DE 3 · DOMINADA», fotograma
clave del clip en `atS` (`MediaMetadataRetriever.getFrameAtTime(us, OPTION_CLOSEST)`
en `LaunchedEffect` + `Dispatchers.IO`, retriever liberado en `finally`), a los
600 ms zoom animado (800 ms, `cubic-bezier(.22,1,.36,1)` del sistema) hacia la
región del cuerpo (`graphicsLayer` + `TransformOrigin`), y tras el zoom aparecen
la tarjeta naranja con el valor y el objetivo, y debajo el por qué + «PRÓXIMA
SERIE · cue». Avanza solo cada 4 s (pausa/reanuda tocando la cabecera, con el
botón II/▶ del mock), atrás/adelante tocando los lados (30 %), «VER LA REP A
0.5×» llama a `onPlayRep`. Si no hay clip o el fotograma no se lee, recuadro
oscuro con «REP n» y el tiempo. Sin fallos: «NADA QUE CORREGIR» con CERRAR
(nunca una pantalla vacía).

- `faultSlides(a: Analysis)`: recorre `a.reps[i].faults`, agrupa por
  `errorId.ifBlank { name }` (un fallo que se repite en varias reps colapsa en
  su peor rep), ordena por el exceso normalizado sobre el umbral (la misma
  fórmula de `ReplayPlan.exceedance` / `barra/fault_select`) y corta a 3.
- `atS` = punto medio de `intervalS` del fallo, o `turnS` de la rep si no hay
  (y `startS` si tampoco hay turnaround).
- `regionFor(errorId)` por palabras del id: lockout/elbow/chin/range/top →
  UPPER; hip/swing/kip/sag/core → MIDDLE; knee/depth/foot/leg → LOWER; si no
  FULL. Soporta snake_case y camelCase.
- Valor y objetivo salen de `MeasuredFault.value/threshold/comparison/unit`:
  `comparison` «<» dispara por debajo (lockout 76 % < 85 %) → «OBJETIVO MÁS DE
  85%»; el resto dispara por encima (swing 19° > 8°) → «OBJETIVO MENOS DE 8°».
  Un fallo sin número muestra «—», nunca 0.

### RepCorrection (2c)

Fondo papel: cabecera «← REP 4 · BALANCEO» + «0:14 · PAUSADO EN EL PUNTO CLAVE»,
dos fotogramas lado a lado («TU REP 4» / «TU MEJOR (REP 1)», mismo `keyFrame`),
valor grande + objetivo, título humano, por qué comparando contigo, tarjeta
«PRUEBA EN LA PRÓXIMA SERIE» con la cue, y el botón naranja «SIGUIENTE
CORRECCIÓN · n/N» con sombra dura (la única de la pantalla). `onNext == null`
oculta el botón (última corrección).

- `repCorrections(a: Analysis)`: un dato por fallo distinto (máx. 3, peor
  exceso primero). `rep` = la rep que peor muestra el fallo; `bestRep` = la rep
  con mayor `score` de la serie. Si la mejor rep midió el mismo fallo,
  `bestValue` es su número y el por qué cierra con «En tu mejor rep (la 1) se
  midió 0.1 torsos.»; si no (no la midió, no se puntuó nada, o la mejor rep ES
  la peor), `bestValue` es null y el por qué se queda en el número medido, sin
  comparación inventada.

## Campos nuevos / parámetros con valor por defecto (para el supervisor)

1. `FaultViewer(..., exercise: String = "")` — el «· DOMINADA» de la cabecera
   del mock necesita el movimiento y la firma pedida no lo traía. Pasar
   `analysis.exercise` (ya existe en `Models.kt`); se renderiza con
   `movementEs()`.
2. `RepCorrection(..., onPlay: (() -> Unit)? = null)` — el mock 2c tiene un
   control «0.5×» y la firma pedida no traía callback de reproducción. Sin
   conectar, el botón no se dibuja.
3. `onPlayRep(slide)` en FaultViewer entrega el slide actual: `slide.rep - 1`
   es el índice 0-based para `RepReplayState.showRep()` y `slide.atS` el
   segundo del vídeo.
4. `onClose` (FaultViewer) y `onBack` (RepCorrection) + probablemente un
   `BackHandler`: el mock 3b no dibuja ninguna salida y he añadido un ✕ de
   48 dp en la cabecera (mismo estilo que el de pausa); 2c sí trae su ←.

## Qué NO he podido hacer del diseño, y por qué

- **Huesos, ángulo dibujado, flechas y «posición correcta en verde» (3b y
  2c)**: el teléfono no recibe keypoints del esqueleto en el payload del
  análisis; no hay con qué dibujarlos. Tal como pedía la tarea, se muestra el
  fotograma real del clip (ampliado) y los datos medidos. **Pendiente para el
  servidor**: enviar keypoints por rep (o fotogramas ya anotados) con el
  resultado; las pantallas están listas para superponerlos dentro de la caja de
  vídeo.
- **Zoom por coordenadas exactas del mock (3b)**: los `crop`/`transform-origin`
  del mock apuntan a coordenadas del esqueleto. Sin keypoints, el zoom va a la
  región del cuerpo derivada del `errorId` (UPPER/MIDDLE/LOWER/FULL) y la
  escala es fija por región (1.6×; 1.2× en FULL) en vez del 1.55–2.2× variable
  del mock.
- **Título largo y prosa del por qué (2c)**: «LAS PIERNAS SE ADELANTAN PARA
  SUBIR» y «estás usando el impulso porque el dorsal ya va cansado» son texto
  del modelo que el servidor no envía por fallo. En su lugar: nombre del fallo
  (`faultEs`) como título, y un por qué compuesto sólo con lo medido
  («Balanceo: 0.3 torsos frente al máximo de 0.2 torsos.» + la comparación con
  tu mejor rep si la hay). Que el servidor envíe prosa en español por `errorId`
  (o por qué ya medido) es lo que falta para el texto del mock.
- **Tempo**: el script de la maqueta avanza cada 4,2 s; la tarea dice «cada 4 s»
  → `SLIDE_MS = 4000`.
- **Navegación**: TrackerRoot todavía no abre estas pantallas (fuera de mis
  ficheros). El clip se lo pasa quien las conecte; para eso está el clip que ya
  usa el replay (`vm.replayClip()`).

## Detalles de calidad

- Formato de números determinista (Locale.US): «19°», «0.45 torsos», «76%».
- Objetivos táctiles ≥ 48 dp (botones 48/52, zonas laterales grandes);
  `contentDescription` en todo lo que es sólo gráfico o icono.
- Al 200 % de fuente los textos bajan de línea (sin recortes); la única línea
  con elipsis es el título del visor 3b, donde el mock pide `white-space:nowrap`.
- Sin colores sueltos: todo por tokens (`Tk.*`), sin `Color.White` (papel
  `Tk.onInk` sobre tinta).
- Ningún test existente necesitó cambios: ninguno comprueba textos de estas
  pantallas nuevas.
- La barra de progreso de un conjunto de UN solo fallo se dibuja llena (no al
  0 % para siempre); el avance automático sólo corre con 2+ fallos.
