package com.barrapp

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.barrapp.data.ActivityLevel
import com.barrapp.data.Analysis
import com.barrapp.data.DayEntry
import com.barrapp.data.MovementDay
import com.barrapp.data.Profile
import com.barrapp.data.RepRow
import com.barrapp.data.SessionStore
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
@org.robolectric.annotation.Config(sdk = [34])
class SessionRecordTest {
    private val ctx: Context get() = ApplicationProvider.getApplicationContext()

    @Before fun clean() = SessionStore.forgetAll(ctx)

    private fun rep(score: Int?) = RepRow(
        session = "s", label = "r", transitionS = "", totalS = "", cls = "rep", score = score)

    private fun analysis(exercise: String, vararg scores: Int?) = Analysis(
        headline = "", narrative = "", sessions = emptyList(),
        reps = scores.map { rep(it) }, blockers = emptyList(), nextSession = "",
        exercise = exercise, repCount = scores.size, sessionDate = "2026-10-16",
    )

    @Test fun sameJobRecordedTwiceCountsOnce() {
        val a = analysis("muscle_up", 58)
        SessionStore.record(ctx, "job-1", a)
        SessionStore.record(ctx, "job-1", a)
        val day = SessionStore.days(ctx).single()
        assertEquals(1, day.reps)
        assertEquals(1, day.verifiedReps)
        assertEquals(58, day.score)
        SessionStore.record(ctx, "job-2", analysis("muscle_up", 50, 62))
        assertEquals(3, SessionStore.days(ctx).single().reps)
    }

    @Test fun lastJobIsKeptApartFromTheDay() {
        SessionStore.record(ctx, "a", analysis("muscle_up", 58), "2026-10-16T10:00:00")
        SessionStore.record(ctx, "b", analysis("push_up", null, null, null), "2026-10-16T11:00:00")
        val day = SessionStore.days(ctx).single()
        assertEquals("push_up", day.last!!.exercise)
        assertEquals(3, day.last!!.reps)
        assertEquals(0, day.last!!.verified)
        // an older clip arriving late does not displace it
        SessionStore.record(ctx, "c", analysis("muscle_up", 70), "2026-10-16T09:00:00")
        assertEquals("b", SessionStore.days(ctx).single().last!!.jobId)
    }

    @Test fun recordsArePerMovementAndScoredOnly() {
        val days = listOf(
            DayEntry("2026-10-16", "push_up", "Flexión", 21, 57, "solid", listOf("a", "b", "c"),
                byMovement = mapOf(
                    "push_up" to MovementDay("push_up", "Flexión", 19, 0, 0),
                    "muscle_up" to MovementDay("muscle_up", "Muscle-up", 2, 2, 114))),
        )
        val r = Progression.records(days)
        assertEquals(listOf("muscle_up"), r.map { it.movement })
        assertEquals(57, r.single().bestScore)
        assertEquals(2, r.single().mostReps)
    }

    @Test fun coachDescribesTheLastJob() {
        SessionStore.record(ctx, "a", analysis("muscle_up", 58, 56), "2026-10-16T10:00:00")
        SessionStore.record(ctx, "b", analysis("push_up", null, null), "2026-10-16T11:00:00")
        val p = Profile("Diego", 30, ActivityLevel.Regular)
        val ans = Coach.answer("¿Qué mostró realmente mi última sesión?", SessionStore.days(ctx), p)
        assertTrue(ans, ans.contains("16 oct"))
        assertTrue(ans, ans.contains("Flexión"))
        assertTrue(ans, ans.contains("2 repeticiones contadas"))
        assertTrue(ans, ans.contains("sin puntuar"))
        assertFalse(ans, ans.contains("medidas"))
        assertFalse(ans, ans.contains("2026-10-16"))
    }

    @Test fun aDayKeepsEverySessionWithItsOwnScore() {
        SessionStore.record(ctx, "a", analysis("muscle_up", 80, 80), "2026-10-16T10:00:00")
        SessionStore.record(ctx, "b", analysis("muscle_up", 40), "2026-10-16T11:00:00")
        val day = SessionStore.days(ctx).single()
        assertEquals(listOf("a", "b"), day.sessions.map { it.jobId })
        assertEquals(listOf(80, 40), day.sessions.map { it.score })
        // weighted by scored reps: (80+80+40)/3, not the mean of the clips (60)
        assertEquals(66, day.score)
    }

    @Test fun anUnmeasuredSessionDoesNotLowerTheDay() {
        SessionStore.record(ctx, "a", analysis("muscle_up", 80, 70), "2026-10-16T10:00:00")
        SessionStore.record(ctx, "b", analysis("push_up", null, null), "2026-10-16T11:00:00")
        val day = SessionStore.days(ctx).single()
        assertEquals(75, day.score)
        assertEquals(2, day.sessions.size)
        assertEquals(null, day.sessions.last().score)
    }

    @Test fun deletingASessionRebuildsTheDay() {
        SessionStore.record(ctx, "a", analysis("muscle_up", 80, 80), "2026-10-16T10:00:00")
        SessionStore.record(ctx, "b", analysis("muscle_up", 40), "2026-10-16T11:00:00")
        SessionStore.forget(ctx, "b")
        val day = SessionStore.days(ctx).single()
        assertEquals(listOf("a"), day.jobIds)
        assertEquals(80, day.score)
        assertEquals(2, day.reps)
        assertEquals("a", day.last!!.jobId)
        SessionStore.forget(ctx, "a")
        assertTrue(SessionStore.days(ctx).isEmpty())
    }

    @Test fun aFinishedClipStaysNewUntilItIsOpened() {
        assertTrue(SessionStore.unseen(ctx).isEmpty())
        SessionStore.addUnseen(ctx, "a")
        SessionStore.addUnseen(ctx, "b")
        assertEquals(setOf("a", "b"), SessionStore.unseen(ctx))
        SessionStore.markSeen(ctx, "a")
        assertEquals(setOf("b"), SessionStore.unseen(ctx))
        // deleting a clip is not news either
        SessionStore.record(ctx, "b", analysis("muscle_up", 80), "2026-10-16T10:00:00")
        SessionStore.forget(ctx, "b")
        assertTrue(SessionStore.unseen(ctx).isEmpty())
        // signing out forgets what the previous account had not seen
        SessionStore.addUnseen(ctx, "c")
        SessionStore.forgetAll(ctx)
        assertTrue(SessionStore.unseen(ctx).isEmpty())
    }

    @Test fun theDayListsNewestSessionFirstAndShowsLocalTime() {
        SessionStore.record(ctx, "a", analysis("muscle_up", 80), "2026-10-16T10:00:00Z")
        SessionStore.record(ctx, "b", analysis("push_up", 60), "2026-10-16T11:30:00Z")
        val day = SessionStore.days(ctx).single()
        assertEquals(listOf("b", "a"), com.barrapp.ui.tracker.daySessions(day).map { it.jobId })
        // a day stored before the list existed still shows its last clip
        val legacy = day.copy(sessions = emptyList())
        assertEquals(listOf("b"), com.barrapp.ui.tracker.daySessions(legacy).map { it.jobId })
        val utc = java.util.TimeZone.getDefault()
        java.util.TimeZone.setDefault(java.util.TimeZone.getTimeZone("Europe/Madrid"))
        try {
            assertEquals("12:00", com.barrapp.ui.tracker.localTime("2026-10-16T10:00:00Z"))
            assertEquals(null, com.barrapp.ui.tracker.localTime(""))
        } finally {
            java.util.TimeZone.setDefault(utc)
        }
    }
}
