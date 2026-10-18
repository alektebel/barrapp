"""Spanish at the edge: the catalog that turns barra's English into what the
phone shows.

barra writes its reasons in English and the trace keeps them that way - that
is the developer's record, and every test and replay reads it. The payload the
phone renders is translated once, when it is built (`localize_payload`), from
this catalog:

* `Msg(code, en, es)`: `en` is the template the source produces, with holes -
  `{name}` a number (sign, decimals and a trailing % allowed), `{name*}` a
  fragment that is translated in its own turn. `es` uses the same holes.
  `code` is stable: tests, analytics and the app can key on it.
* Numbers keep their digits and gain a decimal comma: 1.45 -> 1,45, 66% -> 66 %.
* What the catalog does not know is left untouched and listed under
  `payload["i18n"]["untranslated"]`; the payload sentinel reports it, so the
  catalog grows from what production actually says rather than from a guess.

Keys the app matches on - fault and component names, metric keys, the worker
stage - are never translated in place: a Spanish `label` or `stageText` goes
beside them.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

LOCALE = "es"


@dataclass(frozen=True)
class Msg:
    code: str
    en: str
    es: str


@dataclass(frozen=True)
class Translated:
    code: str
    text: str
    params: dict = field(default_factory=dict)


# -- words: exact names ------------------------------------------------------
MOVEMENTS = {
    "Muscle-up": "Muscle-up", "Pull-up": "Dominada", "Dip": "Fondo", "Push-up": "Flexión",
    "Squat": "Sentadilla", "Hanging knee raise": "Elevación de rodillas colgado",
    "Front lever": "Front lever", "Planche": "Plancha", "Pistol squat": "Sentadilla pistol",
    "Split squat": "Sentadilla split", "Bulgarian split squat": "Sentadilla búlgara",
    "Not recognised": "No reconocido",
    # Names the classifier can say but the pipeline cannot measure.
    "deadlift": "Peso muerto", "bench_press": "Press de banca", "barbell_squat": "Sentadilla con barra",
    "handstand": "Pino", "human_flag": "Bandera humana", "back_lever": "Back lever",
    "monkey_bar_traversal": "Pasamanos", "monkey_bar_traverse": "Pasamanos",
    # Skill-catalog names the pipeline cannot measure yet (barra/skills.py):
    # the vision localizer still reports them, and the name reaches the phone.
    "leg_raise": "Elevación de piernas colgado", "toes_to_bar": "Puntas a la barra",
    "dragon_flag": "Dragon flag", "dragonflag": "Dragon flag", "dragon flag": "Dragon flag",
    "plank": "Plancha frontal", "hollow_hold": "Hollow hold",
    "l_sit": "L-sit", "v_sit": "V-sit", "manna": "Manna", "ab_wheel": "Rueda abdominal",
    "dead_hang": "Dead hang", "australian_row": "Remo australiano",
    "nordic_curl": "Curl nórdico", "sissy_squat": "Sentadilla sissy",
    "skin_the_cat": "Skin the cat", "hefesto": "Hefesto",
}

METRICS = {
    "Concentric duration": "Duración de la subida", "Eccentric duration": "Duración de la bajada",
    "Rep duration": "Duración de la rep", "Eccentric : concentric": "Bajada : subida",
    "Transition through the bar": "Transición por la barra", "Time held near lockout": "Tiempo arriba",
    "Range of motion": "Recorrido", "Lockout height above bar": "Altura sobre la barra",
    "Start position below bar": "Posición inicial bajo la barra",
    "Shoulder asymmetry (concentric)": "Asimetría de hombros (subida)",
    "Shoulder asymmetry at turnaround": "Asimetría de hombros en el giro",
    "Body swing relative to the bar": "Balanceo respecto a la barra",
}

# Movement keys (pull_up) -> the English label MOVEMENTS is keyed on.
HUMAN_KEYS = {"muscle_up": "Muscle-up", "pull_up": "Pull-up", "dip": "Dip", "push_up": "Push-up",
              "squat": "Squat", "knee_raise": "Hanging knee raise", "front_lever": "Front lever",
              "planche": "Planche", "pistol_squat": "Pistol squat", "split_squat": "Split squat",
              "bulgarian_split_squat": "Bulgarian split squat"}

COMPONENTS = {"range": "recorrido", "control": "control", "smoothness": "fluidez",
              "swing": "balanceo", "symmetry": "simetría"}

BANDS = {"strong": "fuerte", "solid": "sólida", "shaky": "irregular",
         "broken down": "se desmorona", "unmeasured": "sin medir"}

BODY = {"hands": "las manos", "feet": "los pies", "shoulders": "los hombros",
        "hips": "las caderas", "knees": "las rodillas"}

STAGES = {
    "receiving the clip": ("stage.receiving", "Recibiendo el vídeo"),
    "locating the exercise": ("stage.locating", "Buscando el ejercicio en el vídeo"),
    "opening the clip": ("stage.opening", "Abriendo el vídeo"),
    "estimating the pose": ("stage.pose", "Estimando la postura"),
    "recognising the movement": ("stage.recognising", "Reconociendo el movimiento"),
    "finding the reps": ("stage.finding", "Buscando las repeticiones"),
    "trying the relaxed pass": ("stage.relaxed", "Repasando con criterio más flexible"),
    "counting from the frames": ("stage.visual_count", "Contando a partir de fotogramas"),
    "scoring the reps": ("stage.scoring", "Puntuando las repeticiones"),
    "measuring the hold": ("stage.hold", "Midiendo el mantenimiento"),
}

# -- sentences ----------------------------------------------------------------
CATALOG: list[Msg] = [
    # segmentation (barra/ingest.py)
    Msg("segment.no_turnaround", "no turnaround stood out from the noise",
        "ningún cambio de dirección destacó sobre el ruido"),
    Msg("segment.span_cut_end", "candidate at {t}s runs past the end of the active span - the rest of the rep was cut off, so it is not scored",
        "el intento en {t} s sigue después del tramo que se pudo medir: le falta el final, así que no se puntúa"),
    Msg("segment.span_cut_start", "candidate at {t}s runs past the start of the active span - the rest of the rep was cut off, so it is not scored",
        "el intento en {t} s empieza antes del tramo que se pudo medir: le falta el principio, así que no se puntúa"),
    Msg("segment.too_brief", "candidate at {t}s was too brief to be a rep",
        "el intento en {t} s fue demasiado corto para ser una repetición"),
    Msg("segment.interpolated", "candidate at {t}s is mostly interpolated - only {p} of its frames were tracked",
        "el intento en {t} s está casi todo interpolado: solo se siguió el {p} de sus fotogramas"),
    Msg("segment.hands_moved", "candidate at {t}s: the hands travelled {d} torso-lengths, so they were not on a fixed bar - this is movement around the rig, not a rep",
        "intento en {t} s: las manos se desplazaron {d} torsos, así que no estaban en una barra fija; es movimiento por la estructura, no una repetición"),
    Msg("segment.not_from_hang", "candidate at {t}s rests with the shoulders {d} torso-lengths above the hands, so it did not start from a hang - not a rep of a hanging movement",
        "el intento en {t} s reposa con los hombros {d} torsos por encima de las manos, así que no empezó colgado: no es una repetición de un ejercicio en suspensión"),
    Msg("segment.not_from_support", "candidate at {t}s rests with the shoulders {d} torso-lengths below the hands, so it did not start from a support - not a rep of a pressing movement",
        "el intento en {t} s reposa con los hombros {d} torsos por debajo de las manos, así que no empezó en apoyo: no es una repetición de empuje"),
    Msg("segment.no_usable_pose", "no frame had a usable pose for this movement's landmarks",
        "ningún fotograma tenía una postura útil para los puntos que necesita este ejercicio"),
    Msg("segment.no_usable_pose_short", "no frame had a usable pose",
        "ningún fotograma tenía una postura útil"),
    Msg("segment.off_apparatus", "no stretch of this clip shows the athlete on the apparatus - the hands were never still on anything fixed",
        "en ningún tramo del vídeo se ve al atleta en el aparato: las manos nunca estuvieron quietas sobre algo fijo"),
    Msg("segment.off_apparatus_short", "no stretch of this clip shows the athlete on the apparatus",
        "en ningún tramo del vídeo se ve al atleta en el aparato"),
    Msg("segment.trimmed", "trimmed to the active spans", "recortado a los tramos con movimiento"),
    Msg("segment.never_moved", "the tracked signal never moved - no movement detected",
        "la señal seguida nunca se movió: no se detectó movimiento"),
    Msg("segment.never_moved_short", "the tracked signal never moved", "la señal seguida nunca se movió"),
    Msg("segment.turn_untracked", "turnaround at {t}s was never actually tracked - the subject left frame or the pose was lost at the top",
        "el giro en {t} s no llegó a seguirse: la persona salió del encuadre o se perdió la postura arriba"),
    Msg("segment.none_met", "candidates were found but none met the rep criteria",
        "se encontraron intentos, pero ninguno cumplió los criterios de repetición"),
    Msg("segment.relaxed_counted", "the relaxed pass validated by the movement's own gradients counted {n} rep(s) the standard pass missed",
        "la pasada flexible, validada con la propia dinámica del movimiento, contó {n} repetición(es) que la pasada normal no vio"),
    Msg("segment.relaxed_none", "even the gradient-validated relaxed pass found no rep",
        "ni siquiera la pasada flexible encontró una repetición"),
    Msg("segment.standard_then", "the standard pass found nothing ({why*}) — {then*}",
        "la pasada normal no encontró nada ({why*}); {then*}"),
    # the session row's note (server/process.py)
    Msg("session.need_three", "{found} segmented, {usable} usable — need {min} for a session median",
        "{found} detectadas, {usable} útiles: hacen falta {min} para la mediana de una sesión"),
    Msg("session.counts", "{found} segmented, {usable} usable", "{found} detectadas, {usable} útiles"),
    Msg("session.hold", "hold", "mantenimiento"),
    # pose / probe (server/process.py)
    Msg("probe.no_video", "No video arrived at the server.", "El vídeo no llegó al servidor."),
    Msg("probe.cannot_open", "Could not open the clip: {why*}", "No se pudo abrir el vídeo: {why*}"),
    Msg("probe.cannot_open_reason", "cannot open", "no se puede abrir"),
    Msg("pose.failed", "Pose estimation failed: {why*}", "Falló la estimación de la postura: {why*}"),
    Msg("rep.impossible_pose", "the pose estimate is not physically possible: {why*}",
        "la postura estimada no es físicamente posible: {why*}"),
    Msg("rep.under_tracked", "too little of the rep was tracked (quality {q} < {min})",
        "se siguió muy poco de la repetición (calidad {q} < {min})"),
    Msg("count.vision", "the geometry could not time the reps, so two vision models counted {n} from stills of the clip ({models*})",
        "la geometría no pudo cronometrar las repeticiones, así que dos modelos de visión contaron {n} a partir de fotogramas ({models*})"),
    # metrics plausibility (barra/metrics.py)
    Msg("rep.arm_too_short", "shoulders reach {a} torso from the hands but the arms are only {b} long - the wrist or shoulder track is wrong",
        "los hombros llegan a {a} torsos de las manos pero los brazos solo miden {b}: el seguimiento de muñeca u hombro es erróneo"),
    Msg("rep.starts_above_bar", "rep starts {d} torso ABOVE the bar, so the detected start is not a hang",
        "la repetición empieza {d} torsos POR ENCIMA de la barra, así que el inicio detectado no es colgado"),
    Msg("rep.starts_too_deep", "rep starts {d} torso below the bar, deeper than an arm length ({a})",
        "la repetición empieza {d} torsos bajo la barra, más que la longitud del brazo ({a})"),
    Msg("rep.rom_too_big", "range of motion {d} torso exceeds twice the arm reach",
        "el recorrido de {d} torsos supera el doble del alcance del brazo"),
    # score components (barra/quality.py)
    Msg("score.ruler_unusable", "the torso-length ruler is not usable on this clip (arm reads {a} torso), so range cannot be scored",
        "la medida del torso no sirve en este vídeo (el brazo mide {a} torsos), así que no se puede puntuar el recorrido"),
    Msg("assess.ruler_unusable", "the torso-length ruler is not usable on this clip, so a length in torso units cannot be judged",
        "la medida del torso no sirve en este vídeo, así que no se puede juzgar una longitud en torsos"),
    Msg("score.no_arm", "arm reach could not be measured", "no se pudo medir el alcance del brazo"),
    Msg("score.range", "hang {h} of full, lockout {l} of full",
        "colgado al {h} del total, bloqueo arriba al {l} del total"),
    Msg("score.no_descent", "no descent measured, so no control penalty applied",
        "no se midió la bajada, así que no se aplicó penalización de control"),
    Msg("score.controlled", "descent {r}x the ascent - controlled", "bajada {r}x la subida: controlada"),
    Msg("score.uncontrolled", "descent {r}x the ascent, under the {min}x that counts as controlled",
        "bajada {r}x la subida, por debajo del {min}x que cuenta como controlada"),
    Msg("score.ascent_short", "ascent too short to assess", "subida demasiado corta para valorarla"),
    Msg("score.no_progress", "the ascent made no net progress", "la subida no avanzó en neto"),
    Msg("score.stalled_share", "{p} of the ascent made no progress", "el {p} de la subida no avanzó"),
    Msg("score.no_rate", "the ascent never moved at a usable rate", "la subida nunca se movió a un ritmo útil"),
    Msg("score.even", "paced evenly through the ascent", "ritmo uniforme durante la subida"),
    Msg("score.rate", "the ascent ran at {p} of its own best rate", "la subida fue al {p} de su mejor ritmo"),
    Msg("score.not_impossible", "not scored: the pose estimate is not physically possible",
        "sin puntuar: la postura estimada no es físicamente posible"),
    Msg("score.not_tracked", "not scored: too little of the rep was tracked",
        "sin puntuar: se siguió muy poco de la repetición"),
    Msg("score.not_components", "not scored: no component could be measured",
        "sin puntuar: no se pudo medir ningún componente"),
    Msg("score.no_components_note", "None of the components could be measured.",
        "No se pudo medir ninguno de los componentes de la nota."),
    Msg("score.not_range", "not scored: range could not be measured", "sin puntuar: no se pudo medir el recorrido"),
    Msg("score.swing_aside", "body travel relative to the bar - needs a consistent camera side, so it is not part of the score",
        "desplazamiento del cuerpo respecto a la barra: necesita grabar siempre desde el mismo lado, así que no cuenta en la puntuación"),
    Msg("score.symmetry_aside", "left/right shoulder difference - needs a consistent camera side, so it is not part of the score",
        "diferencia entre hombro izquierdo y derecho: necesita grabar siempre desde el mismo lado, así que no cuenta en la puntuación"),
    Msg("score.swing_short", "body travel relative to the bar", "desplazamiento del cuerpo respecto a la barra"),
    Msg("score.weighted", "weighted mean of the measured components, less any fault penalty",
        "media ponderada de los componentes medidos, menos las penalizaciones"),
    Msg("note.no_range", "Range of motion could not be measured on this clip, and a quality score without it would say nothing about how much of the movement happened. Film from the side so the torso is not foreshortened.",
        "No se pudo medir el recorrido en este vídeo, y una puntuación sin él no diría cuánto movimiento hubo. Graba de lado para que el torso no salga escorzado."),
    Msg("note.impossible", "This rep could not be measured - the pose estimate is not physically possible.",
        "Esta repetición no se pudo medir: la postura estimada no es físicamente posible."),
    # movement recognition (barra/classify.py)
    Msg("classify.part_unseen", "the {part*} were never seen clearly enough for long enough",
        "{part*} nunca se vieron con claridad el tiempo suficiente"),
    Msg("classify.part_partial", "the {part*} were only tracked in {p} of the clip - they are out of frame for most of it",
        "{part*} solo se siguieron en el {p} del vídeo: están fuera de encuadre casi todo el tiempo"),
    Msg("classify.part_moved", "the {part*} moved {d} torso-lengths, past {max}",
        "{part*} se movieron {d} torsos, más de {max}"),
    Msg("classify.front_lever", "hanging from a fixed bar with the body held {deg} degrees from vertical - a front lever",
        "colgado de una barra fija con el cuerpo a {deg} grados de la vertical: un front lever"),
    Msg("classify.front_lever_short", "hanging from a fixed bar, body held horizontal",
        "colgado de una barra fija con el cuerpo horizontal"),
    Msg("classify.planche", "body held {deg} degrees from vertical on the hands with the legs carried up off the ground - a planche",
        "cuerpo a {deg} grados de la vertical sobre las manos y con las piernas en el aire: una plancha"),
    Msg("classify.planche_short", "body horizontal on straight arms, legs off the ground",
        "cuerpo horizontal sobre brazos rectos, piernas en el aire"),
    Msg("classify.parked_short", "the body stays parked - a hold or a rest, not a set",
        "el cuerpo se queda quieto: un mantenimiento o un descanso, no una serie"),
    Msg("classify.parked", "hanging from something fixed, but {p} of the clip is spent within a fifth of a torso-length of one position - a hold, or resting between attempts, rather than a set of repetitions",
        "colgado de algo fijo, pero el {p} del vídeo pasa casi en la misma posición: un mantenimiento o un descanso entre intentos, más que una serie de repeticiones"),
    Msg("classify.knee_raise_short", "the knees are carried above the hips, and travel further than the shoulders do",
        "las rodillas suben por encima de las caderas y se mueven más que los hombros"),
    Msg("classify.knee_raise", "hanging from a fixed bar with the knees carried {d} torso-lengths above the hips and travelling further than the shoulders - the legs are doing the work",
        "colgado de una barra fija con las rodillas {d} torsos por encima de las caderas y moviéndose más que los hombros: el trabajo lo hacen las piernas"),
    Msg("classify.mu_short", "the shoulders finish above the hands", "los hombros terminan por encima de las manos"),
    Msg("classify.muscle_up", "hanging from a fixed bar, and the shoulders finish {d} torso-lengths above the hands",
        "colgado de una barra fija, y los hombros terminan {d} torsos por encima de las manos"),
    Msg("classify.pu_short", "the shoulders never rise above the hands", "los hombros nunca suben por encima de las manos"),
    Msg("classify.pull_up", "hanging from a fixed bar, and the shoulders never rise above the hands (peak {d} torso-lengths)",
        "colgado de una barra fija, y los hombros nunca suben por encima de las manos (máximo {d} torsos)"),
    Msg("classify.pistol_short", "one foot planted, the other carried forward", "un pie apoyado y el otro adelantado"),
    Msg("classify.pistol", "one foot stayed planted and the other leg was carried forward while the hips moved through {d} torso-lengths - a single-leg squat",
        "un pie se quedó apoyado y la otra pierna adelantada mientras la cadera recorría {d} torsos: una sentadilla a una pierna"),
    Msg("classify.bulgarian_short", "front foot planted, rear foot up on a bench", "pie delantero apoyado, trasero sobre un banco"),
    Msg("classify.bulgarian", "feet in a split stance with the rear ankle {d} torso-lengths above the front - a Bulgarian split squat",
        "pies en zancada con el tobillo trasero {d} torsos por encima del delantero: una sentadilla búlgara"),
    Msg("classify.split_short", "front foot planted, rear foot behind, on the floor", "pie delantero apoyado, trasero detrás en el suelo"),
    Msg("classify.split", "feet planted in a split stance with the ankles {d} torso-lengths apart in height, and the rear ankle on the floor - a split squat",
        "pies en zancada con los tobillos a {d} torsos de altura de diferencia y el trasero en el suelo: una sentadilla split"),
    Msg("classify.squat_short", "feet planted, hips travelling, arms rigid to the torso",
        "pies apoyados, cadera en movimiento, brazos fijos al torso"),
    Msg("classify.squat", "feet stayed put, the hips moved through {d} torso-lengths, and the arms did not move relative to the torso",
        "los pies no se movieron, la cadera recorrió {d} torsos y los brazos no se movieron respecto al torso"),
    Msg("classify.too_little_short", "too little of the body was seen to tell them apart",
        "se vio muy poco del cuerpo para distinguirlos"),
    Msg("classify.dip_or_push", "hands fixed below the shoulders, but too little of the body was seen to tell a dip from a push-up",
        "manos fijas bajo los hombros, pero se vio muy poco del cuerpo para distinguir un fondo de una flexión"),
    Msg("classify.feet_unseen_short", "hands fixed, body below them, but the feet were never seen",
        "manos fijas y cuerpo por debajo, pero nunca se vieron los pies"),
    Msg("classify.feet_unseen", "hands fixed below the shoulders with {p} of the body below them, but the feet were never clearly seen - this is a dip (feet hanging) or a squat with the feet out of frame, and a dip is not justified",
        "manos fijas bajo los hombros con el {p} del cuerpo por debajo, pero los pies nunca se vieron bien: puede ser un fondo (pies colgando) o una sentadilla con los pies fuera de encuadre, y no hay base para decir fondo"),
    Msg("classify.dip_short", "the legs hang below the hands", "las piernas cuelgan por debajo de las manos"),
    Msg("classify.dip", "hands fixed below the shoulders, with {p} of the body hanging below them - the legs are off the ground",
        "manos fijas bajo los hombros, con el {p} del cuerpo colgando por debajo: las piernas no tocan el suelo"),
    Msg("classify.push_short", "nothing hangs below the hands, so they are on the floor",
        "nada cuelga por debajo de las manos, así que están en el suelo"),
    Msg("classify.push_up", "hands fixed below the shoulders and nothing hanging below them, so the hands are on the floor rather than on bars",
        "manos fijas bajo los hombros y nada colgando por debajo, así que las manos están en el suelo y no en barras"),
    Msg("classify.nothing_fixed", "no {s}-second stretch of this clip shows hands on something fixed or feet planted ({a*}, and {b*}), so it does not show a movement barra can measure",
        "ningún tramo de {s} segundos del vídeo muestra las manos sobre algo fijo ni los pies apoyados ({a*}, y {b*}), así que no se ve un ejercicio que barra pueda medir"),
    Msg("classify.no_match", "the clip does not match any movement barra knows: the hands are {state*} and the shoulders move {d} torso-lengths relative to them",
        "el vídeo no encaja con ningún ejercicio que barra conozca: las manos están {state*} y los hombros se mueven {d} torsos respecto a ellas"),
    # fusion (barra/fusion.py)
    Msg("fusion.vision", "the vision read of the frames is the most reliable single detector and the others did not agree",
        "la lectura por visión de los fotogramas es el detector más fiable y los demás no coincidían"),
    Msg("fusion.model", "the learned classifier decided; it is measured well above the geometric detector on this corpus",
        "decidió el clasificador aprendido, que en nuestras pruebas acierta bastante más que el detector geométrico"),
    Msg("fusion.geometry", "geometry decided the movement; no other detector offered a usable label",
        "decidió la geometría; ningún otro detector dio una etiqueta útil"),
    Msg("fusion.none", "no detector had enough support to name the movement",
        "ningún detector tenía apoyo suficiente para nombrar el ejercicio"),
    # movement tree (barra/movement_tree.py)
    Msg("tree.no_answer", "the footage does not answer this question", "el vídeo no responde a esta pregunta"),
    Msg("tree.too_deep", "the tree did not reach a movement within {n} questions",
        "el árbol no llegó a un ejercicio en {n} preguntas"),
    # jobs (server/api/handler.py, sweeper.py)
    Msg("job.upload_stuck", "the clip was never finished uploading. Retry. (stuck for {m} min)",
        "la subida del vídeo no llegó a terminar. Vuelve a intentarlo. (atascado {m} min)"),
    Msg("job.upload_stuck2", "the clip was never finished uploading (stuck for {m} min). Retry.",
        "la subida del vídeo no llegó a terminar (atascado {m} min). Vuelve a intentarlo."),
    Msg("job.worker_stuck", "the worker never picked this up. Retry. (stuck for {m} min)",
        "el análisis no llegó a empezar. Vuelve a intentarlo. (atascado {m} min)"),
    Msg("job.worker_stuck2", "the worker never picked this up (stuck for {m} min). Retry.",
        "el análisis no llegó a empezar (atascado {m} min). Vuelve a intentarlo."),
    Msg("job.worker_died", "the worker died while measuring this (stuck for {m} min). Retry.",
        "el análisis se interrumpió mientras medía (atascado {m} min). Vuelve a intentarlo."),
    Msg("job.never_terminal", "this job never reached a terminal state (stuck for {m} min). Retry.",
        "este análisis nunca terminó (atascado {m} min). Vuelve a intentarlo."),
    Msg("job.no_clip", "the clip never arrived in storage", "el vídeo nunca llegó al almacenamiento"),
    # unmeasurable movement (process.py; replaces the raw SystemExit text)
    Msg("movement.unsupported", "movement_unsupported:{name*}",
        "hemos detectado {name*}, que todavía no medimos. Graba dominadas, muscle-ups, fondos, flexiones o sentadillas"),
    # pose frame budget (barra/pose/budget.py): refused before any pose runs
    Msg("video.too_long", "video_too_long:{max_s}",
        "El vídeo es demasiado largo para analizarlo entero. Recórtalo a la serie "
        "(unos {max_s} segundos como mucho) y vuelve a subirlo."),
    # detectors disagree and no vision read broke the tie (fusion abstention)
    Msg("movement.unconfirmed", "movement_unconfirmed",
        "No hemos podido confirmar qué ejercicio es, así que no lo hemos puntuado. "
        "Vuelve a grabarlo de lado, con todo el cuerpo dentro del plano."),
]

# -- the English detector used by the sentinel ---------------------------------
# Words that are English and not Spanish. Short and unambiguous on purpose:
# "clip", "pose", "torso", "control", "rep" are used in Spanish too.
_ENGLISH = {
    "the", "and", "of", "was", "were", "is", "are", "not", "never", "with", "from",
    "this", "that", "could", "would", "which", "than", "rather", "only", "into", "been",
    "has", "have", "its", "it", "be", "to", "at", "on", "by", "or", "so", "but", "none",
    "nothing", "countable", "verified", "measured", "tracked", "shoulders", "hands",
    "feet", "knees", "hips", "turnaround", "noise", "ascent", "descent", "controlled",
    "hanging", "candidate", "stretch", "reps", "solid", "shaky", "strong", "film",
    "five", "six", "tripod", "same", "side", "lockout", "trimmed", "working",
    "set", "recognised", "movement", "frame", "frames", "stuck", "retry", "worker",
    "uploading", "finished", "rep(s)", "duration", "range", "motion", "swing",
}
_WORD = re.compile(r"[A-Za-z]+(?:\(s\))?")


def english_words(text: str | None) -> list[str]:
    """The English giveaway words in `text` - empty for Spanish."""
    if not text:
        return []
    return [w for w in _WORD.findall(text) if w.lower() in _ENGLISH]


_KNOWN_SPANISH = set(MOVEMENTS.values()) | set(METRICS.values()) | set(COMPONENTS.values())
_SPANISH = {"el", "la", "los", "las", "de", "del", "que", "en", "y", "se", "un", "una",
            "por", "con", "para", "es", "sin", "al", "lo", "su", "más", "muy", "ya",
            # Determiners and negations that headlines lean on: "19 flexiones:
            # ninguna verificada" has no accent and none of the words above.
            "ninguna", "ninguno", "ningún", "no", "ni", "cada", "todas", "todos"}


def looks_spanish(text: str) -> bool:
    """Spanish enough to leave alone: an accent, or a Spanish function word,
    and no English giveaway."""
    if english_words(text):
        return False
    if text in _KNOWN_SPANISH:
        return True
    words = [w.lower() for w in re.findall(r"\w+", text)]
    if len(words) < 4:
        return True  # too short to tell, and no English giveaway
    return bool(re.search(r"[áéíóúñ¿¡]", text, re.I)) or bool(set(words) & _SPANISH)


# -- matching -----------------------------------------------------------------
_HOLE = re.compile(r"\{(\w+)(\*?)\}")
_NUM = r"-?\d+(?:\.\d+)?%?"


def _compile(en: str) -> re.Pattern:
    out, pos = [], 0
    for m in _HOLE.finditer(en):
        out.append(re.escape(en[pos:m.start()]))
        out.append(f"(?P<{m.group(1)}>.+?)" if m.group(2) else f"(?P<{m.group(1)}>{_NUM})")
        pos = m.end()
    out.append(re.escape(en[pos:]))
    return re.compile("".join(out), re.S)


_COMPILED = [(m, _compile(m.en)) for m in CATALOG]


def _number(raw: str) -> str:
    pct = raw.endswith("%")
    core = raw[:-1] if pct else raw
    core = core.replace(".", ",")
    return f"{core} %" if pct else core


def _fragment(text: str, missing: list[str]) -> str:
    stripped = text.strip()
    if stripped in BODY:
        return BODY[stripped]
    if stripped in MOVEMENTS:
        name = MOVEMENTS[stripped]
        return name if name[:1].isupper() and name.split()[0] in ("Muscle-up", "Front", "Back") else name.lower()
    if stripped in HUMAN_KEYS:
        return _fragment(HUMAN_KEYS[stripped], missing)
    t = translate(stripped, missing)
    if t is None:
        missing.append(stripped)
        return stripped
    return t.text


def translate(text: str, missing: list[str] | None = None) -> Translated | None:
    """The catalog's translation of one message, or None when no template
    matches. A trailing full stop and the first letter's case are kept."""
    if not text or not text.strip():
        return None
    missing = [] if missing is None else missing
    body = text.strip()
    candidates = [body]
    if body.endswith("."):
        candidates.append(body[:-1])
    for cand in candidates:
        for msg, rx in _COMPILED:
            m = rx.fullmatch(cand)
            if not m:
                continue
            params = m.groupdict()
            out = msg.es
            for name, star in _HOLE.findall(msg.es):
                val = params[name]
                rendered = _fragment(val, missing) if star else _number(val)
                out = out.replace("{" + name + star + "}", rendered, 1)
            if cand is not body:  # the stop was stripped to match
                out += "."
            if body[:1].isupper() and out[:1].islower():
                out = out[:1].upper() + out[1:]
            elif body[:1].islower() and out[:1].isupper() and msg.es[:1].islower():
                out = out[:1].lower() + out[1:]
            return Translated(msg.code, out, params)
    return None


