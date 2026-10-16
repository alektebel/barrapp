# Auditoría del pipeline de análisis de técnica

Fecha: 16 de octubre de 2026.

## Objetivo

Detectar y comunicar únicamente los errores de mala técnica que estén demostrados en el vídeo. La salida debe indicar qué error se observa, cuándo ocurre y qué evidencia lo sostiene.

Las puntuaciones, los elogios y las recomendaciones para próximas sesiones quedan fuera de este objetivo. La recurrencia puede servir para ordenar los errores, pero no debe ocultar un incidente aislado bien demostrado.

## Conclusión

El pipeline todavía no garantiza que todo lo que presenta como mala técnica sea un error visible en el vídeo. Tiene buenas bases —evidencia por repetición, fases y abstención cuando falta visibilidad—, pero existen vías para introducir afirmaciones no sustentadas, aplicar criterios de una variante incorrecta y omitir errores puntuales.

## Alcance y límites

- Revisión del código de medición, reglas, selección de errores, análisis visual y generación del informe.
- Reproducciones locales de los comportamientos descritos abajo.
- Ejecución de 54 tests relevantes: todos pasaron.
- Consulta de un informe histórico de evaluación, que no representa una medición de precisión de la versión actual.
- No se ejecutó un nuevo análisis completo de vídeos ni una revisión humana de su técnica.
- Esta auditoría no modificó el código del pipeline. Las propuestas siguen pendientes de implementación.

## Hallazgos

### 1. El informe puede inventar errores aunque pase su validación

**Prioridad: alta.**

El validador del informe comprueba que no haya números inventados, pero no verifica que los errores mencionados existan en los resultados medidos.

**Comprobación:** `_judge()` aceptó un informe con «Tienes valgo de rodilla» y «Se te hunde la cadera y pierdes el control escapular» cuando los datos aportados contenían una lista de repeticiones vacía. La ausencia de cifras permite que estas afirmaciones pasen el filtro actual.

**Impacto:** el texto que recibe el usuario puede atribuirle errores que el pipeline no ha detectado.

**Mejora propuesta:** generar el texto exclusivamente desde errores validados. Cada afirmación debe referenciar un identificador de error y su evidencia. Un texto sin respaldo debe rechazarse; una plantilla determinista puede cubrir esta salida sin necesitar generación libre.

**Código:** [server/report.py](../server/report.py), funciones `digest()`, `_judge()` e `invented_numbers()`.

### 2. Algunas etiquetas afirman más de lo que se mide

**Prioridad: alta.**

En front lever y planche, la medición de codos flexionados produce etiquetas de mala retracción o protracción escapular. El propio registro de reglas reconoce que la flexión de codos no demuestra ese diagnóstico.

También se interpreta una proporción entre la duración de la bajada y la subida como pérdida de control. Esa regla establece una equivalencia que necesita validación adicional: medir una proporción temporal no demuestra por sí solo cómo se controló el movimiento.

**Impacto:** una medida puede ser correcta mientras que el error comunicado no está demostrado.

**Mejora propuesta:** describir el hecho observable —por ejemplo, «codos flexionados»— y exigir evidencia adicional antes de afirmar una causa o falta de control. Revisar cada regla separando la variable medida de la conclusión que se comunica.

**Código:** [barra/rules.py](../barra/rules.py), reglas `front_lever.bent_arms`, `planche.bent_arms` y reglas basadas en `tempo_ratio`.

### 3. El detector de valgo no distingue desviación hacia dentro de desviación hacia fuera

**Prioridad: alta.**

`_knee_valgus()` utiliza el valor absoluto del desplazamiento horizontal de la rodilla respecto a la referencia de cadera y tobillo. El signo se pierde antes de aplicar el umbral.

**Comprobación:** con datos sintéticos, desplazamientos de `-0.4` y `+0.4` produjeron la misma medida: `0.4`.

**Impacto:** desviaciones en sentidos opuestos pueden producir la misma etiqueta de valgo.

**Mejora propuesta:** conservar y resolver la dirección respecto al cuerpo y a cada pierna, manteniendo la restricción de vista adecuada. Verificar explícitamente desviación medial, lateral y alineación neutra.

**Código:** [barra/evidence.py](../barra/evidence.py), función `_knee_valgus()`; [barra/rules.py](../barra/rules.py), reglas `knee_medial_drift`.

### 4. Una variante no declarada activa reglas que pueden no corresponder

**Prioridad: alta.**

`Rule.applies_to()` mantiene todas las reglas cuando la variante es `unspecified`, incluidas las que dependen de una ejecución estricta o de una posición completa.

**Comprobación:** `pull_up.body_swing` devuelve que es aplicable a `unspecified`, aunque es una regla restringida a la variante estricta cuando esta se declara.

**Impacto:** puede juzgarse el balanceo con el criterio de una dominada estricta, o las rodillas flexionadas con el de un front lever completo, sin haber confirmado esa variante.

**Mejora propuesta:** abstenerse en las reglas dependientes de variante hasta identificarla con suficiente evidencia o disponer de una declaración explícita. Continuar evaluando las reglas independientes de ella.

**Código:** [barra/rules.py](../barra/rules.py), método `Rule.applies_to()`.

### 5. La validación visual admite evidencia que no corresponde al fallo

**Prioridad: alta.**

