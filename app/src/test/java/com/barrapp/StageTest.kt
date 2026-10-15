package com.barrapp

import com.barrapp.data.BarraApi
import com.barrapp.data.Stage
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * The worker's progress, in Spanish, keyed by a stable code.
 *
 * The progress bar used to find its step by searching the English stage phrase
 * for "recognising", "pose", "finding", "scoring" - so translating the phrase on
 * the server would have silently frozen the bar. The server now sends
 * `stageCode` + Spanish `stageText` beside the old `stage`; the app keys on the
 * code and still understands an older server's English phrase.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class StageTest {
    @Test
    fun `progress follows the stable code`() {
        assertEquals(1, Stage.progressIndex("stage.recognising", ""))
        assertEquals(1, Stage.progressIndex("stage.pose", ""))
        assertEquals(1, Stage.progressIndex("stage.locating", ""))
        assertEquals(3, Stage.progressIndex("stage.finding", ""))
        assertEquals(3, Stage.progressIndex("stage.scoring", ""))
        assertEquals(2, Stage.progressIndex("stage.opening", ""))
    }

    @Test
    fun `an older server's english phrase still maps`() {
        assertEquals("stage.recognising", Stage.legacyCode("recognising the movement"))
        assertEquals("stage.pose", Stage.legacyCode("estimating the pose"))
        assertEquals("stage.scoring", Stage.legacyCode("scoring the reps"))
        assertEquals(3, Stage.progressIndex("", "finding the reps"))
    }

    @Test
    fun `the server's spanish text and code are read`() {
        val job = BarraApi.parseJob(JSONObject(
            """{"id":"j","status":"processing","stage":"recognising the movement",
               "stageCode":"stage.recognising","stageText":"Reconociendo el movimiento"}"""))
        assertEquals("stage.recognising", job.stageCode)
        assertEquals("Reconociendo el movimiento", job.stageText)
        assertEquals("recognising the movement", job.stage)
    }

    @Test
    fun `what the list shows prefers the spanish text`() {
        val job = BarraApi.parseJob(JSONObject(
            """{"id":"j","status":"processing","stage":"scoring the reps","stageText":"Puntuando las repeticiones"}"""))
        assertEquals("Puntuando las repeticiones", Stage.display(job))
        val old = BarraApi.parseJob(JSONObject("""{"id":"j","status":"processing","stage":"scoring the reps"}"""))
        assertEquals("Puntuando las repeticiones", Stage.display(old))
    }

    @Test
    fun `client stages are spanish`() {
        for (text in listOf(Stage.SENDING.text, Stage.QUEUED.text, Stage.WAITING.text,
                            Stage.RESUMING.text, Stage.MEASURING.text)) {
            for (word in listOf("the ", "clip", "queued", "waiting", "sending")) {
                assert(!text.lowercase().contains(word)) { "$text contains $word" }
            }
        }
    }

    @Test
    fun `component labels are read beside the key`() {
        val a = BarraApi.parseAnalysis(JSONObject(
            """{"reps":[{"components":[{"name":"range","label":"recorrido","value":0.8,"weight":0.4,"why":"x"}],
                         "aside":[{"name":"swing","label":"balanceo","value":0.1,"why":"y"}]}]}"""))
        val rep = a.reps.single()
        assertEquals("range", rep.components.single().name)
        assertEquals("recorrido", rep.components.single().label)
        assertEquals("swing", rep.asides.single().name)
        assertEquals("balanceo", rep.asides.single().label)
    }

    @Test
    fun `a session whose vision note is still coming is marked so`() {
        val a = BarraApi.parseAnalysis(JSONObject("""{"visionStatus":"pending"}"""))
        assertEquals(true, a.visionPending)
        assertEquals(false, BarraApi.parseAnalysis(JSONObject("""{"visionStatus":"done"}""")).visionPending)
        assertEquals(false, BarraApi.parseAnalysis(JSONObject("""{}""")).visionPending)
    }

    @Test
    fun `a session whose model prose is still coming is marked so`() {
        val a = BarraApi.parseAnalysis(JSONObject("""{"proseStatus":"pending"}"""))
        assertEquals(true, a.prosePending)
        assertEquals(false, BarraApi.parseAnalysis(JSONObject("""{"proseStatus":"done"}""")).prosePending)
        assertEquals(false, BarraApi.parseAnalysis(JSONObject("""{}""")).prosePending)
    }

    @Test
    fun `count status survives analysis parsing`() {
        val a = BarraApi.parseAnalysis(JSONObject("""{"countStatus":"unmeasured","n_reps":0}"""))
        assertEquals("unmeasured", a.countStatus)
    }
}
