package com.barrapp.ui.tracker

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TrackerResultRenderTest {
    @Test fun `marks the visible results phase for the matching completed job`() {
        assertTrue(shouldMarkResultRendered(
            RecordPhase.RESULTS, true, "job-1", "trace-1", "trace-1"))
    }

    @Test fun `does not mark analyzing idle incomplete or unrelated content`() {
        assertFalse(shouldMarkResultRendered(
            RecordPhase.ANALYZING, true, "job-1", "trace-1", "trace-1"))
        assertFalse(shouldMarkResultRendered(
            RecordPhase.RESULTS, false, "job-1", "trace-1", "trace-1"))
        assertFalse(shouldMarkResultRendered(
            RecordPhase.RESULTS, true, null, "trace-1", "trace-1"))
        assertFalse(shouldMarkResultRendered(
            RecordPhase.RESULTS, true, "job-1", "trace-1", "trace-2"))
        assertFalse(shouldMarkResultRendered(
            RecordPhase.RESULTS, true, "job-1", "", ""))
    }
}
