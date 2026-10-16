package com.barrapp

import com.barrapp.data.Analysis
import com.barrapp.data.CheckSummary
import com.barrapp.data.DayEntry
import com.barrapp.data.JobSummary
import com.barrapp.data.MovementDay
import com.barrapp.data.RepRow
import com.barrapp.ui.tracker.CoachBasisPicker
import com.barrapp.ui.tracker.ResultComparison
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class CoachBasisTest {
    private fun rep(score: Int?) = RepRow(
        session = "s", label = "x", transitionS = "", totalS = "", cls = "rep", score = score,
    )

    private fun analysis(ex: String, date: String, score: Int?, n: Int = 1) = Analysis(
        headline = "", narrative = "", sessions = emptyList(),
        reps = List(n) { rep(score) }, blockers = emptyList(), nextSession = "",
        exercise = ex, repCount = n, sessionDate = date, sessionScore = score,
        checks = listOf(CheckSummary("e1", "fast_descent", "descent", 1, 0, 0)),
    )

    // Same day: two scored muscle-ups, then push-ups nobody could score.
    private val day = DayEntry(
        date = "2026-10-16", exercise = "push_up", exerciseLabel = "Flexiones", reps = 22,
        score = 57, band = "ok", jobIds = listOf("a", "b", "c"),
        byMovement = mapOf(
            "muscle_up" to MovementDay("muscle_up", "Muscle-up", 3, 3, 170),
            "push_up" to MovementDay("push_up", "Flexiones", 19, 0, 0),
        ),
        last = JobSummary("c", "push_up", "Flexiones", 19, 0, null),
    )

    @Test fun unscoredLastFallsBackToScoredSessionOfOtherMovement() {
        val mu = analysis("muscle_up", "2026-10-16", 56, 2)
        val push = analysis("push_up", "2026-10-16", null, 19)
        val b = CoachBasisPicker.pick(listOf(day), listOf(push, mu))
        assertEquals("push_up", b.unscoredLast?.exercise)
        assertEquals(19, b.unscoredLast?.reps)
        assertEquals("muscle_up", b.scoredKey)
        assertTrue(b.rulesFrom === mu)
    }

    @Test fun rulesNeverComeFromTheUnmeasuredAnalysis() {
        val push = analysis("push_up", "2026-10-16", null, 19)
        val b = CoachBasisPicker.pick(listOf(day), listOf(push))
        assertNull(b.rulesFrom)
        assertEquals("muscle_up", b.scoredKey)
    }

    @Test fun scoredLastHasNoNotice() {
        val d = day.copy(last = JobSummary("c", "muscle_up", "Muscle-up", 2, 2, 56))
        val b = CoachBasisPicker.pick(listOf(d), emptyList())
        assertNull(b.unscoredLast)
        assertEquals("muscle_up", b.scoredKey)
    }

    @Test fun noScoredSessionIsAnHonestEmptyState() {
        val d = DayEntry("2026-10-16", "push_up", "Flexiones", 19, null, "unmeasured",
            listOf("c"), mapOf("push_up" to MovementDay("push_up", "Flexiones", 19, 0, 0)),
            last = JobSummary("c", "push_up", "Flexiones", 19, 0, null))
        val b = CoachBasisPicker.pick(listOf(d), emptyList())
        assertEquals(19, b.unscoredLast?.reps)
        assertNull(b.scoredDay)
    }

    @Test fun firstMeasurementOnlyWithNoEarlierScoredSetOfThatMovement() {
        val first = analysis("muscle_up", "2026-10-16", 58, 1)
        val d1 = day.copy(jobIds = listOf("a"), byMovement = mapOf(
            "muscle_up" to MovementDay("muscle_up", "Muscle-up", 1, 1, 58)))
        assertNull(ResultComparison.aboveAverage(first, listOf(d1), "a"))
        // Second clip same day: the first one is earlier work.
        val second = analysis("muscle_up", "2026-10-16", 56, 2)
        val d2 = day.copy(jobIds = listOf("a", "b"), byMovement = mapOf(
            "muscle_up" to MovementDay("muscle_up", "Muscle-up", 3, 3, 58 + 112)))
        assertEquals(false, ResultComparison.aboveAverage(second, listOf(d2), "b"))
    }

    @Test fun unscoredSetHasNoComparison() {
        val push = analysis("push_up", "2026-10-16", null, 19)
        assertNull(ResultComparison.aboveAverage(push, listOf(day), "c"))
        assertFalse(day.byMovement["push_up"]!!.verified > 0)
    }
}
