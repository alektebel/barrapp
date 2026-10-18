package com.barrapp

import com.barrapp.data.DayEntry
import com.barrapp.data.MovementDay
import com.barrapp.data.SkillGraph
import com.barrapp.ui.tracker.HistoryRow
import com.barrapp.ui.tracker.SkillNodeUi
import com.barrapp.ui.tracker.SkillPathData
import com.barrapp.ui.tracker.SessionPoint
import com.barrapp.ui.tracker.chartTitle
import com.barrapp.ui.tracker.dayNumber
import com.barrapp.ui.tracker.missingForNext
import com.barrapp.ui.tracker.monthAbbrev
import com.barrapp.ui.tracker.movementSeriesFrom
import com.barrapp.ui.tracker.pathSteps
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * The pure logic behind design 2d: the history folded into per-movement
 * series, the chart's real weeks and months, and the vertical path with its
 * single "Te falta" line.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class ProgressPathTest {

    private fun row(date: String, label: String, movement: String, reps: Int, score: Int?) =
        HistoryRow(date, label, movement, reps, 1, score)

    private fun day(date: String, movement: String, reps: Int, score: Int?) = DayEntry(
        date = date, exercise = movement, exerciseLabel = movement,
        reps = reps, score = score, band = "solid", jobIds = listOf("j-$date"),
        byMovement = mapOf(
            movement to MovementDay(movement, movement, reps, reps, (score ?: 0) * reps)
        ),
    )

    @Test
    fun `history rows fold into one series per movement, most recent first`() {
        val series = movementSeriesFrom(listOf(
            row("2026-09-08", "8 sept", "Dominada", 8, 71),
            row("2026-09-07", "7 sept", "Flexión", 12, null),
            row("2026-09-06", "6 sept", "Dominada", 6, 64),
        ))
        assertEquals(listOf("Dominada", "Flexión"), series.map { it.label })
        val dom = series.first()
        assertEquals(listOf("2026-09-06", "2026-09-08"), dom.sessions.map { it.date })
        assertEquals(listOf(64, 71), dom.sessions.map { it.score })
        assertEquals(8, dom.maxCleanReps)
        assertEquals(71, dom.bestRep)
    }

    @Test
    fun `average and delta come from the sessions, not from anywhere else`() {
        val series = movementSeriesFrom(listOf(
            row("2026-08-09", "9 ago", "Dominada", 5, 52),
            row("2026-08-16", "16 ago", "Dominada", 5, 56),
            row("2026-08-23", "23 ago", "Dominada", 5, 60),
            row("2026-08-30", "30 ago", "Dominada", 5, 64),
        ))
        assertEquals(58, series.single().average)
        assertEquals(8, series.single().delta)
    }

    @Test
    fun `a movement never measured has no series at all`() {
        assertTrue(movementSeriesFrom(emptyList()).isEmpty())
    }

    @Test
    fun `the title counts the weeks the sessions really span`() {
        val eight = listOf(
            SessionPoint("2026-08-09", "9 ago", 52),
            SessionPoint("2026-09-27", "27 sept", 69),
        )
        assertEquals("CALIDAD MEDIA · 8 SEMANAS", chartTitle(eight))
        assertEquals("CALIDAD MEDIA · 1 SEMANA", chartTitle(
            listOf(SessionPoint("2026-09-01", "1 sept", 52),
                SessionPoint("2026-09-03", "3 sept", 55))))
        // No real dates, no invented window.
        assertEquals("CALIDAD MEDIA", chartTitle(listOf(SessionPoint("8 sept", "8 sept", 52))))
    }

    @Test
    fun `the axis labels are the real months`() {
        assertEquals("AGO", monthAbbrev("2026-08-09"))
        assertEquals("OCT", monthAbbrev("2026-10-08"))
        assertEquals("", monthAbbrev("8 sept"))
        assertEquals("", monthAbbrev("2026-13-40"))
    }

    @Test
    fun `days since the epoch match the calendar`() {
        assertEquals(0L, dayNumber("1970-01-01"))
        assertEquals(11017L, dayNumber("2000-03-01"))
        assertEquals(49L, dayNumber("2026-09-27")!! - dayNumber("2026-08-09")!!)
        assertNull(dayNumber("9 ago"))
        assertNull(dayNumber("2026-02-31"))
    }

    @Test
    fun `the path marks the next step once and nobody else`() {
        val next = SkillNodeUi("slow_pull_up", "Dominada lenta", SkillGraph.AVAILABLE, true)
        val steps = pathSteps(SkillPathData(
            targetId = "muscle_up",
            targetName = "Muscle-up",
            rows = listOf(
                listOf(
                    SkillNodeUi("australian_pull_up", "Dominada australiana", SkillGraph.VERIFIED, false),
                    SkillNodeUi("pull_up", "Dominada estricta", SkillGraph.CLAIMED, false),
                ),
                listOf(next),
                listOf(SkillNodeUi("muscle_up", "Muscle-up", SkillGraph.LOCKED, false)),
            ),
            edges = emptyList(),
            next = next,
            nextStandard = "5 repeticiones con calidad 47 o más, en 2 días distintos. " +
                "barra lo verifica con tus vídeos.",
            targets = emptyList(),
        ))
        assertEquals(
            listOf(
                "Completado", "Hecho",
                "Ahora: 5 repeticiones con calidad 47 o más, en 2 días distintos",
                "Bloqueado hasta completar el anterior",
            ),
            steps.map { it.note },
        )
        assertEquals(1, steps.count { it.next })
        // Without measured days there is no honest gap: the line stays quiet.
        assertTrue(steps.none { it.missing != null })
    }

    @Test
    fun `the missing line counts what the standard still asks`() {
        val graph = SkillGraph.parse(
            """{"skills":[{"id":"slow_pull_up","name":"Dominada lenta","family":"pull",
                "requires":[],"tier":3,"measurable":true,
                "standard":{"reps":5,"quality":60,"days":2}}]}"""
        )
        val next = SkillNodeUi("slow_pull_up", "Dominada lenta", SkillGraph.AVAILABLE, true)

        val missing = missingForNext(graph, next, listOf(
            day("2026-09-01", "slow_pull_up", reps = 4, score = 55),
            day("2026-09-02", "slow_pull_up", reps = 3, score = 50),
        ))
        assertEquals("1 repetición más en una sesión (vas por 4), " +
            "y calidad 60 o más (mejor hasta ahora: 55), y 2 días más que cumplan", missing)

        // Nothing measured yet: it says so, it does not invent numbers.
        assertEquals("todavía no hay repeticiones medidas de esta habilidad",
            missingForNext(graph, next, emptyList()))

        // Standard met on enough days: verified, nothing missing.
        assertEquals(null, missingForNext(graph, next, listOf(
            day("2026-09-01", "slow_pull_up", reps = 5, score = 60),
            day("2026-09-02", "slow_pull_up", reps = 6, score = 65),
        )))

        // A skill barra cannot measure asks for nothing countable.
        val unmeasurable = SkillGraph.parse(
            """{"skills":[{"id":"human_flag","name":"Human flag","family":"pull",
                "requires":[],"tier":4,"measurable":false}]}"""
        )
        assertNull(missingForNext(unmeasurable,
            SkillNodeUi("human_flag", "Human flag", SkillGraph.AVAILABLE, true), emptyList()))
    }

    @Test
    fun `the caller's gap reaches the path and only the next step`() {
        val next = SkillNodeUi("slow_pull_up", "Dominada lenta", SkillGraph.AVAILABLE, true)
        val steps = pathSteps(SkillPathData(
            targetId = "muscle_up", targetName = "Muscle-up",
            rows = listOf(listOf(next), listOf(SkillNodeUi("muscle_up", "Muscle-up", SkillGraph.LOCKED, false))),
            edges = emptyList(), next = next, nextStandard = null, targets = emptyList(),
        ), missingFor = "2 repeticiones más en una sesión")
        assertEquals("2 repeticiones más en una sesión", steps[0].missing)
        assertNull(steps[1].missing)
    }
}
