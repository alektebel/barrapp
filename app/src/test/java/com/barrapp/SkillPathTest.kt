package com.barrapp

import androidx.test.core.app.ApplicationProvider
import com.barrapp.data.SkillGraph
import com.barrapp.ui.tracker.skillPathData
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** The skill path screen's data (docs/UX-PLAN.md B3). */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class SkillPathTest {
    private val graph by lazy { SkillGraph.load(ApplicationProvider.getApplicationContext()) }

    @Test
    fun `rows go by tier and end with the target`() {
        val d = skillPathData(graph, "muscle_up", setOf("pull_up"))!!
        assertEquals("Muscle-up", d.targetName)
        assertEquals(listOf("muscle_up"), d.rows.last().map { it.id })
        assertTrue(d.rows.flatten().any { it.id == "pull_up" && it.state == SkillGraph.VERIFIED })
    }

    @Test
    fun `the next step is marked once and is something to work on`() {
        val d = skillPathData(graph, "muscle_up", setOf("pull_up", "dip"))!!
        val marked = d.rows.flatten().filter { it.next }
        assertEquals(1, marked.size)
        assertEquals(d.next, marked.single())
        assertEquals(SkillGraph.AVAILABLE, d.next!!.state)
    }

    @Test
    fun `edges connect only skills on the path`() {
        val d = skillPathData(graph, "front_lever", emptySet())!!
        val ids = d.rows.flatten().map { it.id }.toSet()
        assertTrue(d.edges.all { (a, b) -> a in ids && b in ids })
        assertTrue("pull_up" to "tuck_front_lever" in d.edges)
    }

    @Test
    fun `the goal leads the target choices`() {
        val d = skillPathData(graph, "front_lever", emptySet(), goal = "pistol_squat")!!
        assertEquals("pistol_squat", d.targets.first().first)
        assertEquals(d.targets.map { it.first }.distinct(), d.targets.map { it.first })
    }

    @Test
    fun `ordering the rows cuts the edge crossings`() {
        for (target in listOf("muscle_up", "front_lever", "full_planche", "human_flag")) {
            val path = graph.path(target)
            val ids = path.map { it.id }.toSet()
            val edges = path.flatMap { s -> s.requires.filter { it in ids }.map { it to s.id } }
            val raw = path.groupBy { it.tier }.toSortedMap().values.map { t -> t.map { it.id } }
            val ordered = com.barrapp.ui.tracker.orderRows(raw, edges)
            assertEquals(raw.map { it.toSet() }, ordered.map { it.toSet() })
            assertTrue(target, com.barrapp.ui.tracker.crossings(ordered, edges) <=
                com.barrapp.ui.tracker.crossings(raw, edges))
        }
    }

    @Test
    fun `an unknown target has no path`() {
        assertNull(skillPathData(graph, "nope", emptySet()))
    }
}
