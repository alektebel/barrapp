package com.barrapp.ui.tracker

import com.barrapp.data.Analysis
import com.barrapp.data.MeasuredFault
import com.barrapp.data.RepRow
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * The results phase (designs 2b and 3a): the timeline bars, the faults card
 * and the note's comparison line — the parts that turn the measurement into
 * sentences, where an invented number is the one unforgivable bug.
 */
class ResultsTizaTest {

    private fun rep(score: Int?, vararg faults: String, startS: Double = 1.0) = RepRow(
        session = "s", label = "", transitionS = "", totalS = "", cls = "",
        startS = startS, endS = startS + 2.0, turnS = startS + 1.0, score = score,
        faults = faults.map { MeasuredFault(name = it) },
    )

    private fun analysis(vararg reps: RepRow) = Analysis(
        headline = "", narrative = "", sessions = emptyList(),
        reps = reps.toList(), blockers = emptyList(), nextSession = "",
        durationS = 24.0,
    )

    private fun results(
        fixes: List<FixItem> = emptyList(),
        faults: List<Pair<String, Int>> = emptyList(),
        repCards: List<RepCardItem> = emptyList(),
        seriesLabel: String = "",
        whenLabel: String = "",
        score: Int? = 69,
    ) = ResultsData(
        movement = "Dominada", setsLabel = "1 serie", reps = 6, score = score,
        faults = faults, repCards = repCards, xp = 120, aboveAverage = null,
        fixes = fixes, seriesLabel = seriesLabel, whenLabel = whenLabel,
    )

    // ---- the timeline -------------------------------------------------------

    @Test
    fun `bars come from the measurement`() {
        val bars = repBars(
            analysis(
                rep(82, "momentum"),
                rep(null),
                rep(51),
            ),
            emptyList(),
        )
        assertEquals(3, bars.size)
        assertEquals(82, bars[0].score)
        assertEquals(true, bars[0].faulted)
        assertEquals(1.0, bars[0].startS!!, 1e-9)
        assertNull(bars[1].score)
        assertEquals(false, bars[1].faulted)
        assertEquals(false, bars[2].faulted)
    }

    @Test
    fun `bars fall back to the rep cards when no analysis arrived`() {
        val bars = repBars(null, listOf(
            RepCardItem("Rep 1", 88, listOf("Balanceo"), "1.2-3.0s", null),
            RepCardItem("Rep 2", null, emptyList(), "3.4-5.1s", null),
        ))
        assertEquals(true, bars[0].faulted)
        assertNull(bars[0].startS)
        assertNull(bars[1].score)
        assertEquals(false, bars[1].faulted)
    }

    // ---- where the faults fall ---------------------------------------------

    @Test
    fun `the faults sentence lists the reps`() {
        assertEquals("En las reps 4, 5 y 6.", faultRepsSentence(listOf(4, 5, 6)))
        assertEquals("En las reps 1 y 3.", faultRepsSentence(listOf(3, 1)))
        assertEquals("En la rep 4.", faultRepsSentence(listOf(4)))
        assertNull(faultRepsSentence(emptyList()))
    }

    @Test
    fun `the clean lead is said only when the measurement backs it`() {
        fun bar(score: Int?, faulted: Boolean) = RepBar(0, score, faulted, null)
        assertEquals(
            "Las 2 primeras están limpias.",
            leadingCleanSentence(listOf(bar(80, false), bar(75, false), bar(51, true))),
        )
        assertEquals(
            "La primera está limpia.",
            leadingCleanSentence(listOf(bar(80, false), bar(51, true))),
        )
        assertNull("a faulted first rep has no clean lead",
            leadingCleanSentence(listOf(bar(51, true), bar(80, false))))
        assertEquals(
            "the sentence only counts measured-clean reps, so it stays true " +
                "when an unmeasured one follows",
            "La primera está limpia.",
            leadingCleanSentence(listOf(bar(80, false), bar(null, false), bar(51, true))),
        )
        assertNull("an all-clean set needs no sentence",
            leadingCleanSentence(listOf(bar(80, false), bar(75, false))))
    }

