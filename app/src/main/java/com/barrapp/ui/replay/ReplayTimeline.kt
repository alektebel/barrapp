package com.barrapp.ui.replay

import com.barrapp.data.Analysis
import com.barrapp.data.MeasuredFault
import com.barrapp.data.RepRow
import com.barrapp.faultEs
import com.barrapp.repFaults

/**
 * One rep as the replay schedules it: when it happens in the clip, and what
 * to say when it ends. Built from the server's measurement; nothing here
 * judges a rep the server did not judge.
 */
data class ReplayRep(
    /** 0-based position in the set; the athlete reads it as `number`. */
    val index: Int,
    val startS: Double,
    val endS: Double,
    /** The turnaround, where a rep's fault is usually visible. */
    val turnS: Double,
    /** The leading fault in Spanish, or null when the rep measured clean. */
    val fault: String?,
    /** Fault keys this rep showed, most important first. */
    val faultKeys: List<String>,
    /** How far past its threshold each fault went, in units of |threshold|. */
    val exceedance: Map<String, Double>,
    /** False when the rep was counted but could not be scored. */
    val measured: Boolean,
    val band: String,
    /** The rep broke its set's own pattern (server `outlier`). */
    val outlier: Boolean,
    /** How it broke it, in Spanish ("recorrido un 40 % menor que tu rep
     *  media"), or null when it did not. */
    val shapeNote: String? = null,
) {
    val number: Int get() = index + 1

    /** Where to land when someone asks to see this rep. */
    val moment: Double get() = turnS.takeIf { it in startS..endS } ?: startS
}

/**
 * The schedule of a replay: which rep is on screen at a time, how many have
 * finished, which verdict to show, and which stretches to skip when only the
 * reps are wanted. Pure, so the counter that has to rise with the video can be
 * tested without a video.
 */
