package com.barrapp.data

data class CreatedJob(
    val job: Job,
    val uploadUrl: String,
    val uploadMethod: String,
)

data class Job(
    val id: String,
    val status: String,
    val exercise: String,
    val createdAt: String,
    val result: Analysis? = null,
    val error: String? = null,
)

/** What the server made of one clip. */
data class Analysis(
    val headline: String,
    val narrative: String,
    val sessions: List<SessionRow>,
    val reps: List<RepRow>,
    val blockers: List<String>,
    val nextSession: String,
    val exercise: String = "",
    val detected: Detected? = null,
    /** The stretch of the clip that is actually the exercise, in seconds. */
    val trim: Trim? = null,
    val sessionDate: String = "",
    val sessionScore: Int? = null,
    val sessionBand: String = "unmeasured",
    val repCount: Int = 0,
    val candidateCount: Int = 0,
    val durationS: Double = 0.0,
    /** Ties this result to the server's saved decision chain. Shown in
     *  Diagnostics so a report can name one specific run:
     *  `barra explain --replay <id>`. */
    val traceId: String = "",
    /** What produced these numbers. A score that moved because the build moved
     *  is not a score that moved because the athlete did. */
    val provenance: Provenance? = null,
)

data class Provenance(
    val barra: String = "",
    val commit: String = "",
    val python: String = "",
    val platform: String = "",
    val poseModel: String = "",
) {
    val summary: String
        get() = listOf(barra, commit, poseModel.take(12))
            .filter { it.isNotBlank() }.joinToString(" · ")
}

data class Detected(
    val exercise: String,
    val label: String,
    val confidence: Double,
    val reason: String,
    val runnerUp: String? = null,
) {
    val certain: Boolean get() = confidence >= 0.65
}

data class Trim(val startS: Double, val endS: Double) {
    val lengthS: Double get() = (endS - startS).coerceAtLeast(0.0)
}

data class SessionRow(
    val date: String,
    val reps: Int,
    val note: String,
)

data class MetricLine(
    val name: String,
    val value: String,
    val cls: String,
)

/** One component of the quality proxy, shown so the total can be taken apart. */
data class ScorePart(
    val name: String,
    val value: Double?,
    val weight: Double,
    val why: String,
)

/** Measured, reported beside the score, deliberately not folded into it. */
data class Aside(
    val name: String,
    val value: Double,
    val why: String,
)

data class RepRow(
    val session: String,
    val label: String,
    val transitionS: String,
    val totalS: String,
    val cls: String,
    val metrics: List<MetricLine> = emptyList(),
    val problems: List<String> = emptyList(),
    val plausible: Boolean = true,
    val startS: Double = 0.0,
    val endS: Double = 0.0,
    val turnS: Double = 0.0,
    /** null when the rep could not be measured - never a low score instead. */
    val score: Int? = null,
    val band: String = "unmeasured",
    val scoreNote: String = "",
    val components: List<ScorePart> = emptyList(),
    val asides: List<Aside> = emptyList(),
    /** Small copy of the rep's own trace, for drawing. */
    val trace: List<Float> = emptyList(),
)

/**
 * One movement's share of one training day.
 *
 * Kept per movement because a day is not one exercise. Folding push-ups and
 * pull-ups into a single row added their reps together and kept whichever
 * movement was uploaded last, which is wrong for the calendar and useless to
 * the progression referee - "12 reps" of two different movements earns neither.
 *
 * `verified` is the count that actually carries evidence: reps that were
 * segmented, survived the plausibility checks and got a score. `reps` includes
 * the ones barra found but could not score. The two are stored separately
 * because a rep barra could not measure is not a rep the athlete did badly.
 *
 * scoreSum rather than a mean, so merging a second clip into the same day
 * stays exact instead of averaging an average.
 */
data class MovementDay(
    val exercise: String,
    val label: String,
    val reps: Int,
    val verified: Int,
    val scoreSum: Int,
) {
    val score: Int? get() = if (verified > 0) scoreSum / verified else null
}

/** One day in the calendar. Several clips on one day fold into one entry. */
data class DayEntry(
    val date: String,
    val exercise: String,
    val exerciseLabel: String,
    val reps: Int,
    val score: Int?,
    val band: String,
    val jobIds: List<String>,
    /** Per movement, so a mixed day is not silently merged into one number. */
    val byMovement: Map<String, MovementDay> = emptyMap(),
    /**
     * jobId -> the server trace that produced it. Keyed rather than a parallel
     * list so deleting one clip cannot silently shift the rest by one and hand
     * a debugger the wrong run.
     */
    val traces: Map<String, String> = emptyMap(),
) {
    val measured: Boolean get() = score != null

    /** Reps carrying evidence. Falls back to the day total for entries stored
     *  before the breakdown existed, which is the best available guess. */
    val verifiedReps: Int
        get() = if (byMovement.isEmpty()) (if (measured) reps else 0)
                else byMovement.values.sumOf { it.verified }

    /** Newest first, matching the order clips were added to the day. */
    val traceIds: List<String> get() = jobIds.mapNotNull { traces[it] }.reversed()
}

data class ChatTurn(
    val fromUser: Boolean,
    val text: String,
    val at: Long = System.currentTimeMillis(),
)
