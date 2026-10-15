package com.barrapp

import com.barrapp.resultPollDelayMs
import org.junit.Assert.assertEquals
import org.junit.Test

class ResultPollingTest {
    @Test fun `polls rapidly during the Round 2 latency window`() {
        assertEquals(250L, resultPollDelayMs(0L))
        assertEquals(250L, resultPollDelayMs(14_999L))
    }

    @Test fun `returns to the normal cadence after the latency window`() {
        assertEquals(1000L, resultPollDelayMs(15_000L))
        assertEquals(1000L, resultPollDelayMs(60_000L))
    }
}
