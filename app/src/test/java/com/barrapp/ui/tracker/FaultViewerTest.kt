package com.barrapp.ui.tracker

import com.barrapp.cueEs
import com.barrapp.data.Analysis
import com.barrapp.data.MeasuredFault
import com.barrapp.data.RepRow
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The fault viewer's pure side: the slides built from a measured set, the
 * story's wrap-around, the zoom per body region and the number formatting.
 * No Android here — the composables render nothing in these tests.
 */
class FaultViewerTest {
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

    @Test fun `regionFor zooms by the words of the rule id`() {
        assertEquals(BodyRegion.UPPER, regionFor("muscle_up.incomplete_lockout"))
        assertEquals(BodyRegion.UPPER, regionFor("pull_up.elbow_flare"))
        assertEquals(BodyRegion.UPPER, regionFor("incompleteLockout"))   // camelCase
        assertEquals(BodyRegion.MIDDLE, regionFor("pull_up.body_swing"))
        assertEquals(BodyRegion.MIDDLE, regionFor("push_up.hip_sag"))
        assertEquals(BodyRegion.LOWER, regionFor("squat.knee_medial_drift"))
        assertEquals(BodyRegion.LOWER, regionFor("squat.shallow_depth"))
        assertEquals(BodyRegion.FULL, regionFor("muscle_up.slow_transition"))
        assertEquals(BodyRegion.FULL, regionFor(""))
    }

    @Test fun `faultSlides tell the measured faults with value goal and region`() {
        val a = analysis(
            rep(score = 70),
            rep(fault("lockout", 76.0, 85.0, "<", "% of reach",
                errorId = "pull_up.incomplete_lockout", intervalS = listOf(3.0, 3.4)), score = 61, turnS = 3.2),
            rep(score = 66),
            rep(fault("momentum", 0.3, 0.2, ">", "torso",
                errorId = "pull_up.body_swing", intervalS = listOf(6.0, 6.4)), score = 52, turnS = 6.2),
        )
        val slides = faultSlides(a)
        assertEquals(2, slides.size)
        // The swing went further past its threshold than the lockout, so it leads.
        assertEquals("BALANCEO", slides[0].title)
        assertEquals(4, slides[0].rep)
        assertEquals(6.2, slides[0].atS, 1e-9)
        assertEquals("0.3 torsos", slides[0].value)
        assertEquals("OBJETIVO MENOS DE 0.2 torsos", slides[0].goal)
        assertEquals(BodyRegion.MIDDLE, slides[0].region)
        assertEquals(cueEs("momentum"), slides[0].cue)
        assertEquals("SIN BLOQUEO ARRIBA", slides[1].title)
        assertEquals("BLOQUEO", slides[1].short)
        assertEquals("76%", slides[1].value)
        assertEquals("OBJETIVO MÁS DE 85%", slides[1].goal)
        assertEquals(BodyRegion.UPPER, slides[1].region)
    }

    @Test fun `a fault that fired on several reps collapses into its worst one`() {
        val a = analysis(
            rep(fault("momentum", 0.25, 0.2, ">", "torso",
                errorId = "pull_up.body_swing", intervalS = listOf(1.0, 1.2)), turnS = 1.1),
            rep(score = 70),
            rep(fault("momentum", 0.45, 0.2, ">", "torso",
                errorId = "pull_up.body_swing", intervalS = listOf(5.0, 5.4)), turnS = 5.2),
        )
        val slides = faultSlides(a)
        assertEquals(1, slides.size)
        assertEquals(3, slides[0].rep)
        assertEquals(5.2, slides[0].atS, 1e-9)
    }

    @Test fun `at most three slides, worst excess first`() {
        val a = analysis(
            rep(fault("momentum", 0.3, 0.2, ">", "torso", errorId = "m.body_swing"), turnS = 1.0),
            rep(fault("lockout", 76.0, 85.0, "<", "% of reach", errorId = "m.incomplete_lockout"), turnS = 2.0),
            rep(fault("fast descent", 0.5, 0.35, ">", "s", errorId = "m.dropped_descent"), turnS = 3.0),
            rep(fault("stall", 1.4, 1.0, ">=", "s", errorId = "m.lift_stall"), turnS = 4.0),
            rep(fault("too fast", 0.6, 0.75, "<", "s", errorId = "m.fast_lift"), turnS = 5.0),
        )
        val slides = faultSlides(a)
        assertEquals(3, slides.size)
        assertEquals(listOf("BALANCEO", "BAJADA RÁPIDA", "ESTANCAMIENTO A MEDIO TIRÓN"),
            slides.map { it.title })
    }

