package com.barrapp

import com.barrapp.data.Assessment
import com.barrapp.data.BarraApi
import com.barrapp.ui.repChecks
import com.barrapp.ui.standardLine
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * The phone against real server output.
 *
 * The JSON files under `src/test/resources/payloads` are payloads `process_job` produced
 * for two of the sample clips under measurement version 2 (the evaluation
 * runner's cached mode, 2026-09-08). Parsing them here pins the contract the
 * screens depend on: if a server change renames a field, this is where the
 * app finds out - not on a tester's phone as a blank card.
 *
 * Robolectric only because `org.json` is an Android class; nothing here
 * touches a Context.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class PayloadContractTest {

    private fun load(name: String) = BarraApi.parseAnalysis(
        JSONObject(javaClass.getResourceAsStream("/payloads/$name")!!
            .bufferedReader().readText()))

    @Test
    fun muscleUpPayloadCarriesTheAssessmentRecord() {
        val a = load("muscle_up_v2.json")
        assertEquals("muscle_up", a.exercise)
        assertEquals(2, a.measurementVersion)
        assertEquals(2, a.reps.size)
        assertFalse(a.variant.isSpecified)

        val rep = a.reps.first()
        assertEquals(7, rep.assessments.size)
        val lockout = rep.assessments.single { it.errorId == "muscle_up.incomplete_lockout" }
        assertEquals(Assessment.OBSERVED, lockout.status)
        assertEquals("support", lockout.phase)
        assertEquals(listOf(5.83, 6.0), lockout.intervalS)
        assertEquals(85.0, lockout.threshold, 1e-9)
        assertEquals("% of reach", lockout.unit)
        // The observed subset is exactly the fault list the older screens read.
        assertEquals(
            rep.assessments.filter { it.observed }.map { it.errorId }.toSet(),
            rep.faults.map { it.errorId }.toSet(),
        )
        assertTrue(rep.assessments.single { it.errorId == "muscle_up.body_swing" }.variantDependent)

        // Set-level tally, one line per rule, and the standard line names the gap.
        assertEquals(7, a.checks.size)
        assertEquals(2, a.checks.single { it.errorId == "muscle_up.incomplete_lockout" }.observed)
        assertTrue(standardLine(a).startsWith("No standard declared"))

        // What the rep card renders: flagged first, with phase and window.
        val checks = repChecks(rep)
        assertEquals(Assessment.OBSERVED, checks.first().status)
        val lockoutRow = checks.single { it.name == "Lockout" }
        assertEquals("support · 5.8–6.0s", lockoutRow.where)
        assertEquals("75 % of reach, needs 85 % of reach", lockoutRow.detail)
        assertNotNull(rep.phases["support"])
        // JSON null must read as absent, not as the word "null".
        assertTrue(a.reps.all { it.assessmentBlocked == null })
        assertTrue(a.detected?.runnerUp != "null")
    }

    @Test
    fun pushUpPayloadKeepsUnobservableApartFromClean() {
        val a = load("push_up_v2.json")
        assertEquals("push_up", a.exercise)
        assertEquals(19, a.reps.size)
        val all = a.reps.flatMap { it.assessments }
        val blind = all.filter { it.status == Assessment.UNOBSERVABLE }
        assertEquals(19, blind.size)
        assertTrue(blind.all { it.reason.isNotBlank() && it.reasonLabel().isNotBlank() })
        // The push-up defines no variant, so nothing is said about a standard.
        assertEquals("", standardLine(a))
        // A rep with an unobservable check does not read as fully clean.
        val partial = a.reps.first { r -> r.assessments.any { it.status == Assessment.UNOBSERVABLE } }
        assertTrue(unmeasuredNote(partial)!!.startsWith("Not judged:"))
        assertTrue(repChecks(partial).last().detail.isNotBlank())
    }
}