def localize_text(text, missing: list[str] | None = None):
    """`text` in Spanish when the catalog knows it, else unchanged (and noted
    in `missing`). Non-strings pass through."""
    if not isinstance(text, str) or not text.strip():
        return text
    missing = [] if missing is None else missing
    if text in MOVEMENTS:
        return MOVEMENTS[text]
    normalized = MOVEMENTS.get(_normalize_label(text))
    if normalized is not None:
        return normalized
    if text in METRICS:
        return METRICS[text]
    sub: list[str] = []
    t = translate(text, sub)
    if t is None:
        if not looks_spanish(text):
            missing.append(text)
        return text
    missing.extend(sub)
    return t.text



_LABEL_NONWORD = re.compile(r"[\s_-]+")


def _normalize_label(text: str) -> str:
    """An exercise label in the catalog's exact casing: "dragon-flag" and
    "DRAGON FLAG" find "Dragon flag"; unknown text comes back as it came."""
    return _LABEL_NONWORD.sub(" ", text.strip().strip(".")).lower()

_VALUE = re.compile(r"^(-?\d+(?:\.\d+)?)\s*(s|x|torso|deg|%)?$")
_UNITS = {"torso": "torsos", "s": "s", "x": "x", "deg": "°", "%": "%"}


def localize_value(value):
    """A metric value: "0.33 s" -> "0,33 s", "1.2 torso" -> "1,2 torsos"."""
    if not isinstance(value, str):
        return value
    m = _VALUE.match(value.strip())
    if not m:
        return value
    num = m.group(1).replace(".", ",")
    unit = _UNITS.get(m.group(2) or "", m.group(2) or "")
    return f"{num} {unit}".strip()


