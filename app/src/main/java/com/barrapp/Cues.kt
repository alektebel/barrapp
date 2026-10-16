package com.barrapp

import com.barrapp.data.Analysis
import com.barrapp.data.RepRow

/**
 * The coaching layer, kept deliberately small.
 *
 * Everything here is a restatement of a fault the server already measured, so
 * a cue can only appear when the measurement says it should. No cue is
 * invented from a score alone, and no more than three are ever offered: three
 * things is what carries into the next set.
 *
 * This file used to DERIVE the faults itself: regular expressions over the
 * range component's why-string ("lockout 76% of full"), compared against its
 * own copies of 0.85, 0.75 and 0.4. Both halves of that were wrong. Rewording
 * one sentence on the server switched fault detection off on every phone in
 * the field, silently, with no test that could see it; and the thresholds
 * existed in three places - here, barra/faults.py, barra/faults_taxonomy.py -
 * that nothing kept equal.
 *
 * The server ships each fired fault by name with the value and threshold that
 * fired it. This file renders names. It holds no thresholds and parses no
 * prose, and tests/test_cues_parity.py fails the build if either comes back.
 */

/** The faults one rep was actually measured to have, most important first. */
internal fun repFaults(rep: RepRow): List<String> {
    if (rep.faults.isNotEmpty()) {
        return rep.faults.map { canonicalFault(it.name) }.distinct().sortedBy { orderOf(it) }
    }
    return legacyFaults(rep)
}

/**
 * Reps stored before the server shipped `faults`.
 *
 * Deliberately narrow: it reads the two signals that are structured numbers
 * already - the swing aside and the control penalty - and no others. The
 * regex-over-prose derivation is gone rather than preserved, because a history
 * row showing fewer cues is a smaller lie than one showing cues that depend on
 * a sentence nobody may edit. Delete this once stored history has rolled over.
 */
private fun legacyFaults(rep: RepRow): List<String> {
    val faults = mutableListOf<String>()
    rep.asides.firstOrNull { it.name == "swing" }?.let {
        if (it.value > LEGACY_SWING_TORSO) faults += "momentum"
    }
    rep.penalties.firstOrNull { it.name == "control" }?.let {
        if ((it.value ?: 0.0) > 0.0) faults += "fast descent"
    }
    return faults
}

/**
 * Fault names the server used to send, read from sessions stored on the phone.
 * The server renamed them (the tempo rules fire "fast descent"; the lever bent
 * elbows fire "bent arms"); an old payload still renders, under the new name.
 * Kept apart from the tables below, which hold only names the server emits.
 */
private val LEGACY_FAULTS = mapOf(
    "control" to "fast descent",
    "uncontrolled descent" to "fast descent",
    "poor scapular retraction" to "bent arms",
    "poor scapular protraction" to "bent arms",
)

/** A stored fault name, as the server names it today. */
internal fun canonicalFault(name: String): String = LEGACY_FAULTS[name] ?: name

/** The one threshold left on the phone, and only for rows measured before the
 *  server named its own faults. Not consulted for anything current. */
private const val LEGACY_SWING_TORSO = 0.4

/** The one fault that leads the rep's score, or null when it measured clean.
 *  These are the words that go over the video. */
fun repFault(rep: RepRow): String? = when (repFaults(rep).firstOrNull()) {
    "momentum" -> "Balanceo"
    "lockout" -> "Sin bloqueo arriba"
    "dead hang" -> "Sin dead hang"
    "fast descent" -> "Bajada rápida"
    "stall" -> "Estancamiento a medio tirón"
    "poor transition" -> "Transición lenta"
    "bent arms" -> "Brazos doblados"
    "no active hang" -> "Sin colgado activo"
    "too fast" -> "Reps lanzadas"
    "too deep" -> "Demasiado profundo"
    "bounce at bottom" -> "Rebote abajo"
    "poor range of motion" -> "Recorrido incompleto"
    "sagging hips" -> "Cadera hundida"
    "knee valgus" -> "Rodillas hacia dentro"
    "heel raise" -> "Talones levantados"
    "leaning back" -> "Espalda echada atrás"
    "arm swing" -> "Brazos sueltos"
    "piked hips", "piked body" -> "Cuerpo en pica"
    "bent knees" -> "Rodillas dobladas"
    else -> null
}

/** What to work on, at most three of them, ordered by how many reps showed
 *  the fault. An empty list means the set measured clean. */
fun improvementCues(analysis: Analysis): List<String> {
    val counts = mutableMapOf<String, Int>()
    analysis.reps.forEach { rep ->
        repFaults(rep).forEach { counts.merge(it, 1, Int::plus) }
    }
    // A fault whose verdict depends on a standard nobody declared is still
    // shown - it was measured - but the cue says so, instead of telling a
    // kipping set to stop swinging as if strict had been the plan.
    val variantDependent = analysis.reps
        .flatMap { it.assessments }
        .filter { it.observed && it.variantDependent }
        .map { it.name }
        .toSet()
    return counts.entries
        .sortedWith(compareByDescending<Map.Entry<String, Int>> { it.value }
            .thenBy { orderOf(it.key) })
        .mapNotNull { e ->
            CUES[e.key]?.let { cue ->
                if (e.key in variantDependent) "$cue — juzgado como estricto; declara kipping si ese era el plan"
                else cue
            }
        }
        .take(3)
}

