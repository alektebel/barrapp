# Encargo: aplicar el diseño «Barrapp Tiza» a una pantalla de la app Android

Eres un worker. Un supervisor revisará y fusionará tu trabajo. Trabaja SÓLO en los
ficheros que tu tarea nombra. No toques ningún otro fichero (ni TrackerRoot.kt, ni
Models.kt, ni el tema): si necesitas un dato que tu pantalla no recibe, añade un campo
CON VALOR POR DEFECTO a la data class de tu pantalla y apúntalo en `TIZA_NOTES.md`
(en la raíz del repo) para que el supervisor lo conecte.

## Proyecto
- App Android en Kotlin + Jetpack Compose. Paquete `com.barrapp`. Código en
  `app/src/main/java/com/barrapp/ui/tracker/`.
- Compila con: `./gradlew -q :app:compileDebugKotlin` (desde la raíz del repo).
  Tests unitarios: `./gradlew -q :app:testDebugUnitTest`. Tu trabajo NO está terminado
  hasta que compila sin errores y los tests pasan.
- Sin dependencias nuevas.
- Haz `git add` y `git commit` de tus cambios al terminar (mensaje en español, una
  línea que diga qué cambia y por qué).

## El diseño
`TIZA_SPEC/` contiene el diseño exportado como HTML con estilos en línea (React con
plantillas `{{ }}`), una pantalla por fichero (`2a.html` … `3b.html`), `script.js` con
los datos de ejemplo y la lógica de la maqueta, y `notes.html` con las reglas globales.
Las líneas que empiezan por «·» bajo cada teléfono son la intención de la pantalla:
cúmplelas. Los datos de la maqueta (ALEX, 69, rep 4, 19°…) son de ejemplo: usa siempre
los datos reales que recibe la pantalla, nunca números inventados.

Reglas globales del sistema Tiza (obligatorias):
- Archivo Black para titulares, IBM Plex Mono para datos/etiquetas, Archivo para texto.
- Borde de 2px de tinta en tarjetas y controles. Esquinas 14dp (tarjetas) o 12dp (botones).
- Sombra dura SÓLO en la acción principal de la pantalla.
- Naranja SÓLO para lo que pide acción. Una nota nunca es naranja.
- Texto humano en español: nada de `PUSH_UP`, ids ni fechas ISO («Flexión», «Ayer 18:42»).
  Errores en lenguaje humano y con una acción para resolverlos.
- El vídeo es la prueba: cada nota, error o respuesta apunta a una rep concreta.

## Lo que ya existe (úsalo, no lo dupliques)
Tema en `ui/theme/Tracker.kt` (ya es Tiza):
- Colores `Tk.bg` (papel #F1EEE6), `Tk.surface` (blanco), `Tk.card` (papel, para
  recuadros dentro de una tarjeta), `Tk.ink` (#141414), `Tk.muted` (#5A564E),
  `Tk.border` (tinta), `Tk.line` (#D6D0C2, pistas y separadores suaves),
  `Tk.primary` (naranja acción #FF4F1A), `Tk.teal` (verde «correcto/fuerte» #1E9E63),
  `Tk.blue` (#2F6BFF, banda sólida), `Tk.amber` (#E39A00), `Tk.rose` (#D7263D),
  `Tk.dark` (#24221E, fondo detrás del vídeo), `Tk.darkLine`, `Tk.onInk` (texto papel
  sobre tinta), `Tk.orangeSoft`, `Tk.faint`, `Tk.locked`.
- Tipos: `display(size, weight, line, tracking, color)` (Archivo Black),
  `mono(size, tracking, color, weight, line)` (IBM Plex Mono), `body(size, color, line,
  weight)` (Archivo), y los estilos con nombre de `object T`.
- Bandas: `bandOf(score)`, `bandInk(band)`, `scoreInk(score)`, `scoreLabel(score)`.
  Cortes de barra 73/47/20: fuerte verde, sólida azul, inestable ámbar, rota rojo.
  Una rep sin medir es gris y «—», nunca 0 ni rojo.
En `ui/tracker/TrackerParts.kt`:
- `TkCard(accent = false)` tarjeta blanca con borde 2dp; `accent = true` es la tarjeta
  naranja con sombra dura (sólo la acción principal).
- `TkPrimaryButton(text, onClick, shadow = true)` losa de tinta, texto papel y punto
  naranja, 52dp. `TkSecondaryButton` blanca con borde, mono.
- `Modifier.hardShadow(shape)`, `FaultChip`, `ScoreRing`, `Meter`, `Eyebrow`,
  `SlideUp`, `StatTiles`, `CardShape` (14dp), `InnerShape` (12dp), `noRipple`.
- Reproductor de la serie: `ui/replay/RepReplay.kt` (`RepReplay`, `RepReplayState`
  con `seekTo`), y `ui/replay/ReplayTimeline.kt`.
- Datos del análisis: `com.barrapp.data.Analysis`, `RepRow` (startS, endS, turnS,
  score, band, faults: List<MeasuredFault>, checks…), `MeasuredFault` (errorId, value,
  threshold, comparison, unit, intervalS = [inicio, fin] en segundos del vídeo).
  Nombres en español de fallos: busca `faultEs` / `cueEs` en el código y úsalos.

## Calidad
- Objetivos táctiles de al menos 48dp. `contentDescription` en lo que sólo es gráfico.
- Debe verse bien con la fuente al 200 % (sin textos cortados: usa `maxLines` +
  `overflow` sólo donde el diseño lo pide; si no, deja que el texto baje de línea).
- Nada de colores sueltos `Color(0x…)` si existe el token. Nada de `Color.White` para
  texto: usa `Tk.ink` o `Tk.onInk`.
- Respeta los tests existentes; si un test comprueba un texto que el diseño cambia,
  actualiza el test y dilo en `TIZA_NOTES.md`.

## Al terminar
Escribe en `TIZA_NOTES.md`: qué has hecho, qué campos nuevos necesita tu pantalla y de
dónde deberían salir, y qué parte del diseño NO has podido hacer y por qué. Sé honesto:
el supervisor lo comprobará.
