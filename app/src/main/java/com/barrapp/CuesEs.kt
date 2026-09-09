package com.barrapp

import com.barrapp.data.Analysis
import com.barrapp.data.RepRow

/**
 * The coaching layer in the app's own language.
 *
 * Same contract as [Cues]: nothing here invents a fault. Every entry is keyed
 * on a fault name the server measured and shipped, so a cue can only ever
 * appear because a measurement fired. The English side stays where it is —
 * the legacy screens still read it — and this file is the Spanish face the
 * redesigned screens wear.
 *
 * A fault with no entry here renders under its measured name rather than
 * disappearing: an untranslated fault is a translation bug, not a reason to
 * hide evidence.
 */

/** The fault, named the way the screens say it. */
fun faultEs(key: String): String = FAULTS_ES[key] ?: key.replaceFirstChar { it.uppercase() }

/** The single line that goes over the video. */
fun cueEs(key: String): String? = CUES_ES[key]

/** The corrective the coach screen offers for a fault. */
fun drillEs(key: String): Drill? = DRILLS_ES[key]

data class Drill(
    val title: String,
    val sets: String,
    val focus: String,
    val duration: String,
)

private val FAULTS_ES = mapOf(
    "poor range of motion" to "Recorrido incompleto",
    "lockout" to "Sin bloqueo arriba",
    "dead hang" to "Sin dead hang",
    "too deep" to "Demasiado profundo",
    "no active hang" to "Sin colgado activo",
    "momentum" to "Balanceo",
    "sagging hips" to "Cadera hundida",
    "piked hips" to "Cuerpo en pica",
    "piked body" to "Cuerpo en pica",
    "bent arms" to "Brazos doblados",
    "bent knees" to "Rodillas dobladas",
    "knee valgus" to "Rodillas hacia dentro",
    "heel raise" to "Talones levantados",
    "leaning back" to "Espalda echada atrás",
    "arm swing" to "Brazos sueltos",
    "poor scapular retraction" to "Escápulas sin retraer",
    "poor scapular protraction" to "Escápulas sin proyectar",
    "control" to "Descenso sin control",
    "uncontrolled descent" to "Caída sin control",
    "too fast" to "Reps lanzadas",
    "bounce at bottom" to "Rebote abajo",
    "stall" to "Estancamiento a medio tirón",
    "poor transition" to "Transición lenta",
)

private val CUES_ES = mapOf(
    "momentum" to "Corta el balanceo — tira estricto, sin impulso.",
    "lockout" to "Bloquea del todo arriba en cada repetición.",
    "dead hang" to "Empieza cada rep desde un dead hang completo.",
    "control" to "Baja controlando — no te sueltes desde arriba.",
    "stall" to "Atraviesa el punto de estancamiento en un solo arco.",
    "poor transition" to "Pasa la transición en un único movimiento.",
    "bent arms" to "Estira los brazos del todo arriba.",
    "no active hang" to "Estira los brazos entre reps — cuelga y luego tira.",
    "too fast" to "Baja el ritmo — estas reps van lanzadas.",
    "too deep" to "Párate en noventa grados — más abajo es hombro, no pecho.",
    "bounce at bottom" to "Haz una pausa abajo en vez de rebotar.",
    "poor range of motion" to "Lleva cada rep por su recorrido completo.",
    "sagging hips" to "Mantén la cadera en línea — aprieta los glúteos.",
    "uncontrolled descent" to "Baja controlando — no te dejes caer.",
    "knee valgus" to "Lleva las rodillas hacia fuera, sobre las puntas.",
    "heel raise" to "Mantén los talones en el suelo toda la repetición.",
    "leaning back" to "Pecho arriba — deja de echarte hacia atrás.",
    "arm swing" to "Brazos quietos — no busques el equilibrio con ellos.",
    "piked hips" to "Cuerpo plano — sin pica en la cadera.",
    "piked body" to "Cuerpo plano — sin pica en la cadera.",
    "bent knees" to "Piernas estiradas durante todo el hold.",
    "poor scapular retraction" to "Fija los hombros abajo y atrás antes de tirar.",
    "poor scapular protraction" to "Empuja los hombros hacia fuera al bloquear.",
)

