package com.barrapp

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.barrapp.data.Round2TimingStore
import com.barrapp.data.monotonicDurationMs
import android.os.SystemClock
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertNotNull
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.json.JSONArray
import java.io.File
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class Round2TimingTest {
    @Test fun sameBootUsesMonotonicDifference() {
        assertEquals(1500L, monotonicDurationMs(1_000_000_000L, 2_500_000_000L,
            "boot-a", "boot-a"))
    }

    @Test fun rebootMakesDurationUnavailable() {
        assertNull(monotonicDurationMs(1_000_000_000L, 2_500_000_000L,
            "boot-a", "boot-b"))
    }

    @Test fun missingBootIdMakesDurationUnavailable() {
        assertNull(monotonicDurationMs(1L, 2_000_001L, "", ""))
    }

    @Test fun resumedLegacyAttemptWithoutOriginalStartIsNotCounted() {
        assertNull(monotonicDurationMs(1_000_000_000L, 2_500_000_000L,
            "boot-a", "boot-a", completeOrigin = false))
    }

    @Test fun negativeMonotonicIntervalMakesDurationUnavailable() {
        assertNull(monotonicDurationMs(2_000_000_000L, 1_000_000_000L,
            "boot-a", "boot-a"))
    }

    @Test fun `render event persists and is idempotent per job`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val timingFile = File(context.filesDir, "round2-timings.json")
        timingFile.delete()
        val attemptId = UUID.randomUUID().toString()
        Round2TimingStore.begin(context, attemptId)
        Round2TimingStore.begin(context, attemptId)
        Round2TimingStore.bindJob(context, attemptId, "job-1")
        Round2TimingStore.resultReceived(context, attemptId, "trace-1",
            countStatus = "vision", repCount = 5,
            pollCount = 7, pollGetMs = 123, pollSleepMs = 1_230,
            pollHandleMs = 45)

        val first = Round2TimingStore.rendered(context, "job-1", "trace-1", 100L)
        val repeated = Round2TimingStore.rendered(context, "job-1", "trace-1", 200L)
        assertNotNull(first)
        assertEquals(100L, first!!.renderedNs)
        assertEquals(100L, repeated!!.renderedNs)
        assertEquals(attemptId, repeated.attemptId)
        assertEquals("vision", repeated.countStatus)
        assertEquals(5, repeated.repCount)
        assertEquals(7, repeated.pollCount)
        assertEquals(123L, repeated.phaseMs["pollGet"])
        assertEquals(1_230L, repeated.phaseMs["pollSleep"])
        assertEquals(45L, repeated.phaseMs["pollHandle"])
        timingFile.delete()
    }

    @Test fun `preparation export and confirmation data survive until render`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val timingFile = File(context.filesDir, "round2-timings.json")
        timingFile.delete()
        val attemptId = UUID.randomUUID().toString()
        val confirmedNs = SystemClock.elapsedRealtimeNanos()
        Round2TimingStore.preparationDuration(context, attemptId, 321L)
        Round2TimingStore.trimExportDuration(context, attemptId, 654L)
        Round2TimingStore.trimVideoBitrate(context, attemptId, 3_700_000)
        Round2TimingStore.phaseDuration(context, attemptId, "presign", 120L)
        Round2TimingStore.phaseDuration(context, attemptId, "presign", 80L)
        Round2TimingStore.phaseDuration(context, attemptId, "partTransfer", 430L)
        Round2TimingStore.trimConfirmed(context, attemptId, confirmedNs)
        Round2TimingStore.begin(context, attemptId)
        Round2TimingStore.bindJob(context, attemptId, "job-prep")
        Round2TimingStore.resultReceived(context, attemptId, "trace-prep")

        val rendered = Round2TimingStore.rendered(context, "job-prep", "trace-prep")!!
        assertEquals(321L, rendered.preparationMs)
        assertEquals(654L, rendered.trimExportMs)
        assertEquals(3_700_000L, rendered.trimVideoBitrateBps)
        assertEquals(confirmedNs, rendered.trimConfirmedNs)
        assertEquals(rendered.bootId, rendered.trimConfirmedBootId)
        assertEquals(200L, rendered.phaseMs["presign"])
        assertEquals(430L, rendered.phaseMs["partTransfer"])
        timingFile.delete()
    }

    @Test fun `source and prepared byte counts survive render and resume`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val timingFile = File(context.filesDir, "round2-timings.json")
        timingFile.delete()
        val attemptId = UUID.randomUUID().toString()
        Round2TimingStore.clipBytes(context, attemptId, 10_000L, 2_000L)
        Round2TimingStore.begin(context, attemptId)
        // A resumed attempt must retain its original source size while the
        // prepared size reflects the file that is actually uploaded.
        Round2TimingStore.clipBytes(context, attemptId, 2_000L, 2_000L)
        Round2TimingStore.bindJob(context, attemptId, "job-bytes")
        Round2TimingStore.resultReceived(context, attemptId, "trace-bytes")
        val rendered = Round2TimingStore.rendered(context, "job-bytes", "trace-bytes")!!
        assertEquals(10_000L, rendered.sourceBytes)
        assertEquals(2_000L, rendered.preparedBytes)
        timingFile.delete()
    }

    @Test fun `legacy rows remain incomparable for poll count`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val timingFile = File(context.filesDir, "round2-timings.json")
        timingFile.writeText("""[{"attemptId":"legacy","bootId":"boot","startedNs":1}]""")

        Round2TimingStore.begin(context, "legacy")

        assertEquals(null, JSONArray(timingFile.readText()).getJSONObject(0).opt("pollCount"))
        timingFile.delete()
    }
}
