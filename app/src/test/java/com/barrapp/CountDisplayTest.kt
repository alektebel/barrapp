package com.barrapp.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class CountDisplayTest {
    @Test fun `vision counts are described as estimates from frames`() {
        assertEquals("5 reps estimated from frames", countSummary("vision", 5, 0))
    }

    @Test fun `unmeasured is distinct from a measured zero`() {
        assertEquals("Rep count unavailable", countSummary("unmeasured", 0, 0))
    }

    @Test fun `geometric count retains its candidate context`() {
        assertEquals("0 reps measured of 2 found", countSummary("geometry", 0, 2))
    }

    @Test fun `holds are not labeled as repetition counts`() {
        assertEquals("2 hold attempts measured", countSummary("hold", 2, 2))
    }
}
