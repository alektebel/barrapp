package com.barrapp

import com.barrapp.data.ActivityLevel
import com.barrapp.data.DayEntry
import com.barrapp.data.MovementDay
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

    private fun day(date: String, reps: Int, score: Int?, label: String = "Muscle-up") = DayEntry(
        date = date, exercise = label.lowercase().replace("-", "_"), exerciseLabel = label,
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

    /**
     * A calendar entry keeps the id of the run that produced it, so a score
     * recorded weeks ago can still be replayed against the exact run behind it.
     */
    private fun traceRules() {
        val d = DayEntry(
            date = "2026-08-19", exercise = "muscle_up", exerciseLabel = "Muscle-up",
            reps = 5, score = 78, band = "solid",
            jobIds = listOf("j-1", "j-2"),
            traces = mapOf("j-1" to "260828-a", "j-2" to "260828-b"),
        )
        check("newest clip's run comes first", d.traceIds == listOf("260828-b", "260828-a"),
            d.traceIds.toString())

        // Keyed by job id, not a parallel list: deleting the first clip must
        // not shift the rest by one and hand a debugger the wrong run.
        val after = d.copy(jobIds = d.jobIds - "j-1", traces = d.traces - "j-1")
        check("deleting a clip drops only its own run",
            after.traceIds == listOf("260828-b"), after.traceIds.toString())

        val old = d.copy(traces = emptyMap())
        check("an entry stored before runs were kept still reads",
            old.traceIds.isEmpty(), old.traceIds.toString())

        val partial = d.copy(traces = mapOf("j-2" to "260828-b"))
        check("a clip with no run recorded is skipped, not rendered blank",
            partial.traceIds == listOf("260828-b"), partial.traceIds.toString())
    }

    /** The weekly report has to say what the week consisted of, not just how
     *  many reps it contained. */
    private fun weeklyReportRules() {
        val week = listOf(
            day("2026-08-24", 5, 78, "Muscle-up"),
            day("2026-08-26", 19, 94, "Push-up"),
            day("2026-08-27", 4, 71, "Muscle-up"),
        )
        val prior = listOf(day("2026-08-18", 6, 70, "Muscle-up"))
        val r = ReviewText.compose(profile, week + prior, since = "2026-08-22")!!

        check("names the movements trained",
            r.body.lowercase().contains("push-up"), r.body)
        check("counts reps per movement", r.body.contains("19 reps over 1 day"), r.body)
        check("orders by volume, heaviest first",
            r.body.lowercase().indexOf("push-up") < r.body.lowercase().indexOf("muscle-up"),
            r.body)
        check("calls out the best day", r.body.contains("Best day was 26 Aug at 94"), r.body)
        check("compares volume with the week before",
            r.body.contains("up from 6 reps"), r.body)

        // A week with nothing before it must not invent a comparison.
        val alone = ReviewText.compose(profile, week, since = "2026-08-22")!!
        check("no volume claim without a prior week",
            !alone.body.contains("week before"), alone.body)

        // Nor when the prior week exists but was blank.
        val blankPrior = ReviewText.compose(
            profile, week + listOf(day("2026-08-18", 0, null)), since = "2026-08-22")!!
        check("no volume claim against a zero-rep week",
            !blankPrior.body.contains("week before"), blankPrior.body)

        val withBlank = ReviewText.compose(
            profile, week + listOf(day("2026-08-25", 0, null)), since = "2026-08-22")!!
        check("flags sessions that measured nothing",
            withBlank.body.contains("1 session produced no measurable"), withBlank.body)

        check("date formatting drops the leading zero",
            ReviewText.pretty("2026-08-05") == "5 Aug", ReviewText.pretty("2026-08-05"))
        check("date arithmetic crosses a month boundary",
            ReviewText.shiftDays("2026-09-03", -7) == "2026-08-27",
            ReviewText.shiftDays("2026-09-03", -7))
        check("malformed dates are returned untouched",
            ReviewText.pretty("not-a-date") == "not-a-date")

        // The review must carry the progression line - it is the one sentence
        // that says what the week was for.
        val withProg = ReviewText.compose(profile, listOf(
            progDay("2026-08-24", "pull_up", 8, 70),
            progDay("2026-08-26", "pull_up", 8, 70)), since = "2026-08-22")!!
        check("weekly review reports the progression",
            withProg.body.contains("muscle-up"), withProg.body)
        check("and says it was earned",
            withProg.body.contains("cleared the standard"), withProg.body)

        val notYet = ReviewText.compose(profile, listOf(
            progDay("2026-08-24", "pull_up", 4, 70)), since = "2026-08-22")!!
        check("or what is still missing",
            notYet.body.contains("Towards muscle-up"), notYet.body)

        println("\n  --- weekly report ---\n  ${r.title}\n  ${r.body}\n" +
            "\n  ${withProg.body}\n\n  ${notYet.body}\n")
    }

    private fun movementDay(ex: String, label: String, reps: Int, verified: Int, sum: Int) =
        MovementDay(ex, label, reps, verified, sum)

    private fun progDay(date: String, ex: String, verified: Int, quality: Int) = DayEntry(
        date = date, exercise = ex, exerciseLabel = ex, reps = verified,
        score = quality, band = "solid", jobIds = listOf("j-$date-$ex"),
        byMovement = mapOf(ex to movementDay(ex, ex, verified, verified, quality * verified)),
    )

    /** The progression referee. What it must never do is say "ready" on
     *  anything but measured evidence against a stated standard. */
    private fun progressionRules() {
        val step = Progression.LADDER["pull_up"]!!

        val one = Progression.assess("pull_up",
            listOf(progDay("2026-08-10", "pull_up", step.reps + 5, 90)))
        check("one big session is not a progression", !one.ready, one.missing)
        check("and it says a day is missing", one.missing.contains("qualifying day"), one.missing)

        val two = Progression.assess("pull_up", listOf(
            progDay("2026-08-10", "pull_up", step.reps, step.quality),
            progDay("2026-08-14", "pull_up", step.reps, step.quality)))
        check("two qualifying days earn it", two.ready, two.missing)
        check("and nothing is outstanding", two.missing.isEmpty(), two.missing)
        check("headline states the target", two.headline.contains("Ready to work"), two.headline)

        val lowQuality = Progression.assess("pull_up", listOf(
            progDay("2026-08-10", "pull_up", step.reps + 10, step.quality - 15),
            progDay("2026-08-14", "pull_up", step.reps + 10, step.quality - 15)))
        check("volume without quality does not qualify", !lowQuality.ready)
        check("and it names the quality bar",
            lowQuality.missing.contains("${step.quality}"), lowQuality.missing)

        check("the standard is always stated",
            two.standard.contains("${step.reps}") && two.standard.contains("${step.days}"),
            two.standard)

        val untracked = Progression.assess("handstand",
            listOf(progDay("2026-08-10", "handstand", 20, 95)))
        check("an untracked movement says so rather than guessing",
            !untracked.ready && untracked.step == null, untracked.evidence)

        val none = Progression.assess("pull_up", emptyList())
        check("no reps is a starting point, not an error",
            none.evidence.contains("No verified reps"), none.evidence)

        // A mixed day must count each movement on its own merits.
        val mixed = DayEntry(
            date = "2026-08-20", exercise = "push_up", exerciseLabel = "Push-up",
            reps = 20, score = 80, band = "strong", jobIds = listOf("j1", "j2"),
            byMovement = mapOf(
                "push_up" to movementDay("push_up", "Push-up", 15, 15, 15 * 85),
                "pull_up" to movementDay("pull_up", "Pull-up", 5, 5, 5 * 70),
            ),
        )
        val fromMixed = Progression.assess("pull_up", listOf(mixed))
        check("a mixed day does not lend reps between movements",
            fromMixed.bestReps == 5, "${fromMixed.bestReps}")
        check("nor lend quality between movements",
            fromMixed.bestQuality == 70, "${fromMixed.bestQuality}")

        val focus = Progression.focus(listOf(mixed))
        check("focus picks the most-trained movement",
            focus?.movement == "push_up", focus?.movement ?: "null")

        // Unverified reps must never count towards a progression.
        val unverified = DayEntry(
            date = "2026-08-21", exercise = "pull_up", exerciseLabel = "Pull-up",
            reps = 20, score = 90, band = "strong", jobIds = listOf("j3"),
            byMovement = mapOf("pull_up" to movementDay("pull_up", "Pull-up", 20, 3, 3 * 90)),
        )
        val v = Progression.assess("pull_up", listOf(unverified))
        check("only verified reps count towards the standard",
            v.bestReps == 3, "${v.bestReps}")

        check("the ladder says where it stops refereeing",
            Progression.LADDER["muscle_up"]!!.targetMeasurable.not() &&
                Progression.LADDER["squat"]!!.targetMeasurable.not())

        println("\n  --- progression ---\n  ${two.headline}\n  standard: ${two.standard}" +
            "\n  evidence: ${two.evidence}\n  ${one.headline} / ${one.missing}\n")
    }

    @JvmStatic
    fun main(args: Array<String>) {
        profileRules()
        coachRules()
        reviewRules()
        traceRules()
        weeklyReportRules()
        progressionRules()
        println(if (failures == 0) "OK  $checks checks passed"
                else "FAILED  $failures of $checks checks")
        if (failures > 0) kotlin.system.exitProcess(1)
    }
}
