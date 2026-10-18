package com.barrapp.ui.tracker

import java.time.LocalDate
import org.junit.Assert.assertEquals
import org.junit.Test

class TrackerRootWiringTest {
    private fun slide(rep: Int, title: String) = FaultSlide(
        rep = rep, atS = rep.toDouble(), title = title, short = title, value = "", goal = "",
        why = "", cue = "", region = BodyRegion.FULL,
    )

    @Test
    fun `the viewer opens on the fault the results list in that position`() {
        val slides = listOf(slide(5, "CODOS ABIERTOS"), slide(4, "BALANCEO"), slide(6, "RECORRIDO"))
        val fixes = listOf(
            FixItem("Balanceo", null, "", repIndex = 3),
            FixItem("Recorrido", null, "", repIndex = 5),
        )
        val ordered = slidesInFixOrder(slides, fixes)
        assertEquals(listOf("BALANCEO", "RECORRIDO", "CODOS ABIERTOS"), ordered.map { it.title })
    }

    @Test
    fun `a fix with no title match falls back to its rep and nothing repeats`() {
        val slides = listOf(slide(2, "A"), slide(3, "B"))
        val fixes = listOf(FixItem("otro nombre", null, "", repIndex = 2), FixItem("B", null, "", 2))
        assertEquals(listOf("B"), slidesInFixOrder(slides, fixes).map { it.title }.take(1))
        assertEquals(2, slidesInFixOrder(slides, fixes).size)
    }

    @Test
    fun `times read as today, yesterday or a short date`() {
        val today = LocalDate.of(2026, 10, 18)
        assertEquals("Hoy 18:42", whenEs("2026-10-18T18:42:10", today))
        assertEquals("Ayer 07:05", whenEs("2026-10-17T07:05:00", today))
        assertEquals("", whenEs("no es una fecha", today))
    }
}
