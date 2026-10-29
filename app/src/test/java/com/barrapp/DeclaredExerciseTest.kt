package com.barrapp

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.barrapp.data.DECLARABLE_EXERCISES
import com.barrapp.data.DECLARABLE_EXERCISE_LIST
import com.barrapp.data.Work
import com.barrapp.data.WorkStore
import com.barrapp.ui.tracker.EXERCISE_CHOICES
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File

/**
 * Saying what the exercise is, before the clip goes up.
 *
 * The declaration travels as the work's own field and reaches the server as the
 * job's `exercise`; blank means "detect it". It is kept apart from
 * Work.exercise, which is what the server found, so a declaration can never be
 * read back as a measurement.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class DeclaredExerciseTest {
    private val ctx: Context get() = ApplicationProvider.getApplicationContext()

    @Before fun clean() {
        File(ctx.filesDir, "works.json").delete()
    }

    @Test fun `the declaration survives a kill and stays apart from what was detected`() {
        WorkStore.put(ctx, Work(id = "a", createdAt = 0, status = WorkStore.STATUS_WAITING,
            declaredExercise = "dip", exercise = "knee_raise"))
        val back = WorkStore.get(ctx, "a")!!
        assertEquals("dip", back.declaredExercise)
        assertEquals("knee_raise", back.exercise)
    }

    @Test fun `a work stored before the field existed means detect it`() {
        WorkStore.put(ctx, Work(id = "old", createdAt = 0, status = WorkStore.STATUS_WAITING))
        val file = File(ctx.filesDir, "works.json")
        // an old file has no such key at all
        file.writeText(file.readText().replace("\"declaredExercise\":\"\",", "")
            .replace(",\"declaredExercise\":\"\"", ""))
        assertFalse(file.readText().contains("declaredExercise"))
        assertEquals("", WorkStore.get(ctx, "old")!!.declaredExercise)
    }

    @Test fun `every choice has a spanish name and detection comes first`() {
        assertEquals("", EXERCISE_CHOICES.first().value)
        assertEquals("Detectar solo", EXERCISE_CHOICES.first().label)
        assertEquals(DECLARABLE_EXERCISE_LIST, EXERCISE_CHOICES.drop(1).map { it.value })
        EXERCISE_CHOICES.drop(1).forEach {
            assertFalse("${it.value} has no spanish name", it.label.contains('_'))
            assertTrue(it.label, it.label != it.value)
        }
        assertEquals(DECLARABLE_EXERCISE_LIST.size, DECLARABLE_EXERCISES.size)
    }

    @Test fun `the catalog is the one the server accepts`() {
        // server/api/handler.py DECLARABLE_EXERCISES, which tests/test_declared_exercise.py
        // ties to barra.movements.MOVEMENTS.
        val server = setOf("squat", "muscle_up", "pull_up", "knee_raise", "dip", "push_up",
            "front_lever", "planche", "pistol_squat", "split_squat", "bulgarian_split_squat")
        assertEquals(server, DECLARABLE_EXERCISES)
    }
}
