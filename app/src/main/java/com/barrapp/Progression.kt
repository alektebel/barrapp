package com.barrapp

import com.barrapp.data.DayEntry

/**
 * Am I ready for the next progression?
 *
 * This is the question the app exists to answer. See `docs/MARKET.md` for why:
 * it is the decision calisthenics actually turns on, it is made constantly, and
 * every app in the market either ignores it or asks the athlete to self-report
 * the answer it then acts on.
 *
 * Two things are kept strictly apart, and the separation is the whole point:
 *
 *  - **Whether a rep counts is measured.** A rep is verified when it was
 *    segmented out of the footage, survived the plausibility checks and got a
 *    score. Nothing else counts, and every one carries a trace id that can be
 *    replayed with `barra explain --replay <id>`.
 *
 *  - **How many verified reps earn the next step is a convention.** The numbers
 *    in [LADDER] are a published standard, not a discovery. They sit close to
 *    the rule the sport already uses - roughly three sets of ten controlled reps
 *    before moving on - and they are written in the open so they can be argued
 *    with. Presenting them as though they fell out of the data would be the
 *    same dishonesty the measurement core refuses everywhere else.
 *
 * So the claim the app makes is narrow: *you have N verified reps against a
 * standard of M, and here is the trace for each.* Not "you are ready", on our
 * authority.
 *
 * Deliberately free of Android so it can be run rather than only parsed, and
 * deliberately a mirror of `barra/progression.py` - the numbers are pinned
 * against it by a test, because a ladder that drifts between the two would let
 * the phone and the server referee the same athlete differently.
 */
object Progression {

    /**
     * Boundaries converted, not re-tuned, when control left the weighted mean.
     * 
     * Control sat at its ceiling for 86% of reps, so the old score was
     * 0.25 + 0.75 x graded and no rep could score below 25. Removing that floor
     * changes what a given number means, so the boundaries were mapped back through
     * it to keep the SAME reps on the same side of each line:
     * 
     *     old 80  ->  (80 - 25) / 75  ->  73
     *     old 60  ->  (60 - 25) / 75  ->  47
     *     old 40  ->  (40 - 25) / 75  ->  20
     * 
     * This is a restatement of an existing convention in a changed unit, not a
     * recalibration to make scores look better - a muscle-up that read 78 (solid)
     * now reads 56, and is still solid. The boundaries remain conventions and are
     * still unvalidated: see docs/QUALITY.md.
     */
    const val SOLID = 47
    const val STRONG = 73
    const val SHAKY = 20

    data class Step(
        val towards: String,
        val towardsLabel: String,
        val reps: Int,
        val quality: Int,
        val days: Int,
        /** Can barra verify the movement being progressed TO? Where it cannot,
         *  the app says so rather than implying it keeps refereeing. */
        val targetMeasurable: Boolean = true,
        val note: String = "",
    )

    /** The published standard. Conservative on purpose: the cost of holding
     *  someone back a session is a session; the cost of waving them onto a
     *  muscle-up they cannot hold is a shoulder. */
    val LADDER: Map<String, Step> = mapOf(
        "push_up" to Step(
            "dip", "Dip", reps = 15, quality = SOLID, days = 2,
            note = "Dips load the same push pattern through a longer range.",
        ),
        "dip" to Step(
            "muscle_up", "Muscle-up", reps = 10, quality = SOLID, days = 2,
            note = "The dip is the second half of a muscle-up. The transition " +
                "is the other half, so a pull-up standard applies too.",
        ),
        "pull_up" to Step(
            "muscle_up", "Muscle-up", reps = 8, quality = SOLID, days = 2,
            note = "The transition needs the pull to finish high and under " +
                "control, which is what the quality bar is for.",
        ),
        "muscle_up" to Step(
            "weighted_muscle_up", "Weighted or strict muscle-up",
            reps = 5, quality = STRONG, days = 2, targetMeasurable = false,
            note = "Barra cannot verify added load from video, so it stops " +
                "refereeing here and this becomes a training decision.",
        ),
        "knee_raise" to Step(
            "toes_to_bar", "Toes to bar", reps = 12, quality = SOLID, days = 2,
            targetMeasurable = false,
            note = "Toes to bar is not in the measured vocabulary yet, so barra " +
                "can confirm you have earned the attempt but not score it.",
        ),
        "squat" to Step(
            "pistol_squat", "Pistol squat", reps = 20, quality = SOLID, days = 2,
            targetMeasurable = false,
            note = "A pistol is single-leg, and barra measures the hips as one " +
                "point, so it cannot tell the two apart.",
        ),
    )