`validate_observations()` comprueba que los identificadores y nombres de fotogramas existan, pero no exige que una observación tenga imágenes ni que estas correspondan a la repetición y fase indicadas.

**Comprobaciones:** se aceptaron tanto una observación sin fotogramas como otra atribuida a la repetición 2 en fase de soporte usando una imagen de la repetición 1 en fase de preparación. También se aceptó una descripción vacía.

**Impacto:** una observación visual puede superar la validación estructural sin que sus referencias sostengan la afirmación. Actualmente estas observaciones se conservan como auxiliares; no sustituyen las mediciones, el conteo ni la puntuación.

**Mejora propuesta:** para un error marcado como observado, exigir evidencia visual no vacía y coherente con la repetición y la fase, descripción del hecho visible y compatibilidad con la variante. Definir requisitos distintos para estados como `unobservable`.

**Código:** [server/vision.py](../server/vision.py), funciones `validate_observations()` y `_known_rules()`; [server/process.py](../server/process.py), función `add_vision()`.

### 6. Se pueden ocultar errores reales que ocurren una sola vez

**Prioridad: media-alta.**

El resumen exige normalmente dos repeticiones con el mismo fallo. Esta política reduce falsas alarmas, pero también elimina del resumen incidentes aislados. El detalle por repetición conserva esos errores.

**Comprobación:** una lista de tres repeticiones con `lockout` en una sola produjo un resumen vacío en `clip_fault_counts()`.

Además, el análisis visual utiliza tres repeticiones representativas mediante imágenes de fases, con un presupuesto de 16 fotogramas. Este muestreo puede dejar fuera un error puntual y no aporta una secuencia continua para verificar errores dinámicos.

**Mejora propuesta:** conservar cualquier incidente suficientemente demostrado y usar su recurrencia para ordenar. Seleccionar secuencias alrededor de cada candidato y revisar la cobertura de las repeticiones no muestreadas. Eliminar el filtro de recurrencia sin reforzar la evidencia podría aumentar las falsas alarmas.

**Código:** [barra/fault_select.py](../barra/fault_select.py), funciones `clip_fault_counts()` y `top_fixes()`; [barra/config.py](../barra/config.py), `fault_min_reps`; [barra/frames.py](../barra/frames.py), `REPS_SAMPLED` y `MAX_STILLS`.

### 7. La evaluación consultada no acredita precisión frente a revisión humana

**Prioridad: alta para validar las mejoras.**

El informe histórico consultado, generado el 13 de septiembre de 2026, contiene 109 clips etiquetados por modelo y ninguno por humanos. Registra 107 clips medidos.

**Impacto:** permite estudiar acuerdos y desacuerdos entre sistemas, pero no demuestra que los errores sean correctos frente a una referencia humana. Tampoco permite atribuir sus resultados a la versión actual del pipeline.

**Mejora propuesta:** construir un conjunto revisado por humanos, con errores y momentos identificados, ejemplos sin errores y casos no evaluables. Incluir distintas variantes, vistas y condiciones de oclusión. Reservar un conjunto separado para evaluar los cambios sin ajustar los umbrales sobre él.

**Métricas necesarias:** precisión y errores omitidos por tipo de fallo, falsas alarmas por vídeo, cobertura evaluable, abstenciones y exactitud de la localización temporal. Medir también los incidentes aislados.

**Evidencia histórica:** [out/fault-eval-min2/report.json](../out/fault-eval-min2/report.json). Este archivo es un artefacto local y puede no estar disponible en otros clones.

## Salida propuesta para el producto

Mostrar únicamente errores observables y respaldados. Cada error debe incluir:

- Descripción concreta del hecho visible, sin atribuir causas no demostradas.
- Momento o intervalo del vídeo donde ocurre.
- Repeticiones afectadas, si se pueden identificar.
- Evidencia visual vinculada al intervalo y a la regla aplicada.

Agrupar las apariciones del mismo error sin eliminar incidentes aislados. No rellenar la salida para alcanzar un número mínimo de errores.

Cuando no se comuniquen errores, distinguir entre:

- **No se han detectado errores en lo evaluable:** no equivale a certificar toda la técnica.
- **No se ha podido evaluar:** indicar brevemente la limitación de visibilidad, variante o seguimiento que impide concluir.

## Orden de actuación recomendado

1. Cerrar la vía de afirmaciones inventadas en el informe y exigir trazabilidad entre texto, error y evidencia.
2. Corregir la dirección del detector de valgo, las etiquetas que exceden la medición y la aplicación de reglas con variante desconocida.
3. Reforzar la coherencia entre observaciones visuales, fotogramas, repeticiones y fases.
4. Conservar incidentes aislados con evidencia suficiente y mejorar el muestreo temporal de candidatos.
5. Validar los cambios con revisión humana antes de afirmar una mejora de precisión.

## Verificación realizada

Se ejecutó:

```bash
.venv/bin/python -m pytest -q \
  tests/test_faults_evidence.py \
  tests/test_fault_select.py \
  tests/test_top_fixes.py \
  tests/test_technique_phases.py \
  tests/test_vision_validation.py \
  tests/test_angle_mask.py
```

Resultado: **54 tests pasaron**. Las reproducciones de esta auditoría muestran comportamientos que esa selección de tests no impide. Que los tests pasen no acredita precisión de detección sobre vídeos reales.
