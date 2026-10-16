package com.barrapp

import com.barrapp.data.ActivityLevel
import com.barrapp.data.Analysis
import com.barrapp.data.DayEntry
import com.barrapp.data.MovementDay
import com.barrapp.data.Profile
import com.barrapp.data.RepRow
import com.barrapp.ui.tracker.unjudgedNote
import java.util.Calendar
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** A set the server counted but could not score is not a measured, clean set. */
class UnmeasuredSetTest {
    private val today = Calendar.getInstance()
    private val iso = "%04d-%02d-%02d".format(
        today.get(Calendar.YEAR), today.get(Calendar.MONTH) + 1, today.get(Calendar.DAY_OF_MONTH))

    private fun rep(score: Int?, blocked: String? = null) = RepRow(
        session = "s", label = "push_up", transitionS = "", totalS = "", cls = "rep",
        score = score, assessmentBlocked = blocked,
    )

    private fun analysis(vararg reps: RepRow) = Analysis(
        headline = "", narrative = "", sessions = emptyList(), reps = reps.toList(),
        blockers = emptyList(), nextSession = "", exercise = "push_up",
        repCount = reps.size,
    )

    private val unscoredDay = DayEntry(
        date = iso, exercise = "push_up", exerciseLabel = "Flexiones", reps = 19, score = null,
        band = "unmeasured", jobIds = listOf("j"),
        byMovement = mapOf("push_up" to MovementDay("push_up", "Flexiones", 19, 0, 0)),
    )

    @Test fun unscoredRepsAreAnUnmeasuredSet() {
        assertTrue(analysis(rep(null), rep(null)).unmeasuredSet)
        assertFalse(analysis(rep(null), rep(80)).unmeasuredSet)
    }

    @Test fun unmeasuredSetDoesNotCompleteTheMission() {
        val m = Gamification.mission(listOf(unscoredDay), Profile("A", 30, ActivityLevel.Regular),
            null, "", today)
        assertEquals(0, m.doneReps)
        assertFalse(m.complete)
        assertEquals(0, Gamification.standing(listOf(unscoredDay)).totalXp)
    }

    @Test fun unmeasuredSetCountsNoMeasuredRepsAndNoStreak() {
        assertEquals(0, unscoredDay.verifiedReps)
        assertEquals(0, Gamification.streak(listOf(unscoredDay), today))
        assertFalse(Gamification.week(listOf(unscoredDay), today).any { it.done })
    }

    @Test fun unmeasuredSetSaysItWasNotJudged() {
        val note = unjudgedNote(analysis(rep(null, "vista de frente"), rep(null)))!!
        assertTrue(note, note.contains("ninguna de las 2"))
        assertTrue(note, note.contains("vista de frente"))
        assertNull(unjudgedNote(analysis(rep(70))))
    }
}
