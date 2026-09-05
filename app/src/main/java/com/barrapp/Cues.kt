package com.barrapp

import com.barrapp.data.Analysis
import com.barrapp.data.RepRow

/**
 * The coaching layer, kept deliberately small.
 *
 * Everything here is a restatement of a number the server already measured -
 * the range component's lockout share, the control penalty, the swing aside -
 * so a cue can only appear when the measurement says it should. No cue is
 * invented from a score alone, and no more than three are ever offered: three
 * things is what carries into the next set.
 */

/** The faults one rep was actually measured to have, most important first. */
internal fun repFaults(rep: RepRow): List<String> {
    val faults = mutableListOf<String>()

    // Swing is measured in torso-lengths of travel; a strict rep stays small.
    rep.asides.firstOrNull { it.name == "swing" }?.let {
        if (it.value > 0.4) faults += "momentum"
    }

    // The range component's why carries the two shares it scored on.
    rep.components.firstOrNull { it.name == "range" }?.let { range ->
        val lockout = Regex("lockout (\\d+)% of full").find(range.why)
            ?.groupValues?.get(1)?.toIntOrNull()
        val hang = Regex("hang (\\d+)% of full").find(range.why)
            ?.groupValues?.get(1)?.toIntOrNull()
        if (lockout != null && lockout < 85) faults += "lockout"
        if (hang != null && hang < 75) faults += "dead hang"
    }

    // A descent that fell rather than lowered. One-sided: absent costs nothing.
    rep.penalties.firstOrNull { it.name == "control" }?.let {
        if ((it.value ?: 0.0) > 0.0) faults += "control"
    }

    // The ascent stopped and snatched through the sticking point.
    rep.components.firstOrNull { it.name == "smoothness" }?.let {
        if ("% of the ascent made no progress" in it.why) faults += "stall"
    }

    return faults
}

/** The one fault that leads the rep's score, or null when it measured clean.
 *  These are the words that go over the video. */
fun repFault(rep: RepRow): String? = when (repFaults(rep).firstOrNull()) {
    "momentum" -> "Momentum"
    "lockout" -> "Not locking out"
    "dead hang" -> "Not a dead hang"
    "control" -> "Dropped the descent"
    "stall" -> "Stalled mid-pull"
    else -> null
}

/** What to work on, at most three of them, ordered by how many reps showed
 *  the fault. An empty list means the set measured clean. */
fun improvementCues(analysis: Analysis): List<String> {
    val counts = mutableMapOf<String, Int>()
    analysis.reps.forEach { rep ->
        repFaults(rep).forEach { counts.merge(it, 1, Int::plus) }
    }
    return counts.entries
        .sortedWith(compareByDescending<Map.Entry<String, Int>> { it.value }
            .thenBy { CUE_ORDER.indexOf(it.key) })
        .mapNotNull { CUES[it.key] }
        .take(3)
}

private val CUE_ORDER = listOf("momentum", "lockout", "dead hang", "control", "stall")

private val CUES = mapOf(
    "momentum" to "Stop the swing — pull strict, no momentum",
    "lockout" to "Lock out fully at the top of every rep",
    "dead hang" to "Start every rep from a full dead hang",
    "control" to "Lower under control — don't drop from the top",
    "stall" to "Drive through the sticking point in one arc",
)

/** Advice is tied to the selected rep's measured fault. */
fun repAdvice(rep: RepRow): String? = repFaults(rep).firstOrNull()?.let { CUES[it] }
