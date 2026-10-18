package com.barrapp.ui.tracker

import com.barrapp.data.Analysis
import com.barrapp.data.MeasuredFault
import com.barrapp.data.RepRow
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The correction screen's pure side: the worst rep of each fault against the
 * set's best rep, and when no honest comparison exists. No Android here.
 */
class RepCorrectionTest {
    private fun fault(
        name: String,
        value: Double? = null,
        threshold: Double = 0.0,
        comparison: String = "",
        unit: String = "",
        errorId: String = "",
        intervalS: List<Double> = emptyList(),
    ) = MeasuredFault(
        name, value = value, threshold = threshold, comparison = comparison,
        unit = unit, errorId = errorId, intervalS = intervalS,
    )

    private fun rep(
        vararg faults: MeasuredFault,
        score: Int? = null,
        turnS: Double = 0.0,
        startS: Double = 0.0,
    ) = RepRow(
        session = "s", label = "pull_up", transitionS = "", totalS = "", cls = "rep",
        startS = startS, endS = startS + 2.0, turnS = turnS, score = score,
        faults = faults.toList(),
    )

    private fun analysis(vararg reps: RepRow) = Analysis(
        headline = "", narrative = "", sessions = emptyList(), reps = reps.toList(),
        blockers = emptyList(), nextSession = "", exercise = "pull_up",
    )

    private val swing = { v: Double, interval: List<Double> ->
        fault("momentum", v, 0.2, ">", "torso",
            errorId = "pull_up.body_swing", intervalS = interval)
    }

    @Test fun `the worst rep of a fault is set against the best rep of the set`() {
        val a = analysis(
            rep(swing(0.1, listOf(1.0, 1.2)), score = 80, turnS = 1.1),
            rep(score = 75),
            rep(swing(0.45, listOf(5.0, 5.4)), score = 52, turnS = 5.2),
        )
        val corrections = repCorrections(a)
        assertEquals(1, corrections.size)
        val c = corrections[0]
        assertEquals(3, c.rep)
        assertEquals(1, c.bestRep)
        assertEquals(5.2, c.atS, 1e-9)
        assertEquals(1.1, c.bestAtS, 1e-9)
        assertEquals("0.45 torsos", c.value)
        assertEquals("0.1 torsos", c.bestValue)
        assertEquals("OBJETIVO MENOS DE 0.2 torsos", c.goal)
        assertEquals("BALANCEO", c.title)
        assertTrue(
            "the why compares with your own best rep",
            c.why.endsWith("En tu mejor rep (la 1) se midió 0.1 torsos."),
        )
        assertEquals(0, c.index)
        assertEquals(1, c.total)
    }

    @Test fun `no comparison when the best rep never measured the fault`() {
        val a = analysis(
            rep(score = 80, turnS = 2.5),
            rep(swing(0.5, listOf(4.0, 4.2)), score = 60, turnS = 4.1),
        )
        val c = repCorrections(a).single()
        assertEquals(2, c.rep)
        assertEquals(1, c.bestRep)
        assertNull(c.bestValue)
        // The best frame still shows the best rep, at its own turnaround.
        assertEquals(2.5, c.bestAtS, 1e-9)
        assertTrue(!c.why.contains("mejor rep"))
    }

    @Test fun `no comparison when the worst rep is the best rep`() {
        val a = analysis(
            rep(swing(0.5, listOf(2.0, 2.4)), score = 60, turnS = 2.2),
        )
        val c = repCorrections(a).single()
        assertEquals(1, c.rep)
        assertEquals(1, c.bestRep)
        assertNull(c.bestValue)
        assertEquals(c.atS, c.bestAtS, 1e-9)
    }

    @Test fun `an unmeasured set has no best rep to compare with`() {
        val a = analysis(
            rep(swing(0.5, listOf(2.0, 2.4)), turnS = 2.2),
            rep(turnS = 5.0),
        )
        val c = repCorrections(a).single()
        assertEquals(1, c.rep)
        assertEquals(1, c.bestRep)
        assertNull(c.bestValue)
    }

    @Test fun `corrections come worst first and stop at three`() {
        val a = analysis(
            rep(fault("momentum", 0.3, 0.2, ">", "torso", errorId = "m.body_swing"),
                score = 50, turnS = 1.0),
            rep(fault("lockout", 76.0, 85.0, "<", "% of reach", errorId = "m.incomplete_lockout"),
                score = 51, turnS = 2.0),
            rep(fault("fast descent", 0.5, 0.35, ">", "s", errorId = "m.dropped_descent"),
                score = 52, turnS = 3.0),
            rep(fault("stall", 1.4, 1.0, ">=", "s", errorId = "m.lift_stall"),
                score = 53, turnS = 4.0),
            rep(fault("too fast", 0.6, 0.75, "<", "s", errorId = "m.fast_lift"),
                score = 54, turnS = 5.0),
        )
        val corrections = repCorrections(a)
        assertEquals(3, corrections.size)
        assertEquals(listOf("BALANCEO", "BAJADA RÁPIDA", "ESTANCAMIENTO A MEDIO TIRÓN"),
            corrections.map { it.title })
        assertEquals(listOf(0 to 3, 1 to 3, 2 to 3), corrections.map { it.index to it.total })
    }

    @Test fun `the cue and the fallback say what to try next`() {
        val a = analysis(rep(swing(0.5, listOf(2.0, 2.4)), score = 60))
        assertEquals(
            com.barrapp.cueEs("momentum"),
            repCorrections(a).single().cue,
        )
        val unknown = analysis(
            rep(fault("some brand new fault", 1.0, 0.5, ">", "s"), score = 60),
        )
        assertEquals(FALLBACK_CUE, repCorrections(unknown).single().cue)
    }

    @Test fun `a fault without a number reads as unmeasured, never as zero`() {
        val a = analysis(rep(fault("momentum", null, 0.2, ">", "torso"), score = 60))
        val c = repCorrections(a).single()
        assertEquals("—", c.value)
        assertNull(c.bestValue)
    }
}
