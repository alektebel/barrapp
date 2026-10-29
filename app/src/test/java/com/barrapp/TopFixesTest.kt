package com.barrapp

import com.barrapp.data.BarraApi
import com.barrapp.ui.tracker.fixItems
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * "Lo que mejorar": the three things to fix, most important first
 * (docs/UX-PLAN.md A2). The server ranks them (topFixes); the phone shows them
 * in Spanish with the cue, and keeps the per-rep detail behind "Ver detalle".
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class TopFixesTest {
    private val payload = """{
        "topFixes": [
          {"rank": 1, "errorId": "pull_up.body_swing", "name": "momentum", "observedReps": 6, "judgedReps": 8},
          {"rank": 2, "errorId": "pull_up.incomplete_lockout", "name": "lockout", "observedReps": 4, "judgedReps": 8},
          {"rank": 3, "errorId": "pull_up.dropped_descent", "name": "control", "observedReps": 3, "judgedReps": 7}
        ]}"""

    @Test
    fun `top fixes are read in the server's order`() {
        val a = BarraApi.parseAnalysis(JSONObject(payload))
        assertEquals(listOf("momentum", "lockout", "control"), a.topFixes.map { it.name })
        assertEquals(6, a.topFixes[0].observedReps)
        assertEquals(8, a.topFixes[0].judgedReps)
    }

    @Test
    fun `each fix is a spanish title, a cue and where it showed`() {
        val items = fixItems(BarraApi.parseAnalysis(JSONObject(payload)))
        assertEquals(3, items.size)
        assertEquals(faultEs("momentum"), items[0].title)
        assertNotNull(items[0].cue)
        assertEquals("en 6 de 8 repeticiones", items[0].where)
    }

    @Test
    fun `never more than three`() {
        val four = JSONObject(payload).apply {
            getJSONArray("topFixes").put(JSONObject("""{"rank":4,"errorId":"pull_up.lift_stall","name":"stall","observedReps":3,"judgedReps":8}"""))
        }
        assertEquals(3, fixItems(BarraApi.parseAnalysis(four)).size)
    }

    @Test
    fun `an older server without topFixes falls back to the most frequent faults`() {
        val old = BarraApi.parseAnalysis(JSONObject(
            """{"reps":[{"faults":[{"name":"lockout"},{"name":"momentum"}]},
                        {"faults":[{"name":"lockout"}]},{"faults":[{"name":"lockout"}]}]}"""))
        assertEquals(faultEs("lockout"), fixItems(old).first().title)
    }

    @Test
    fun `nothing to fix is an empty list, not a padded one`() {
        assertTrue(fixItems(BarraApi.parseAnalysis(JSONObject("""{"topFixes": []}"""))).isEmpty())
    }

    @Test
    fun `every fault the server can rank has a spanish name and cue`() {
        // barra/rules.py rule names (tests/test_top_fixes.py pins them to PRIORITY).
        val names = listOf("arm swing", "bent arms", "bent knees", "bounce at bottom", "fast descent",
            "dead hang", "heel raise", "knee valgus", "leaning back", "lockout", "momentum",
            "no active hang", "piked body", "piked hips", "poor range of motion",
            "poor transition",
            "sagging hips", "stall", "too deep", "too fast")
        for (n in names) {
            assertNotEquals(n, faultEs(n).lowercase())
            assertNotNull("no cue for $n", cueEs(n))
        }
    }

    @Test
    fun `capture notes are read from the payload`() {
        val a = BarraApi.parseAnalysis(JSONObject(
            """{"blockers":["b"],"notes":["El vídeo estaba del revés y lo hemos girado."]}"""))
        assertEquals(listOf("El vídeo estaba del revés y lo hemos girado."), a.notes)
        // an older server has no notes at all
        assertEquals(emptyList<String>(), BarraApi.parseAnalysis(JSONObject("{}")).notes)
    }
}
