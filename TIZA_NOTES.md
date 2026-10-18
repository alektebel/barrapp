# TIZA_NOTES — Navegación + Onboarding

## Qué he hecho

**`TrackerShell.kt` (barra inferior, según `TIZA_SPEC/notes.html` y la plantilla `tabs()` de `script.js` + el grid de `2a.html`):**
- Barra de 4 pestañas iguales (grid de 4 columnas), borde superior de 2dp de tinta, fondo papel (`Tk.bg`), paddings 8/6/14 como el diseño.
- Cada pestaña: barra de 22×4dp **encima** del texto — naranja (`Tk.primary`) sólo en la activa, transparente en las demás — y etiqueta en IBM Plex Mono 11sp: tinta/peso 600 la activa, `Tk.muted`/peso 400 las inactivas. Sin iconos: el diseño dibuja sólo barra + texto, así que los cuatro iconos dibujados a mano que había (drawHome/drawRecord/drawProgress/drawCoach) se han eliminado (quedan en el histórico de git).
- Añadido `onHelp: () -> Unit = {}` a `TrackerShell` (tras `modifier`; no rompe llamadas existentes). El «?» vive al final de la barra: círculo blanco de 48dp con borde de tinta 2dp (es un control, no la acción principal: sin naranja ni sombra dura) y `contentDescription` «Ayuda: cómo filmar».
- La pestaña usa `heightIn(min = 48dp)` y deja que la etiqueta baje de línea con fuente grande (nada de `maxLines`/elipsis: «PROGRESO» no se corta).

**`TrackerOnboarding.kt` (sistema Tiza; lógica y orden de pasos intactos):**
- Tarjetas de elección: fondo blanco, borde de tinta de 2dp siempre; la elegida con fondo `Tk.orangeSoft` (borde sigue siendo tinta). El radio pasa a tinta con check de papel (`Tk.onInk`, se elimina un `Color.White`); antes era naranja.
- Puntos de progreso en tinta (`Tk.ink` para hecho/actual —el actual más ancho—, `Tk.line` para lo que falta). Antes eran naranjas.
- Campo de nombre: borde de 2dp de tinta siempre (antes 1,5dp y naranja al escribir) y cursor en tinta.
- Logo de la cabecera: caja blanca con borde de tinta 2dp (antes tinte naranja con borde naranja de 1dp). La propia marca sigue siendo naranja: es el logo del diseño.
- Briefing: el «MISIÓN ASIGNADA» y las líneas «Ejercicio principal»/«Objetivo» eran naranjas y son notas, no acciones → mono tinta (`T.eyebrowAccent`) y Archivo tinta. La caja del 🎯 pasa a tarjeta blanca con borde de 2dp (CardShape, 14dp).

**`TrimScreen.kt`:**
- El `RangeSlider` es un control de ajuste, no la acción de la pantalla (la acción es «Recortar y subir»): pulgar y pista activa en tinta, pista inactiva en `Tk.line` (antes todo naranja y la pista inactiva en `Tk.border`).
- La nota «X s de Y» estaba en `Tk.primaryLight` (una nota nunca es naranja) → `Tk.muted`; los valores elegidos (inicio/fin) en tinta.
- El recorte de fotograma usa el token `InnerShape` (12dp) en vez de un `RoundedCornerShape` suelto.

**Test nuevo:** `app/src/test/java/com/barrapp/ui/tracker/TrackerShellTest.kt` — comprueba que tocar PROGRESO avisa con `TrackerTab.PROGRESS` y que el «?» dispara `onHelp`. `./gradlew :app:testDebugUnitTest`: 120 tests, 0 fallos. `TrackerScreenshotTest` pasa sin cambios.

## Campos nuevos que necesita esta pantalla
- Ninguno. El onboarding y el trim ya reciben todos sus datos.

## Qué no he podido hacer y por qué
- **El «?» no lleva todavía a ninguna pantalla**: `onHelp` se expone con valor por defecto `{}`, pero conectarlo exige tocar `TrackerRoot.kt` (fuera de mis ficheros). El supervisor debe pasarle un callback que abra la ayuda de cómo filmar (p. ej. un overlay en `TrackerRoot`); el sitio del botón ya está en la barra, al final, con `contentDescription` «Ayuda: cómo filmar».
- **«← Week» sigue existiendo en `app/src/main/java/com/barrapp/ui/UploadScreen.kt` (líneas 37 y 142)**: es la pantalla de subida del diseño antiguo, no la barra de pestañas de `TrackerShell` (que nunca la tuvo). Es un fichero fuera de mi alcance; si esa pantalla sigue siendo alcanzable, hay que quitarlo ahí.
- **Pestañas activas sin icono**: fidelidad al diseño (su plantilla `tabs()` sólo dibuja barra + etiqueta). Si el supervisor quiere iconos, hay que decidirlo contra el diseño, no contra el código antiguo.
- Los valores de fondo de la barra: la tarea manda papel (`Tk.bg`) y es lo que he aplicado; el HTML del diseño usa blanco (#fff) en la barra. Lo apunto por si el supervisor prefiere el blanco exacto del mockup.