    data class Verdict(
        val movement: String,
        val label: String,
        val step: Step?,
        val ready: Boolean,
        val qualifyingDays: List<String>,
        val bestReps: Int,
        val bestQuality: Int?,
        val standard: String,
        val evidence: String,
        val missing: String,
    ) {
        val headline: String
            get() = when {
                step == null -> "No progression tracked for this movement"
                ready -> "Ready to work ${step.towardsLabel}"
                else -> "Working towards ${step.towardsLabel}"
            }
    }

    private fun band(q: Int?): String = when {
        q == null -> "unscored"
        q >= STRONG -> "strong"
        q >= SOLID -> "solid"
        else -> "below the bar"
    }

    /**
     * Referee one movement against its published standard.
     *
     * Reads the per-movement breakdown so a mixed training day counts each
     * movement on its own merits rather than on the day's total.
     */
    /** The ladder as the home page reads it: the focus movement first when it
     *  has not started yet, then everything trained, best first. */
    fun verdicts(all: List<DayEntry>, focusExercise: String? = null): List<Verdict> {
        val trained = LADDER.keys.map { assess(it, all) }
            .filter { it.bestReps > 0 }
            .sortedByDescending { it.bestReps }
        val focus = focusExercise?.takeIf { it in LADDER }
            ?.let { assess(it, all) }
            ?.takeIf { it.bestReps == 0 }
        return listOfNotNull(focus) + trained
    }

    fun assess(movement: String, all: List<DayEntry>): Verdict {
        val step = LADDER[movement]
        val label = all.firstNotNullOfOrNull { it.byMovement[movement]?.label }
            ?: movement.replace("_", " ").replaceFirstChar { it.uppercase() }
        if (step == null) {
            return Verdict(
                movement, label, null, false, emptyList(), 0, null, "",
                "Barra has no progression ladder for this movement yet.", "",
            )
        }
        val standard = "${step.reps} verified reps in one session at " +
            "${step.quality} or better, on ${step.days} separate days."

        val days = all.mapNotNull { d -> d.byMovement[movement]?.let { d.date to it } }
            .filter { it.second.verified > 0 }
        if (days.isEmpty()) {
            return Verdict(
                movement, label, step, false, emptyList(), 0, null, standard,
                "No verified reps of this movement yet.",
                "Film a set. ${step.reps} verified reps is the bar.",
            )
        }

        val qualifying = days
            .filter { it.second.verified >= step.reps && (it.second.score ?: 0) >= step.quality }
            .map { it.first }
            .sorted()
        val best = days.maxByOrNull { it.second.verified * 1000 + (it.second.score ?: 0) }!!
        val bestReps = best.second.verified
        val bestQuality = best.second.score

        val evidence = "Best session: $bestReps verified rep${if (bestReps == 1) "" else "s"} " +
            "at $bestQuality (${band(bestQuality)}) on ${best.first}. " +
            "${qualifying.size} of ${step.days} days clear the standard."

        if (qualifying.size >= step.days) {
            return Verdict(movement, label, step, true, qualifying, bestReps,
                bestQuality, standard, evidence, "")
        }

        val gaps = mutableListOf<String>()
        if (bestReps < step.reps) {
            val short = step.reps - bestReps
            gaps += "$short more verified rep${if (short == 1) "" else "s"} in one session"
        } else if ((bestQuality ?: 0) < step.quality) {
            gaps += "the same volume at ${step.quality} or better (best so far $bestQuality)"
        }
        if (qualifying.isNotEmpty()) {
            val short = step.days - qualifying.size
            gaps += "$short more qualifying day${if (short == 1) "" else "s"}"
        }
        return Verdict(movement, label, step, false, qualifying, bestReps,
            bestQuality, standard, evidence, "Still needed: " + gaps.joinToString(", and ") + ".")
    }

    /** The movement worth showing: the one with the most verified reps on
     *  record, since that is what the athlete is actually training. */
    fun focus(all: List<DayEntry>): Verdict? {
        val totals = mutableMapOf<String, Int>()
        all.forEach { d ->
            d.byMovement.forEach { (k, m) -> totals[k] = (totals[k] ?: 0) + m.verified }
        }
        val movement = totals.filterKeys { LADDER.containsKey(it) }
            .maxByOrNull { it.value }?.key ?: return null
        return assess(movement, all)
    }
}
