# barrapp — QA Pase 2 (hallazgos + mejoras propuestas)

- **Fecha:** 2026-09-06 16:31–16:40, mismo dispositivo (1080×2400, `eida4h4xamzhroeq`)
- **Contexto:** continuacion de `feedback.md` (pases 1–3) y `ux-tree.md`. Este pase
  exploro: estados post-medicion, Coach con teclado, calendario multi-mes, boton atras
  de hardware, y reinicio en frio.
- **Nuevas fallas N1–N9 + propuestas M-1…M-8.**

---

## Fallas nuevas

### N1. (CRITICA) El boton "atras" de hardware cierra la app desde sub-pantallas
Repro: Calendar → fila de sesion (540,1550) → detalle abre → KEYCODE_BACK → **landing del
launcher** (`app.olauncher` en el dump), no Calendar. Reproducido 2x (tambien desde
detalle via fila 5 Sept). La pila de navegacion no hace pop del destino detalle; el
usuario pierde todo el contexto y la app "desaparece".

### N2. (CRITICA) Octubre muestra las sesiones de Septiembre con otros numeros
Vista Octubre 2026 (flecha › tras reinicio): "2 MEASURED DAYS · **908 reps in October**"
y las filas "Push-up **289 reps** · 5 Sept" y "Push-up **619 reps** · 4 Sept".
- Las sesiones de septiebre filtran dentro de octubre (filtro de mes roto).
- Los conteos difieren de la vista de Septiembre (269/598) y de Coach (249): **el mismo
  session muestra 3–4 valores distintos segun pantalla/momento**.

### N3. (CRITICA) Deriva de numeros en cada recomposicion
Misma sesion "5 Sept": 189 → 269 → 289 reps; "4 Sept": 514 → 598 → 619; Week total:
703 → 744 → 867. Ninguna medicion nueva justifica los saltos (+80/+84 sin clips nuevos).
Sin indicador de "re-medido", el usuario no puede confiar en ninguna cifra.

### N4. (ALTA) Coach: el input queda oculto tras la barra de navegacion
Al recibir respuestas nuevas y scrollear al fondo, el campo "Ask about your training" y
el boton ↑ **desaparecen del todo** (nodos ausentes en el dump); el ultimo mensaje queda
cortado detras de la nav bar. El chat no auto-scrollea a los mensajes nuevos (la respuesta
llego tapada). Falta bottom-padding = altura de la nav bar.

### N5. (ALTA) Coach: mensajes duplicados + respuestas sin estado pendiente
- "What did my last session actually show?" + su respuesta aparecen **duplicados**
  consecutivamente en el historial (burbujas identicas, mismo texto).
- La respuesta a "Am I getting better…" tardo ~10 min y llego sin ningun indicador de
  espera/error (revira B2: no es fallo silencioso total — es latencia extrema sin UI).
- La app no tiene forma de saber que "1 recorded session" es viejo: el historico muestra
  respuestas obsoletas junto a datos nuevos.

### N6. (MEDIA) Tres formatos de fecha distintos para el mismo campo
- "THU 14 AUG · MUSCLE-UP" (detalla vieja)
- "2026-09-05 · PUSH_UP" (enum crudo + ISO)
- "5 SEPT · PUSH UP" (tras reinicio — ahora si abre la sesion correcta)
Un formatter compartida y humanizada.

### N7. (MEDIA) Hoy no queda marcado en el calendario
Grabo y mido clips el dom 6 Sept; el dia 6 sigue vacio (ni relleno ni punteado) y las
reps se atribuyen a los dias 4/5. "across 2 days" tampoco se actualiza. Atribucion de
fecha de medicion incorrecta (usa fecha del clip viejo, no fecha de medicion).

### N8. (MEDIA) Controles "muertos" dependen del estado de navegacion
- Flechas ‹ › del calendario: `clickable=false` y sin efecto en plena sesion (B8);
  tras reinicio en frio funcionan (Octubre abre).
- B1 (detalle siempre abre Aug-14): tras reinicio abre la sesion correcta.
Ambos bugs desaparecen con restart → handlers/perda enlazados a un state que se corrompe
al navegar (posible recomposicion con capturas viejas). Difficil de ver sin A/B de restart.

### N9. (BAJA) El prefijo "Still needed:" es inconsistente en Ladder
Pase 1: "Still needed: Still needed: …" (duplicado). Pase 2: Muscle-up con un prefijo
correcto y **Pull up sin prefijo** ("Film a set. 8 verified reps is the bar."). La
plantilla se aplica 0, 1 o 2 veces segun el estado de datos.

### Nota: B6 (fila 28/29/30 desalineada) se auto-resolvio
Tras la actualizacion de datos, la ultima fila cuadricula bien. Bug de layout
dependiente de estado, no constante — seguir con ojo.

---

## Mejoras propuestas

| # | Mejora | Falla que mitiga |
|---|---|---|
| M-1 | Back stack correcta (Compose `navigateUp`/predictive back) en detalle, midiendo, work log | N1 |
| M-2 | Fuente unica de verdad de conteos: el resultado de medicion se guarda una vez y se muestra identico en todas las vistas; si re-mide, mostrar badge "re-medido" con delta | N2, N3 |
| M-3 | Filtro de mes en Calendar por fecha de **sesion**, no por fecha de medicion | N2, N7 |
| M-4 | Chat: `imePadding` + padding inferior = nav bar; auto-scroll a nuevo mensaje; deduplicar por id de mensaje; estado "Barra esta pensando…" + timeout con reintento | N4, N5 |
| M-5 | Un solo formatter de fecha (ej. "Sat 5 Sept") para cabeceras y chips | N6 |
| M-6 | Marcar hoy en calendario con estilo propio (ej. borde) y dia "medido hoy" aunque la sesion sea antigua | N7 |
| M-7 | Si un control no tiene handler activo (flechas, replay), deshabilitarlo visualmente; anadir logs de "handler not attached" en debug | N8, B3, B8 |
| M-8 | Tests de recomposicion: render de Calendar/Week/Ladder con datos que cambian en vivo (job completa mientras el usuario esta en otra pestaña) | N3, N8, B6 |

## Que sigue funcionando bien
- Respuesta de Coach "Flat, within the resolution this has…" — honesta y bien redactada.
- Envio con input vacio se ignora; tras reinicio el detalle abre la sesion correcta.
- Octubre muestra empty-state limpio (solo dias sin datos).

## Pendiente para un pase 3
- Retry/Dismiss de la cola con server alcanzable; "Skip ahead to the result".
- Teclado soft visible (no abrio con `input tap` sobre el campo — verificar con `ime` activo).
- TalkBack completo; landscape; multi-seleccion en el picker.