    // ---- the note -----------------------------------------------------------

    @Test
    fun `the comparison line exists only when there is something to compare`() {
        assertNull(versusAverageLine(null, null, "Dominada"))
        assertEquals("+4 respecto a tu media de dominada",
            versusAverageLine(4, null, "Dominada"))
        assertEquals("-3 respecto a tu media de dominada",
            versusAverageLine(-3, null, "Dominada"))
        assertEquals("En tu media de dominada",
            versusAverageLine(0, null, "Dominada"))
        assertEquals("Por encima de tu media de dominada",
            versusAverageLine(null, true, "Dominada"))
        assertEquals("Algo por debajo de tu media de dominada",
            versusAverageLine(null, false, "Dominada"))
    }

    // ---- the clock ----------------------------------------------------------

    @Test
    fun `the clip clock is minutes seconds`() {
        assertEquals("0:00", clockMmSs(0.0))
        assertEquals("0:24", clockMmSs(24.0))
        assertEquals("1:15", clockMmSs(75.7))
        assertEquals("0:00", clockMmSs(-2.0))
    }

    @Test
    fun `timeline and full-clip labels carry the length when known`() {
        assertEquals("Línea de tiempo", timelineLabel(null))
        assertEquals("Línea de tiempo · 0:24", timelineLabel(analysis()))
        assertEquals("Ver vídeo completo", fullClipLabel(null))
        assertEquals("Ver vídeo completo · 0:24", fullClipLabel(analysis()))
    }

    // ---- the header ---------------------------------------------------------

    @Test
    fun `the header names the movement the set and when`() {
        assertEquals("Dominada · Serie 1",
            resultsHeaderTitle(results(seriesLabel = "Serie 1")))
        assertEquals("Dominada", resultsHeaderTitle(results()))
        assertEquals("Hoy 18:42 · 6 reps",
            resultsHeaderMeta(results(whenLabel = "Hoy 18:42")))
        assertEquals("6 reps", resultsHeaderMeta(results()))
    }

    // ---- the fault thumbnails ----------------------------------------------

    @Test
    fun `thumbnails come from the ranked fixes and their rep`() {
        val thumbs = faultThumbs(
            results(fixes = listOf(
                FixItem("Balanceo al subir", null, "en 3 de 6 repeticiones", repIndex = 3),
                FixItem("Codos abiertos", null, "en 2 de 6 repeticiones", repIndex = null),
            )),
            analysis(rep(null), rep(null), rep(null), rep(null, startS = 13.5)),
        )
        assertEquals(2, thumbs.size)
        assertEquals("Balanceo al subir", thumbs[0].title)
        assertEquals(4, thumbs[0].repNumber)
        assertEquals("0:13", thumbs[0].timeLabel)
        assertEquals(0, thumbs[0].openIndex)
        assertEquals("Codos abiertos", thumbs[1].title)
        assertNull(thumbs[1].repNumber)
        assertNull(thumbs[1].timeLabel)
        assertEquals(1, thumbs[1].openIndex)
    }

    @Test
    fun `without fixes the fault list itself stands in`() {
        val thumbs = faultThumbs(
            results(faults = listOf("Balanceo" to 4, "Codos" to 2)),
            null,
        )
        assertEquals(listOf("Balanceo", "Codos"), thumbs.map { it.title })
        assertNull(thumbs[0].repNumber)
        assertEquals(0, thumbs[0].openIndex)
        assertEquals(1, thumbs[1].openIndex)
    }

    @Test
    fun `no more than three thumbnails`() {
        val thumbs = faultThumbs(
            results(faults = listOf("a" to 4, "b" to 3, "c" to 2, "d" to 1)),
            null,
        )
        assertEquals(3, thumbs.size)
    }
}
