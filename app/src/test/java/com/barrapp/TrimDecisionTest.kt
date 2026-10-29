package com.barrapp

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.barrapp.data.TrimPlan
import com.barrapp.data.TrimSuggestion
import com.barrapp.data.WorkStore
import com.barrapp.media.ClipTrimmer
import com.barrapp.media.MotionSamplerPlan
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.json.JSONArray
import java.io.File

/**
 * La decisión de recorte, con un [ClipTrimmer] falso: cuándo se recorta,
 * cuándo se sube el original y qué pasa con un reintento tras un fallo del
 * transcodificador. La vía real del Transformer necesita un dispositivo —
 * no se finge aquí.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class TrimDecisionTest {

    @Test
    fun `motion scan samples a 30 second clip at one second intervals`() {
        assertEquals((1..29).map(Int::toDouble), MotionSamplerPlan.timestamps(30.0).toList())
    }

    @Test
    fun `motion scan skips invalid and sub-second durations`() {
        assertTrue(MotionSamplerPlan.timestamps(0.75).none())
        assertTrue(MotionSamplerPlan.timestamps(0.0).none())
        assertTrue(MotionSamplerPlan.timestamps(Double.NaN).none())
        assertEquals(listOf(1.0), MotionSamplerPlan.timestamps(1.01).toList())
    }

    @Test
    fun `coarse WA0020 window is declined while short window would crop`() {
        assertFalse(TrimPlan.shouldTrim(TrimSuggestion(1.0, 19.0, 20.0), 20.0))
        assertTrue(TrimPlan.shouldTrim(TrimSuggestion(0.5, 12.5, 20.0), 20.0))
    }

    /**
     * WA0014 at the phone's 1 Hz cadence (an OpenCV mirror of the sampler).
     * The loudest steady stretch, 2-7 s, is the walk to the bar; the set is
     * not distinguishable from it by pixel motion alone. Nobody confirms the
     * cut any more, so the plan keeps every substantial run: here that is the
     * approach AND the walk away, i.e. the whole clip, and the clip goes up
     * untrimmed. Losing a rep costs more than uploading a few seconds extra.
     */
    @Test
    fun `an ambiguous clip keeps every run and uploads whole`() {
        val scores = listOf(44, 50, 43, 49, 51, 27, 12, 10, 4, 3, 3, 4, 8, 4, 2, 3, 5, 1, 1,
            1, 1, 7, 9, 4, 8, 5, 2, 2, 2, 1, 4, 4, 4, 7, 10, 39, 26, 64, 99)
        // The 1 s frame only seeds the difference: the first sample is at 2 s.
        val samples = scores.mapIndexed { i, v -> com.barrapp.data.MotionSample(i + 2.0, v.toDouble()) }
        val s = TrimPlan.suggest(samples, 40.4)!!
        assertEquals(0.0, s.startS, 1e-9)
        assertEquals(40.4, s.endS, 1e-9)
        assertFalse(TrimPlan.shouldTrim(s, 40.4))
    }

    private class FakeTrimmer(
        private val fail: Boolean = false,
    ) : ClipTrimmer {
        var exports = 0
        var lastWindow: Pair<Double, Double>? = null
        override suspend fun export(src: File, dst: File, startS: Double, endS: Double): Int? {
            exports++
            lastWindow = startS to endS
            if (fail) throw RuntimeException("no such codec")
            dst.parentFile?.mkdirs()
            dst.writeBytes(ByteArray(10))
            return 3_700_000
        }
    }

    private lateinit var vm: BarrappViewModel

    @Before
    fun setUp() {
        val app = ApplicationProvider.getApplicationContext<Context>()
        // Cada prueba tiene su tienda: el works.json de una anterior no
        // puede contaminar la siguiente.
        File(app.filesDir, "works.json").delete()
        File(app.filesDir, "round2-timings.json").delete()
        vm = BarrappViewModel(app as android.app.Application)
    }

    @Test
    fun `a confirmed window exports the cut and keeps the original safe`() =
        kotlinx.coroutines.test.runTest {
            val app = ApplicationProvider.getApplicationContext<Context>()
            val clip = File(app.filesDir, "clips/w1.mp4")
            clip.parentFile?.mkdirs()
            clip.writeBytes(ByteArray(100))
            val fake = FakeTrimmer()
            vm.trimmer = fake
            WorkStore.put(app, com.barrapp.data.Work(
                id = "w1", createdAt = 0, status = WorkStore.STATUS_WAITING,
                clipPath = clip.absolutePath,
                trimmed = true, trimStartS = 14.0, trimEndS = 22.0,
            ))
            val work = WorkStore.get(app, "w1")!!
            val out = vm.trimForUpload(work, clip)
            assertEquals(1, fake.exports)
            assertEquals(14.0 to 22.0, fake.lastWindow)
            // El fichero que viaja es el recortado, y el work apunta a él.
            assertTrue(out.name.endsWith("-trim.mp4"))
            val saved = WorkStore.get(app, "w1")!!
            assertEquals(out.absolutePath, saved.clipPath)
            assertFalse(saved.trimmed)
            assertEquals(0.0, saved.trimStartS, 0.0)
            assertEquals(0.0, saved.trimEndS, 0.0)
            assertTrue(out.exists())
            val timing = JSONArray(File(app.filesDir, "round2-timings.json").readText())
                .getJSONObject(0)
            assertEquals(3_700_000L, timing.getLong("trimVideoBitrateBps"))
            // A resumed upload sees the persisted one-shot window cleared and
            // sends the same bytes without a second transcode.
            assertEquals(out, vm.trimForUpload(saved, out))
            assertEquals(1, fake.exports)
        }

    @Test
    fun `a transformer failure falls back to the original`() =
        kotlinx.coroutines.test.runTest {
            val app = ApplicationProvider.getApplicationContext<Context>()
            val clip = File(app.filesDir, "clips/w2.mp4")
            clip.parentFile?.mkdirs()
            clip.writeBytes(ByteArray(100))
            val fake = FakeTrimmer(fail = true)
            vm.trimmer = fake
            WorkStore.put(app, com.barrapp.data.Work(
                id = "w2", createdAt = 0, status = WorkStore.STATUS_WAITING,
                clipPath = clip.absolutePath,
                trimmed = true, trimStartS = 14.0, trimEndS = 22.0,
            ))
            val out = vm.trimForUpload(WorkStore.get(app, "w2")!!, clip)
            // El original es lo que se sube; el work queda sin marca de
            // recorte, así un reintento tampoco lo intenta dos veces.
            assertEquals(clip, out)
            val after = WorkStore.get(app, "w2")!!
            assertFalse(after.trimmed)
            assertEquals(clip.absolutePath, after.clipPath)
            assertTrue(clip.exists())
        }

    @Test
    fun `an untrimmed work uploads the original untouched`() =
        kotlinx.coroutines.test.runTest {
            val app = ApplicationProvider.getApplicationContext<Context>()
            val clip = File(app.filesDir, "clips/w3.mp4")
            clip.parentFile?.mkdirs()
            clip.writeBytes(ByteArray(100))
            val fake = FakeTrimmer()
            vm.trimmer = fake
            WorkStore.put(app, com.barrapp.data.Work(
                id = "w3", createdAt = 0, status = WorkStore.STATUS_WAITING,
                clipPath = clip.absolutePath, trimmed = false,
            ))
            val out = vm.trimForUpload(WorkStore.get(app, "w3")!!, clip)
            assertEquals(clip, out)
            assertEquals(0, fake.exports)
        }

    @Test
    fun `a degenerate window uploads the original`() =
        kotlinx.coroutines.test.runTest {
            val app = ApplicationProvider.getApplicationContext<Context>()
            val clip = File(app.filesDir, "clips/w4.mp4")
            clip.parentFile?.mkdirs()
            clip.writeBytes(ByteArray(100))
            vm.trimmer = FakeTrimmer()
            WorkStore.put(app, com.barrapp.data.Work(
                id = "w4", createdAt = 0, status = WorkStore.STATUS_WAITING,
                clipPath = clip.absolutePath,
                trimmed = true, trimStartS = 5.0, trimEndS = 5.0,
            ))
            val out = vm.trimForUpload(WorkStore.get(app, "w4")!!, clip)
            assertEquals(clip, out)
        }
}