/**
 * The order faults are offered in when several fired on the same rep.
 *
 * Range of motion first: a rep that did not happen through its full travel is
 * not a rep with a tempo problem, it is a shorter rep. Then the things that
 * change how the load is carried, then the things that change how it looked.
 */
private val CUE_ORDER = listOf(
    "poor range of motion", "lockout", "dead hang", "too deep", "no active hang",
    "momentum", "sagging hips", "piked hips", "piked body", "bent arms",
    "bent knees", "knee valgus", "heel raise", "leaning back", "arm swing",
    "fast descent", "too fast", "bounce at bottom",
    "stall", "poor transition",
)

private fun orderOf(name: String): Int =
    CUE_ORDER.indexOf(name).let { if (it < 0) CUE_ORDER.size else it }

private val CUES = mapOf(
    "momentum" to "Corta el balanceo — tira estricto, sin impulso.",
    "lockout" to "Bloquea del todo arriba en cada repetición.",
    "dead hang" to "Empieza cada rep desde un dead hang completo.",
    "fast descent" to "Baja más despacio: la bajada es corta comparada con la subida.",
    "stall" to "Atraviesa el punto de estancamiento en un solo arco.",
    "poor transition" to "Pasa la transición en un único movimiento.",
    "bent arms" to "Estira los brazos del todo arriba.",
    "no active hang" to "Estira los brazos entre reps — cuelga y luego tira.",
    "too fast" to "Baja el ritmo — estas reps van lanzadas.",
    "too deep" to "Párate en noventa grados — más abajo es hombro, no pecho.",
    "bounce at bottom" to "Haz una pausa abajo en vez de rebotar.",
    "poor range of motion" to "Lleva cada rep por su recorrido completo.",
    "sagging hips" to "Mantén la cadera en línea — aprieta los glúteos.",
    "knee valgus" to "Lleva las rodillas hacia fuera, sobre las puntas.",
    "heel raise" to "Mantén los talones en el suelo toda la repetición.",
    "leaning back" to "Pecho arriba — deja de echarte hacia atrás.",
    "arm swing" to "Brazos quietos — no busques el equilibrio con ellos.",
    "piked hips" to "Cuerpo plano — sin pica en la cadera.",
    "piked body" to "Cuerpo plano — sin pica en la cadera.",
    "bent knees" to "Piernas estiradas durante todo el hold.",
)

/** Advice is tied to the selected rep's measured fault. */
fun repAdvice(rep: RepRow): String? = repFaults(rep).firstOrNull()?.let { CUES[it] }

/**
 * What this rep could not be judged on, in plain words.
 *
 * A fault that did not fire because its measurement was missing is not the
 * same as a rep that passed, and the app has to be able to say so - a camera
 * that cannot see the knees is not evidence of good knees.
 */
fun unmeasuredNote(rep: RepRow): String? {
    // A rep withheld from assessment altogether: no fault list is a verdict here.
    rep.assessmentBlocked?.let { return "Esta repetición no se juzgó — $it." }
    // Measurement version 2 ships every check with its verdict; name the
    // ones that could not be made, grouped by why.
    if (rep.assessments.isNotEmpty()) {
        val blind = rep.unobservable
        if (blind.isEmpty()) return null
        val byReason = blind.groupBy { it.reasonLabel().ifBlank { "sin seguir" } }
        val parts = byReason.entries.map { (why, rows) ->
            rows.joinToString(", ") { it.name } + " ($why)"
        }
        return "Sin juzgar: " + parts.joinToString("; ") +
            " — se hicieron ${rep.checked} de ${rep.assessments.size} comprobaciones."
    }
    if (rep.viewBlocked.isNotEmpty()) {
        return "Algunas comprobaciones necesitan otro ángulo de cámara — " +
            "${rep.viewBlocked.size} no se juzgaron desde este."
    }
    if (rep.unmeasured.isNotEmpty()) {
        return if (rep.unmeasured.size == 1) "1 comprobación no tuvo medida en este clip y se quedó sin juzgar."
        else "${rep.unmeasured.size} comprobaciones no tuvieron medida en este clip y se quedaron sin juzgar."
    }
    return null
}

/** The lines the "Improve" panel shows.
 *
 * An empty fault list means two different things, and they must not share a
 * sentence: a set that was measured and held up, or a set with no measurable
 * rep at all. The second one printed "the set measured clean" directly under
 * a headline reading "Barra couldn't score this set". */
fun improvementLines(analysis: Analysis): List<String> {
    val cues = improvementCues(analysis)
    if (cues.isNotEmpty()) return cues
    if (analysis.reps.isEmpty()) {
        return listOf("Nada que señalar — barra no pudo medir ninguna repetición en este clip.")
    }
    // "Clean" is a claim about checks that were made. With the structured
    // assessment we know how many were: none made means nothing was judged.
    val checks = analysis.checks
    if (checks.isNotEmpty()) {
        val made = checks.sumOf { it.observed + it.notObserved }
        val blind = checks.sumOf { it.unobservable }
        if (made == 0) {
            return listOf("Nada señalado — pero no se pudo hacer ninguna comprobación en este clip " +
                "($blind sin juzgar). Filma más cerca, de lado, con todo el cuerpo en el encuadre.")
        }
        if (blind > 0) {
            return listOf(
                "Nada señalado en las comprobaciones que se pudieron hacer.",
                if (blind == 1) "1 comprobación no se pudo hacer con esta grabación."
                else "$blind comprobaciones no se pudieron hacer con esta grabación.",
            )
        }
    }
    return listOf("Nada señalado — la serie salió limpia en lo medido.")
}
