package com.barrapp

import com.barrapp.data.ActivityLevel
import com.barrapp.data.DayEntry
import com.barrapp.data.Profile
import com.barrapp.notify.ReviewText

/**
 * Tests for the parts of the app that are pure logic: the coach's answers and
 * the weekly review's arithmetic.
 *
 * Written against no test framework on purpose. The Compose and androidx
 * toolchain cannot be fetched in the environment this was built in, so JUnit
 * would only mean these never ran. A `main` runs on any JVM with the Kotlin
 * stdlib, which means they run here, and they still run under Gradle.
 *
 *     kotlinc <sources> -include-runtime -d logic.jar && java -jar logic.jar
 */
object LogicTest {

    private var failures = 0
    private var checks = 0

    private fun check(name: String, condition: Boolean, detail: String = "") {
        checks++
        if (!condition) {
            failures++
            println("  FAIL  $name${if (detail.isEmpty()) "" else "  ($detail)"}")
        }
    }

    private fun day(date: String, reps: Int, score: Int?) = DayEntry(
        date = date, exercise = "muscle_up", exerciseLabel = "Muscle-up",
        reps = reps, score = score,
        band = when {
            score == null -> "unmeasured"
            score >= 80 -> "strong"
            score >= 60 -> "solid"
            score >= 40 -> "shaky"
            else -> "broken down"
        },
        jobIds = listOf("j-$date"),
    )

    private val profile = Profile("Diego Atencia", 30, ActivityLevel.Regular)

    // ---- profile ---------------------------------------------------------
    private fun profileRules() {
        check("first name is the first word", profile.firstName == "Diego")
        check("blank name falls back", Profile().firstName == "there")
        check("incomplete profile is detected", !Profile("Diego", 0, ActivityLevel.Regular).complete)
        check("age must be plausible", !Profile("Diego", 4, ActivityLevel.Regular).complete)
        check("complete profile is complete", profile.complete)
        check("rep target rises with training", 
            Profile("A", 30, ActivityLevel.New).repTarget < Profile("A", 30, ActivityLevel.Daily).repTarget)
        check("every activity level has a target above the floor",
            ActivityLevel.entries.filter { it != ActivityLevel.Unset }
                .all { Profile("A", 30, it).repTarget >= ReviewText.FLOOR })
    }

    // ---- coach -----------------------------------------------------------
    private fun coachRules() {
        val none = Coach.answer("am I getting better?", emptyList(), profile)
        check("no data means no claim", none.contains("Nothing has been measured"), none)

        val thin = listOf(day("2026-08-10", 1, 83), day("2026-08-14", 2, 78))
        val a = Coach.answer("am I getting better or is it noise?", thin, profile)
        check("below the floor, progress is declined", a.contains("Not yet"), a)
        check("and it says how many sessions qualify", a.contains("0 session"), a)

        val flat = listOf(day("2026-08-10", 4, 78), day("2026-08-17", 4, 80))
        val b = Coach.answer("am I improving?", flat, profile)
        check("a small change is called flat", b.contains("Flat", ignoreCase = true), b)

        val up = listOf(day("2026-08-10", 4, 62), day("2026-08-17", 4, 84))
        val c = Coach.answer("am I improving?", up, profile)
        check("a real change is reported", c.contains("22 points"), c)
        check("and is not called proof", c.contains("not proof"), c)

        val d = Coach.answer("what did my last session show?", up, profile)
        check("last session names its date", d.contains("2026-08-17"), d)

        val e = Coach.answer("how should I film the next one?", up, profile)
        check("filming advice uses the profile's target", e.contains("${profile.repTarget} reps"), e)

        val f = Coach.answer("what is the capital of France?", up, profile)
        check("out of scope is declined", f.contains("I only answer from what has been measured"), f)
        check("and offers what it can do", f.contains("how to film the next one"), f)

        val g = Coach.answer("why did that rep get no score?", up, profile)
        check("unscored reps get the geometric reason", g.contains("not physically possible"), g)

        // Every branch must produce something a person can read.
        listOf("progress", "last session", "no score", "film", "score", "how many reps", "asdf")
            .forEach { q ->
                val ans = Coach.answer(q, up, profile)
                check("answer to '$q' is substantial", ans.length > 40, "${ans.length} chars")
            }
    }

    // ---- weekly review ---------------------------------------------------
    private fun reviewRules() {
        check("a quiet week produces no notification",
            ReviewText.compose(profile, emptyList(), since = "2026-08-01") == null)
        check("old sessions do not count as this week",
            ReviewText.compose(profile, listOf(day("2026-01-01", 5, 80)), since = "2026-08-01") == null)

        val thin = ReviewText.compose(profile, listOf(day("2026-08-10", 2, 70)), since = "2026-08-01")
        check("a thin week is reported", thin != null)
        check("and says nothing cleared the floor", thin!!.body.contains("None reached"), thin.body)
        check("and names the target", thin.body.contains("${profile.repTarget} in one set"))
        check("the title counts sessions", thin.title.contains("1 session"), thin.title)

        val one = ReviewText.compose(profile, listOf(day("2026-08-10", 4, 70)), since = "2026-08-01")
        check("one qualifying session says one more is needed",
            one!!.body.contains("One session reached"), one.body)

        val two = ReviewText.compose(
            profile, listOf(day("2026-08-10", 4, 60), day("2026-08-14", 4, 85)), since = "2026-08-01")
        check("two qualifying sessions report the trend",
            two!!.body.contains("up 25 points"), two.body)

        val level = ReviewText.compose(
            profile, listOf(day("2026-08-10", 4, 80), day("2026-08-14", 4, 83)), since = "2026-08-01")
        check("a small change is not called a trend",
            level!!.body.contains("held level"), level.body)

        check("a change below the threshold is not a trend",
            ReviewText.trendSentence(listOf(day("2026-08-10", 4, 80), day("2026-08-14", 4, 87))) == null)
        check("a change at the threshold is",
            ReviewText.trendSentence(listOf(day("2026-08-10", 4, 80), day("2026-08-14", 4, 88))) != null)

        // Unmeasured days must not be treated as zeros.
        val withGap = ReviewText.compose(
            profile,
            listOf(day("2026-08-10", 4, 80), day("2026-08-12", 3, null), day("2026-08-14", 4, 84)),
            since = "2026-08-01",
        )
        check("an unmeasured day still counts as a session", withGap!!.title.contains("3 session"))
        check("but is not scored as zero", !withGap.body.contains("down 80"), withGap.body)
        check("grammar: plural days", withGap.body.contains("3 days"), withGap.body)

        val single = ReviewText.compose(profile, listOf(day("2026-08-10", 1, 70)), since = "2026-08-01")
        check("grammar: singular rep and day", single!!.body.startsWith("1 rep measured across 1 day."),
            single.body)
    }

    @JvmStatic
    fun main(args: Array<String>) {
        profileRules()
        coachRules()
        reviewRules()
        println(if (failures == 0) "OK  $checks checks passed"
                else "FAILED  $failures of $checks checks")
        if (failures > 0) kotlin.system.exitProcess(1)
    }
}
