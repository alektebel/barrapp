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
        return rep.faults.map { it.name }.sortedBy { orderOf(it) }
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
        if ((it.value ?: 0.0) > 0.0) faults += "control"
    }
    return faults
}

/** The one threshold left on the phone, and only for rows measured before the
 *  server named its own faults. Not consulted for anything current. */
private const val LEGACY_SWING_TORSO = 0.4

/** The one fault that leads the rep's score, or null when it measured clean.
 *  These are the words that go over the video. */
fun repFault(rep: RepRow): String? = when (repFaults(rep).firstOrNull()) {
    "momentum" -> "Momentum"
    "lockout" -> "Not locking out"
    "dead hang" -> "Not a dead hang"
    "control" -> "Dropped the descent"
    "stall" -> "Stalled mid-pull"
    "poor transition" -> "Slow transition"
    "bent arms" -> "Bent arms"
    "no active hang" -> "No active hang"
    "too fast" -> "Thrown, not pulled"
    "too deep" -> "Too deep"
    "bounce at bottom" -> "Bounced at the bottom"
    "poor range of motion" -> "Short range"
    "sagging hips" -> "Hips sagging"
    "uncontrolled descent" -> "Dropped the descent"
    "knee valgus" -> "Knees caving in"
    "heel raise" -> "Heels lifting"
    "leaning back" -> "Leaning back"
    "arm swing" -> "Arm swing"
    "piked hips", "piked body" -> "Piked body line"
    "bent knees" -> "Bent knees"
    "poor scapular retraction" -> "Shoulders not set"
    "poor scapular protraction" -> "Shoulders not pushed"
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
                if (e.key in variantDependent) "$cue — judged strict; declare kipping if that was the plan"
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
    "poor scapular retraction", "poor scapular protraction",
    "control", "uncontrolled descent", "too fast", "bounce at bottom",
    "stall", "poor transition",
)

private fun orderOf(name: String): Int =
    CUE_ORDER.indexOf(name).let { if (it < 0) CUE_ORDER.size else it }

private val CUES = mapOf(
    "momentum" to "Stop the swing — pull strict, no momentum",
    "lockout" to "Lock out fully at the top of every rep",
    "dead hang" to "Start every rep from a full dead hang",
    "control" to "Lower under control — don't drop from the top",
    "stall" to "Drive through the sticking point in one arc",
    "poor transition" to "Get through the transition in one movement",
    "bent arms" to "Press out to straight arms at the top of every rep",
    "no active hang" to "Straighten the arms between reps — hang, then pull",
    "too fast" to "Slow the pull down — these are being thrown",
    "too deep" to "Stop at ninety degrees — deeper is shoulder, not chest",
    "bounce at bottom" to "Pause at the bottom instead of bouncing out of it",
    "poor range of motion" to "Take every rep through its full range",
    "sagging hips" to "Hold the hips in line — squeeze the glutes",
    "uncontrolled descent" to "Lower under control — don't drop into the hole",
    "knee valgus" to "Drive the knees out over the toes",
    "heel raise" to "Keep the heels down through the whole rep",
    "leaning back" to "Keep the chest up — stop leaning back out of it",
    "arm swing" to "Keep the arms still — no swinging for balance",
    "piked hips" to "Hold the body flat — no piking at the hips",
    "piked body" to "Hold the body flat — no piking at the hips",
    "bent knees" to "Keep the legs straight through the hold",
    "poor scapular retraction" to "Set the shoulders down and back first",
    "poor scapular protraction" to "Push the shoulders away at the top",
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
    rep.assessmentBlocked?.let { return "This rep was not judged — $it." }
    // Measurement version 2 ships every check with its verdict; name the
    // ones that could not be made, grouped by why.
    if (rep.assessments.isNotEmpty()) {
        val blind = rep.unobservable
        if (blind.isEmpty()) return null
        val byReason = blind.groupBy { it.reasonLabel().ifBlank { "not tracked" } }
        val parts = byReason.entries.map { (why, rows) ->
            rows.joinToString(", ") { it.name } + " ($why)"
        }
        return "Not judged: " + parts.joinToString("; ") +
            " — ${rep.checked} of ${rep.assessments.size} checks were made."
    }
    if (rep.viewBlocked.isNotEmpty()) {
        return "Some checks need a different camera angle — " +
            "${rep.viewBlocked.size} of them were not judged from this one."
    }
    if (rep.unmeasured.isNotEmpty()) {
        return "${rep.unmeasured.size} check${if (rep.unmeasured.size == 1) "" else "s"} " +
            "had no measurement in this clip and were left unjudged."
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
        return listOf("Nothing to flag — barra could not measure a rep in this clip.")
    }
    // "Clean" is a claim about checks that were made. With the structured
    // assessment we know how many were: none made means nothing was judged.
    val checks = analysis.checks
    if (checks.isNotEmpty()) {
        val made = checks.sumOf { it.observed + it.notObserved }
        val blind = checks.sumOf { it.unobservable }
        if (made == 0) {
            return listOf("Nothing flagged — but no check could be made on this clip " +
                "($blind left unjudged). Film closer, side-on, with the whole body in frame.")
        }
        if (blind > 0) {
            return listOf(
                "Nothing flagged on the checks that were made.",
                "$blind check${if (blind == 1) "" else "s"} could not be made from this footage.",
            )
        }
    }
    return listOf("Nothing flagged — the set measured clean.")
}