class ReplayPlan(
    reps: List<ReplayRep>,
    /** Playback stays inside this window: the set, not the walk to the bar. */
    val windowStart: Double,
    val windowEnd: Double,
) {
    val reps: List<ReplayRep> = reps
        .filter { it.endS > it.startS && it.endS > windowStart && it.startS < windowEnd }
        .sortedBy { it.startS }

    val total: Int get() = reps.size

    /** The rep being performed at [t], or null between reps. */
    fun activeRepAt(t: Double): ReplayRep? =
        reps.firstOrNull { t >= it.startS && t < it.endS }

    /** How many reps have finished by [t]: the number the counter shows. */
    fun repsDoneBy(t: Double): Int = reps.count { it.endS <= t }

    /**
     * The rep whose verdict is on screen at [t]: from the moment it ends for
     * [holdS] seconds, cut short when the next rep ends sooner.
     */
    fun verdictAt(t: Double, holdS: Double = VERDICT_HOLD_S): ReplayRep? =
        reps.lastOrNull { t >= it.endS && t < it.endS + holdS }

    /**
     * The stretches worth playing when only the reps are wanted: each rep
     * padded by [padS], merged with its neighbour when the rest between them
     * is under [gapS]. This is the cut the measurement makes, applied at
     * playback - the file on the phone is never rewritten.
     */
    fun compactSegments(gapS: Double = COMPACT_GAP_S, padS: Double = COMPACT_PAD_S): List<ClosedFloatingPointRange<Double>> {
        val out = mutableListOf<ClosedFloatingPointRange<Double>>()
        for (rep in reps) {
            val a = (rep.startS - padS).coerceAtLeast(windowStart)
            val b = (rep.endS + padS).coerceAtMost(windowEnd)
            val last = out.lastOrNull()
            if (last != null && a - last.endInclusive <= gapS) {
                out[out.lastIndex] = last.start..maxOf(last.endInclusive, b)
            } else {
                out += a..b
            }
        }
        return out
    }

    /** Seconds of rest [compactSegments] would skip inside the window. */
    fun skippableS(): Double {
        val segments = compactSegments()
        if (segments.isEmpty()) return 0.0
        return (windowEnd - windowStart) - segments.sumOf { it.endInclusive - it.start }
    }

    /** Skip the rest by default only when there is enough of it to notice. */
    val compactByDefault: Boolean get() = skippableS() > COMPACT_DEFAULT_MIN_S

    /**
     * Where playback should be at [t] in compact mode: null when [t] is inside
     * a segment (keep playing), the next segment's start when [t] is in a rest,
     * and [Double.NaN] when [t] is past the last segment - the set is over.
     */
    fun compactJump(t: Double): Double? {
        val segments = compactSegments()
        if (segments.isEmpty()) return null
        if (segments.any { t >= it.start && t <= it.endInclusive }) return null
        return segments.firstOrNull { it.start > t }?.start ?: Double.NaN
    }

    /**
     * Guided review: the faulted rep whose turnaround playback just reached,
     * if it has not been shown yet. Playback pauses there so the fault is
     * looked at, not scrolled past.
     */
    fun guidedStop(t: Double, reviewed: Set<Int>): ReplayRep? =
        reps.firstOrNull {
            it.fault != null && it.index !in reviewed && t >= it.moment && t <= it.endS
        }

    /** The reps a guided pass has gone by at [t]. */
    fun reviewedBy(t: Double): Set<Int> =
        reps.filter { it.moment <= t + SEEK_SLACK_S }.map { it.index }.toSet()

    /** The rep that shows a fault worst - "Ver en la rep N". */
    fun worstRepFor(faultKey: String): ReplayRep? =
        reps.filter { faultKey in it.faultKeys }
            .maxByOrNull { it.exceedance[faultKey] ?: 0.0 }

    fun clamp(t: Double): Double = t.coerceIn(windowStart, windowEnd)

    companion object {
        const val VERDICT_HOLD_S = 1.5
        const val COMPACT_GAP_S = 1.0
        const val COMPACT_PAD_S = 0.3
        const val COMPACT_DEFAULT_MIN_S = 3.0
        private const val SEEK_SLACK_S = 0.15

        /**
         * The plan for a measured clip of [clipDurationS] seconds. The window
         * is the server's trim, else the hull of its active spans, else the
         * whole clip.
         */
        fun from(a: Analysis, clipDurationS: Double): ReplayPlan {
            val end = clipDurationS.takeIf { it > 0 } ?: a.durationS.takeIf { it > 0 }
                ?: a.reps.maxOfOrNull { it.endS } ?: 0.0
            val trim = a.trim?.takeIf { it.endS > it.startS }
            val spans = a.activeSpans
            val start = trim?.startS ?: spans.minOfOrNull { it.startS } ?: 0.0
            val stop = trim?.endS ?: spans.maxOfOrNull { it.endS } ?: end
            return ReplayPlan(
                reps = a.reps.mapIndexed { i, r -> replayRep(i, r) },
                windowStart = start.coerceAtLeast(0.0),
                windowEnd = stop.coerceAtMost(end).takeIf { it > start } ?: end,
            )
        }

        internal fun replayRep(index: Int, rep: RepRow): ReplayRep {
            val keys = repFaults(rep)
            return ReplayRep(
                index = index,
                startS = rep.startS,
                endS = rep.endS,
                turnS = rep.turnS,
                fault = keys.firstOrNull()?.let(::faultEs),
                faultKeys = keys,
                exceedance = rep.faults.associate { it.name to exceedance(it) },
                measured = rep.score != null,
                band = rep.band,
                outlier = rep.outlier,
                shapeNote = if (rep.outlier) shapeNote(rep.amplitudeVsSet, rep.tempoVsSet) else null,
            )
        }

        /** The server's marks, put into words. Mirrors barra/config.py. */
        internal fun shapeNote(amplitude: Double?, tempo: Double?): String? {
            val parts = buildList {
                amplitude?.takeIf { kotlin.math.abs(it) > AMPLITUDE_OUTLIER }?.let {
                    add("recorrido un ${pct(it)} % ${if (it > 0) "mayor" else "menor"}")
                }
                tempo?.takeIf { kotlin.math.abs(it) > TEMPO_OUTLIER }?.let {
                    add("un ${pct(it)} % más ${if (it > 0) "lenta" else "rápida"}")
                }
            }
            if (parts.isEmpty()) return null
            return parts.joinToString(" y ").replaceFirstChar { it.uppercase() } + " que tu rep media."
        }

        private fun pct(x: Double) = kotlin.math.round(kotlin.math.abs(x) * 100).toInt()
        private const val AMPLITUDE_OUTLIER = 0.20
        private const val TEMPO_OUTLIER = 0.25

        /** The same normalisation the server ranks by (barra/fault_select). */
        internal fun exceedance(f: MeasuredFault): Double {
            val v = f.value ?: return 0.0
            val scale = kotlin.math.abs(f.threshold) + 1e-6
            return if (f.comparison.startsWith("<")) (f.threshold - v) / scale
            else (v - f.threshold) / scale
        }
    }
}

/** "Ritmo ±12 % · Recorrido ±8 %", or null when the set had no CVs. */
fun consistencyLine(a: Analysis): String? {
    val parts = buildList {
        a.tempoCV?.let { add("Ritmo ±${(it * 100).toInt()} %") }
        a.amplitudeCV?.let { add("Recorrido ±${(it * 100).toInt()} %") }
    }
    if (parts.isEmpty()) return null
    val band = when (a.consistencyBand) {
        "estable" -> "Serie estable"
        "irregular" -> "Serie irregular"
        else -> null
    }
    return listOfNotNull(band, parts.joinToString(" · ")).joinToString(" — ")
}