def stage(name: str) -> tuple[str, str]:
    """(stable code, Spanish text) for a worker stage phrase."""
    if name in STAGES:
        return STAGES[name]
    t = translate(name)
    return (t.code if t else "stage.other", t.text if t else name)


def band(name: str | None) -> str | None:
    return BANDS.get(name or "", name)


# -- the payload ----------------------------------------------------------------
def _capital(s):
    return s[:1].upper() + s[1:] if isinstance(s, str) and s else s


def localize_payload(payload: dict) -> dict:
    """A copy of `payload` with every visible text in Spanish, keys untouched,
    and `i18n = {"locale": "es", "untranslated": [...]}`. Idempotent."""
    p = copy.deepcopy(payload)
    missing: list[str] = []
    L = lambda s: localize_text(s, missing)  # noqa: E731

    for k in ("headline", "narrative", "nextSession"):
        if k in p:
            p[k] = L(p[k])
    # Translated reasons read as list items, so they start with a capital;
    # an unknown one is left exactly as it came.
    p["blockers"] = [(_capital(t) if t != b else b)
                     for b in p.get("blockers") or [] for t in [L(b)]]
    d = p.get("detected")
    if isinstance(d, dict):
        for k in ("label", "reason"):
            if k in d:
                d[k] = L(d[k])
    for s in p.get("sessions") or []:
        if isinstance(s, dict) and "note" in s:
            s["note"] = L(s["note"])
    for r in p.get("reps") or []:
        r["problems"] = [L(x) for x in r.get("problems") or []]
        if "scoreNote" in r:
            r["scoreNote"] = L(r["scoreNote"])
        for k in ("transition_s", "total_s"):
            if k in r:
                r[k] = localize_value(r[k])
        for m in r.get("metrics") or []:
            if "name" in m:
                m["name"] = L(m["name"])
            if "value" in m:
                m["value"] = localize_value(m["value"])
        for group in ("components", "aside", "penalties"):
            for c in r.get(group) or []:
                if c.get("name") in COMPONENTS:
                    c["label"] = COMPONENTS[c["name"]]
                if "why" in c:
                    c["why"] = L(c["why"])
    p["i18n"] = {"locale": LOCALE, "untranslated": list(dict.fromkeys(missing))}
    return p