    @Test fun `same fault name but different movements are different slides`() {
        val a = analysis(
            rep(fault("momentum", 0.3, 0.2, ">", "torso", errorId = "pull_up.body_swing")),
            rep(fault("momentum", 0.3, 0.2, ">", "torso", errorId = "front_lever.body_swing")),
        )
        assertEquals(2, faultSlides(a).size)
    }

    @Test fun `atS falls back to the turnaround and then to the rep start`() {
        val withTurn = rep(fault("momentum", 0.3, 0.2, ">", "torso"), turnS = 7.0)
        assertEquals(7.0, faultMoment(withTurn, withTurn.faults[0]), 1e-9)
        val fromStart = rep(fault("momentum", 0.3, 0.2, ">", "torso"), startS = 9.0)
        assertEquals(9.0, faultMoment(fromStart, fromStart.faults[0]), 1e-9)
    }

    @Test fun `a fault without a number reads as unmeasured, never as zero`() {
        val a = rep(fault("momentum", null, 0.2, ">", "torso"))
        val slide = faultSlides(analysis(a)).single()
        assertEquals("—", slide.value)
    }

    @Test fun `the story wraps around`() {
        assertEquals(1, nextSlide(0, 3))
        assertEquals(0, nextSlide(2, 3))
        assertEquals(2, prevSlide(0, 3))
        assertEquals(0, prevSlide(1, 3))
        assertEquals(0, nextSlide(0, 0))
        assertEquals(0, prevSlide(0, 0))
    }

    @Test fun `the zoom lands on the failing region`() {
        val upper = zoomTarget(BodyRegion.UPPER)
        assertEquals(1.6f, upper.scale)
        assertEquals(0.5f, upper.x)
        assertTrue("upper zooms near the top", upper.y < 0.3f)
        assertTrue("lower zooms near the bottom", zoomTarget(BodyRegion.LOWER).y > 0.7f)
        assertTrue("middle stays centred",
            zoomTarget(BodyRegion.MIDDLE).y in 0.4f..0.6f)
        assertTrue("full frame zooms less than a region", zoomTarget(BodyRegion.FULL).scale < 1.6f)
    }

    @Test fun `measured numbers are said the way the design writes them`() {
        assertEquals("19°", fmtValue(19.0, "deg"))
        assertEquals("0.3 torsos", fmtValue(0.3, "torso"))
        assertEquals("0.45 torsos", fmtValue(0.45, "torso"))
        assertEquals("76%", fmtValue(76.0, "% of reach"))
        assertEquals("5.5°", fmtValue(5.5, "deg"))
        assertEquals("8", fmtValue(8.0, ""))
    }

    @Test fun `the goal points the way the comparison says`() {
        // Fires above the threshold (swing 19° > 8°): the goal is to stay under.
        assertEquals("OBJETIVO MENOS DE 8°", goalText(8.0, ">", "deg"))
        assertEquals("OBJETIVO MENOS DE 1", goalText(1.0, "", ""))
        // Fires below it (lockout 76% < 85%): the goal is to get above.
        assertEquals("OBJETIVO MÁS DE 85%", goalText(85.0, "<", "% of reach"))
    }

    @Test fun `the short name is the one word a header can hold`() {
        assertEquals("BALANCEO", shortFault("Balanceo"))
        assertEquals("BLOQUEO", shortFault("Sin bloqueo arriba"))
        assertEquals("PROFUNDO", shortFault("Demasiado profundo"))
        assertEquals("RECORRIDO", shortFault("Recorrido incompleto"))
    }

    @Test fun `the why sentence says the number and the limit, nothing invented`() {
        val why = faultWhy("momentum", 0.3, 0.2, ">", "torso", 4)
        assertEquals("Balanceo: 0.3 torsos frente al máximo de 0.2 torsos.", why)
        assertEquals(
            "Sin bloqueo arriba: 76% frente al mínimo de 85%.",
            faultWhy("lockout", 76.0, 85.0, "<", "% of reach", 2),
        )
        assertEquals("Balanceo, medido en la rep 4.", faultWhy("momentum", null, 0.2, ">", "torso", 4))
    }

    @Test fun `video seconds read as clocks`() {
        assertEquals("0:14", clockLabel(14.0))
        assertEquals("1:01", clockLabel(61.0))
        assertEquals("0:00", clockLabel(-3.0))
    }

    @Test fun `the header names the fault and the movement`() {
        assertEquals("FALLO 2 DE 3", headerLabel(3, 1, ""))
        assertEquals("FALLO 1 DE 3 · DOMINADA", headerLabel(3, 0, "pull_up"))
    }
}
