package com.barrapp.ui.tracker

import com.barrapp.data.Analysis
import com.barrapp.data.DayEntry

/**
 * Which session the Coach tab talks about.
 *
 * The coach must never mix two sessions: if the last one could not be scored
 * (counted reps, none judged) it says so, and everything else (focus, rules)
 * comes from the most recent session that WAS scored, named explicitly.
 */
data class CoachBasis(
    /** The last session with reps, when it was not scored. Null when it was. */
    val unscoredLast: UnscoredLast?,
    /** The most recent scored session; null when there is none. */
    val scoredDay: DayEntry?,
    /** The movement key of that scored session. */
    val scoredKey: String?,
    /** The scored analysis of that movement, source of the rules; null if
     *  none is available (only analyses still held in memory carry checks). */
    val rulesFrom: Analysis?,
) {
    data class UnscoredLast(val exercise: String, val label: String, val reps: Int)
}

object CoachBasisPicker {

    /** Whether this day's most recent clip was counted but never scored. */
    private fun unscored(day: DayEntry): Boolean {
        val job = day.last
        return if (job != null) job.score == null else day.score == null
    }

    /** The scored movement of a day: its last clip when scored, else the
     *  movement of the day with the most scored reps. */
    private fun scoredKeyOf(day: DayEntry): String? {
        day.last?.takeIf { it.score != null }?.let { return it.exercise }
        return day.byMovement.values.filter { it.verified > 0 }
            .maxByOrNull { it.verified }?.exercise
            ?: if (day.last == null && day.score != null) day.exercise else null
    }

    /**
     * [days] newest first (as the store keeps them); [analyses] newest first,
     * the ones the app still holds with their checks.
     */
    fun pick(days: List<DayEntry>, analyses: List<Analysis>): CoachBasis {
        val withReps = days.filter { it.reps > 0 }
        val last = withReps.firstOrNull()
        val unscoredLast = last?.takeIf { unscored(it) }?.let { d ->
            val job = d.last
            CoachBasis.UnscoredLast(
                exercise = job?.exercise ?: d.exercise,
                label = job?.label ?: d.exerciseLabel,
                reps = job?.reps ?: d.reps,
            )
        }
        val scoredDay = withReps.firstOrNull { scoredKeyOf(it) != null }
        val key = scoredDay?.let { scoredKeyOf(it) }
        val rulesFrom = if (key == null) null else analyses.firstOrNull {
            !it.unmeasuredSet && it.reps.isNotEmpty() && it.exercise == key &&
                it.checks.isNotEmpty() &&
                (it.sessionDate.isBlank() || it.sessionDate == scoredDay.date)
        }
        return CoachBasis(unscoredLast, scoredDay, key, rulesFrom)
    }
}

/**
 * How a result compares with the athlete's earlier scored work in the same
 * movement. Null when the set itself is unscored or when there is no earlier
 * scored work (the first measurement); true/false = above/below the mean.
 *
 * The current job is already folded into [days] by the time results show, so
 * its own reps are taken back out (only when its id is there) rather than
 * excluding the whole date, which wrongly hid earlier clips of the same day.
 */
object ResultComparison {

    fun aboveAverage(a: Analysis, days: List<DayEntry>, jobId: String?): Boolean? {
        val mine = a.reps.filter { it.score != null && it.complete }
        if (a.sessionScore == null && mine.isEmpty()) return null
        val key = a.exercise.ifBlank { "unknown" }
        val folded = jobId != null && days.any { jobId in it.jobIds }
        val verified = days.sumOf { it.byMovement[key]?.verified ?: 0 } -
            if (folded) mine.size else 0
        if (verified <= 0) return null
        val sum = days.sumOf { it.byMovement[key]?.scoreSum ?: 0 } -
            if (folded) mine.sumOf { it.score ?: 0 } else 0
        return (a.sessionScore ?: 0) >= sum.toDouble() / verified
    }

    /** This set's score minus the athlete's mean for the movement, excluding
     *  this set; null when there is no history to compare against. */
    fun vsAverage(a: Analysis, days: List<DayEntry>, jobId: String?): Int? {
        val score = a.sessionScore ?: return null
        val mine = a.reps.filter { it.score != null && it.complete }
        val key = a.exercise.ifBlank { "unknown" }
        val folded = jobId != null && days.any { jobId in it.jobIds }
        val verified = days.sumOf { it.byMovement[key]?.verified ?: 0 } -
            if (folded) mine.size else 0
        if (verified <= 0) return null
        val sum = days.sumOf { it.byMovement[key]?.scoreSum ?: 0 } -
            if (folded) mine.sumOf { it.score ?: 0 } else 0
        return Math.round(score - sum.toDouble() / verified).toInt()
    }
}