private val DRILLS_ES = mapOf(
    "momentum" to Drill("Dead hang estático", "3×30 s",
        "Core anti-balanceo y fuerza de agarre", "3 min"),
    "poor range of motion" to Drill("Dominada con goma", "3×5",
        "Recorrido completo con resistencia reducida", "6 min"),
    "lockout" to Drill("Isométrico arriba", "4×10 s",
        "Aguantar con la barbilla por encima de la barra", "4 min"),
    "dead hang" to Drill("Colgado pasivo", "3×20 s",
        "Aprender dónde empieza la repetición", "3 min"),
    "no active hang" to Drill("Scapular pull-up", "3×8",
        "Activar el dorsal sin doblar el codo", "4 min"),
    "control" to Drill("Negativas lentas", "3×4",
        "Bajar en cinco segundos, sin soltarse", "5 min"),
    "uncontrolled descent" to Drill("Negativas lentas", "3×4",
        "Bajar en cinco segundos, sin soltarse", "5 min"),
    "too fast" to Drill("Tempo 3-1-3", "3×5",
        "Marcar el ritmo con la respiración", "5 min"),
    "stall" to Drill("Isométrico en el punto muerto", "4×8 s",
        "Fuerza justo donde se para la barra", "4 min"),
    "poor transition" to Drill("Transición asistida", "3×3",
        "Pasar de tirón a fondo sin pausa", "6 min"),
    "bent arms" to Drill("Bloqueo con apoyo", "3×15 s",
        "Brazos rectos bajo carga", "3 min"),
    "sagging hips" to Drill("Hollow body hold", "3×20 s",
        "Línea del cuerpo bajo tensión", "3 min"),
    "piked hips" to Drill("Hollow body hold", "3×20 s",
        "Línea del cuerpo bajo tensión", "3 min"),
    "piked body" to Drill("Hollow body hold", "3×20 s",
        "Línea del cuerpo bajo tensión", "3 min"),
    "bent knees" to Drill("L-sit en paralelas", "3×15 s",
        "Piernas rectas con el cuádriceps activo", "4 min"),
    "knee valgus" to Drill("Sentadilla con goma", "3×10",
        "Rodillas empujando contra la goma", "5 min"),
    "heel raise" to Drill("Sentadilla con talones fijos", "3×8",
        "Peso en el medio del pie", "4 min"),
    "leaning back" to Drill("Sentadilla goblet", "3×8",
        "Pecho arriba con carga delante", "5 min"),
    "arm swing" to Drill("Series con brazos cruzados", "3×6",
        "Quitar el brazo de la ecuación", "4 min"),
    "poor scapular retraction" to Drill("Scapular pull-up", "3×8",
        "Bajar los hombros antes de tirar", "4 min"),
    "poor scapular protraction" to Drill("Push-up plus", "3×10",
        "Empujar el suelo al final de la rep", "4 min"),
    "too deep" to Drill("Fondo a paralela", "3×6",
        "Parar a noventa grados", "4 min"),
    "bounce at bottom" to Drill("Pausa abajo", "3×5",
        "Dos segundos parado antes de subir", "4 min"),
)

/** Movement names. Falls back to the server's own label, tidied. */
fun movementEs(exercise: String, label: String = ""): String {
    MOVEMENTS_ES[exercise.lowercase()]?.let { return it }
    val fallback = label.ifBlank { exercise }
    return fallback.replace('_', ' ').replaceFirstChar { it.uppercase() }
}

private val MOVEMENTS_ES = mapOf(
    "pull_up" to "Dominada",
    "chin_up" to "Dominada supina",
    "push_up" to "Flexión",
    "diamond_push_up" to "Flexión diamante",
    "dip" to "Fondo",
    "muscle_up" to "Muscle-up",
    "weighted_muscle_up" to "Muscle-up lastrado",
    "weighted_pull_up" to "Dominada lastrada",
    "squat" to "Sentadilla",
    "pistol_squat" to "Pistol squat",
    "knee_raise" to "Elevación de rodillas",
    "toes_to_bar" to "Toes to bar",
    "l_sit" to "L-Sit",
    "handstand" to "Pino",
    "row" to "Remo",
    "plank" to "Plancha",
)

/** The phase a check belongs to, in the app's language. */
fun phaseEs(phase: String): String = when (phase.lowercase().replace('_', ' ')) {
    "concentric", "pull", "ascent" -> "Tirón / fase concéntrica"
    "eccentric", "descent" -> "Fase excéntrica"
    "top", "lockout" -> "Bloqueo superior"
    "bottom" -> "Posición baja"
    "transition" -> "Transición"
    "hold" -> "Sostén"
    "whole rep", "rep", "" -> "Toda la repetición"
    else -> phase.replace('_', ' ').replaceFirstChar { it.uppercase() }
}

/**
 * The faults this set was measured to have, most reps first.
 *
 * Reuses [repFaults] so the Spanish screens and the English ones count the
 * same evidence — one derivation, two languages.
 */
fun faultCounts(analysis: Analysis): List<Pair<String, Int>> {
    val counts = mutableMapOf<String, Int>()
    analysis.reps.forEach { rep -> repFaults(rep).forEach { counts.merge(it, 1, Int::plus) } }
    return counts.entries.sortedByDescending { it.value }.map { it.key to it.value }
}

/** The faults of one rep, in the app's language. */
fun repFaultsEs(rep: RepRow): List<String> = repFaults(rep).map { faultEs(it) }
