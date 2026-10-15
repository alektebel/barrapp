package com.barrapp.ui.replay

import com.barrapp.data.Analysis
import com.barrapp.data.MeasuredFault
import com.barrapp.data.RepRow
import com.barrapp.data.Trim
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ReplayTimelineTest {
    private fun rep(i: Int, start: Double, end: Double, fault: String? = null, value: Double = 0.0) =
        ReplayRep(i, start, end, (start + end) / 2, fault?.let { "F-$it" },
            listOfNotNull(fault), fault?.let { mapOf(it to value) } ?: emptyMap(),
            measured = true, band = "solid", outlier = false)

    // Three reps, a 4 s rest, two more: the shape of a set with a breather.
    private val plan = ReplayPlan(
        listOf(rep(0, 1.0, 2.0), rep(1, 2.0, 3.0, "momentum", 0.2), rep(2, 3.0, 4.0),
            rep(3, 8.0, 9.0, "momentum", 0.9), rep(4, 9.0, 10.0)),
        windowStart = 0.5, windowEnd = 10.5,
    )

    @Test fun `the counter rises as each rep ends, never before`() {
        assertEquals(0, plan.repsDoneBy(1.99))
        assertEquals(1, plan.repsDoneBy(2.0))
        assertEquals(3, plan.repsDoneBy(6.0))
        assertEquals(5, plan.repsDoneBy(10.5))
    }

    @Test fun `the active rep is the one being performed, none during the rest`() {
        assertEquals(1, plan.activeRepAt(2.5)?.index)
        assertNull(plan.activeRepAt(6.0))
    }

    @Test fun `a verdict holds after its rep and gives way to the next`() {
        assertEquals(0, plan.verdictAt(2.1)?.index)
        assertEquals(1, plan.verdictAt(3.1)?.index)   // rep 2 ended at 3.0
        assertEquals(2, plan.verdictAt(5.4)?.index)
        assertNull(plan.verdictAt(5.6))
    }

    @Test fun `compact mode keeps the reps and skips the rest`() {
        val segments = plan.compactSegments()
        assertEquals(2, segments.size)
        assertEquals(0.7, segments[0].start, 1e-9)
        assertEquals(4.3, segments[0].endInclusive, 1e-9)
        assertEquals(7.7, segments[1].start, 1e-9)
        assertNull(plan.compactJump(3.5))
        assertEquals(7.7, plan.compactJump(5.0)!!, 1e-9)
        assertTrue(plan.compactJump(10.4)!!.isNaN())
        assertTrue(plan.compactByDefault)   // 10 s window, ~3.6 s of rest
    }

    @Test fun `an unbroken set is not compacted by default`() {
        val even = ReplayPlan(listOf(rep(0, 1.0, 2.0), rep(1, 2.0, 3.0)), 0.7, 3.3)
        assertFalse(even.compactByDefault)
    }

    @Test fun `guided review stops once at each faulted turnaround`() {
        assertEquals(1, plan.guidedStop(2.5, emptySet())?.index)
        assertNull(plan.guidedStop(2.5, setOf(1)))
        assertNull(plan.guidedStop(1.5, emptySet()))      // rep 0 is clean
        assertEquals(setOf(0, 1, 2), plan.reviewedBy(3.6))
    }

    @Test fun `see it in rep N picks the worst rep for that fault`() {
        assertEquals(3, plan.worstRepFor("momentum")?.index)
        assertNull(plan.worstRepFor("lockout"))
    }

    @Test fun `reps outside the window are not scheduled`() {
        val p = ReplayPlan(listOf(rep(0, 0.0, 0.4), rep(1, 1.0, 2.0)), 0.5, 3.0)
        assertEquals(1, p.total)
    }

    @Test fun `the window is the trim, then the active spans, then the clip`() {
        val reps = listOf(RepRow("d", "r1", "", "", "", startS = 2.0, endS = 3.0))
        val base = Analysis("", "", emptyList(), reps, emptyList(), "")
        assertEquals(0.0, ReplayPlan.from(base, 12.0).windowStart, 1e-9)
        assertEquals(12.0, ReplayPlan.from(base, 12.0).windowEnd, 1e-9)
        val spans = base.copy(activeSpans = listOf(Trim(1.0, 4.0), Trim(6.0, 9.0)))
        assertEquals(1.0, ReplayPlan.from(spans, 12.0).windowStart, 1e-9)
        assertEquals(9.0, ReplayPlan.from(spans, 12.0).windowEnd, 1e-9)
        val trimmed = spans.copy(trim = Trim(1.4, 3.6))
        assertEquals(1.4, ReplayPlan.from(trimmed, 12.0).windowStart, 1e-9)
        assertEquals(3.6, ReplayPlan.from(trimmed, 12.0).windowEnd, 1e-9)
    }

    @Test fun `exceedance mirrors the server for both comparison directions`() {
        assertEquals(0.5, ReplayPlan.exceedance(MeasuredFault("x", value = 1.5, threshold = 1.0, comparison = ">")), 1e-4)
        assertEquals(0.25, ReplayPlan.exceedance(MeasuredFault("x", value = 0.75, threshold = 1.0, comparison = "<")), 1e-4)
    }

    @Test fun `consistency reads as a sentence, or not at all`() {
        val base = Analysis("", "", emptyList(), emptyList(), emptyList(), "")
        assertNull(consistencyLine(base))
        assertEquals("Serie estable — Ritmo ±12 % · Recorrido ±13 %",
            consistencyLine(base.copy(tempoCV = 0.125, amplitudeCV = 0.132, consistencyBand = "estable")))
    }
}

class ShapeNoteTest {
    @Test fun `an outlier is described by what moved and how much`() {
        assertEquals("Recorrido un 52 % mayor y un 57 % más lenta que tu rep media.",
            ReplayPlan.shapeNote(0.517, 0.57))
        assertEquals("Un 30 % más rápida que tu rep media.", ReplayPlan.shapeNote(0.05, -0.30))
        assertNull(ReplayPlan.shapeNote(0.1, 0.1))
        assertNull(ReplayPlan.shapeNote(null, null))
    }
}
