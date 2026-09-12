package com.barrapp.data

data class CreatedJob(
    val job: Job,
    val uploadUrl: String,
    val uploadMethod: String,
)

/** The server's answer to a feedback submission: its id, and - when a clip
 *  was offered - the presigned PUT url to stream it through. */
data class CreatedFeedback(
    val id: String,
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
    /** Where the server's worker is, in words. Absent when idle or done. */
    val stage: String = "",
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
    /** The first learned model's verdict and load estimate, shipped beside the
     *  geometric [detected] as a second opinion - never a replacement. Null
     *  when the server had no trained model (or it had no classes). */
    val model: ModelVerdict? = null,
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
    /** The declared variant the checks were applied under. */
    val variant: Variant = Variant(),
    /** Version of the measurement semantics (phases, thresholds, rule ids).
     *  0 for payloads that predate the structured assessment. Results with
     *  different versions are not comparable rep for rep. */
    val measurementVersion: Int = 0,
    /** Per check, how many reps observed it, were checked clean, or could
     *  not be checked. The whole-clip view of the assessments. */
    val checks: List<CheckSummary> = emptyList(),
    /** Validated observations from the optional vision pass. Advisory. */
    val visionObservations: List<VisionObservation> = emptyList(),
    /** True when the vision model saw a different movement than the
     *  geometry labelled - flagged for review, never applied. */
    val visionDisagreesOnMovement: Boolean = false,
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

/**
 * What the server decided this clip shows, and how clear the call was.
 *
 * `confidence` is NOT a probability. The server computes it as how far the
 * measurement that decided the label sits past the threshold it was compared
 * against, bounded - which is why it ships `certainty` naming the kind. This
 * screen used to render it as "82% confident", a claim the pipeline never
 * made and cannot make: it holds no model of how often it is right.
 */
data class Detected(
    val exercise: String,
    val label: String,
    val confidence: Double,
    val reason: String,
    val runnerUp: String? = null,
    val certainty: String = MARGIN_TO_THRESHOLD,
) {
    /** The deciding measurement is clear of its threshold. Not "probably right". */
    val certain: Boolean get() = confidence >= CLEAR_MARGIN

    /** How to say the number without claiming more than was measured. */
    val certaintyLabel: String
        get() = if (certainty == MARGIN_TO_THRESHOLD)
            "${(confidence * 100).toInt()}% clear of the boundary"
        else "${(confidence * 100).toInt()}% confident"

    companion object {
        const val MARGIN_TO_THRESHOLD = "margin-to-threshold"
        const val CLEAR_MARGIN = 0.65
    }
}

data class Trim(val startS: Double, val endS: Double) {
    val lengthS: Double get() = (endS - startS).coerceAtLeast(0.0)
}

/** The first learned model's verdict on a clip, besides the geometric one. */
data class ModelVerdict(
    val classification: ModelClassification? = null,
    val load: LoadEstimate? = null,
)

data class ModelClassification(
    val exercise: String,
    val confidence: Double,
    val runnerUp: String? = null,
    val marginToRunnerUp: Double = 0.0,
    val probabilities: Map<String, Double> = emptyMap(),
    val modelVersion: String = "",
)

/** What the athlete was carrying, and how that estimate should be read. */
data class LoadEstimate(
    val kg: Double = 0.0,
    val estimated: Boolean = false,
    val note: String = "",
)

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

/**
 * A fault the server measured, with the number that fired it.
 *
 * The phone used to re-derive the faults itself, by running regular
 * expressions over the human-readable `why` strings ("lockout 76% of full")
 * and comparing against its own copies of the thresholds. Two consequences:
 * rewording a sentence on the server switched fault detection off on every
 * device, and the thresholds existed in three places that nothing kept equal.
 * The server ships the verdict and its evidence now, and this is that shape.
 */
data class MeasuredFault(
    val name: String,
    val primitive: String = "",
    val value: Double? = null,
    val threshold: Double = 0.0,
    val comparison: String = "",
    val unit: String = "",
    val cls: String = "",
    /** Stable, movement-scoped id ("muscle_up.incomplete_lockout"). Empty on
     *  payloads older than measurement version 2. */
    val errorId: String = "",
    /** The phase the primitive was read in (setup, lifting, support...). */
    val phase: String = "",
    /** [start, end] seconds in the source video of that phase window. */
    val intervalS: List<Double> = emptyList(),
) {
    /** "76% of reach, needs 85" - the number, never re-derived here. */
    fun evidence(): String {
        val v = value ?: return ""
        val needs = if (comparison.startsWith("<")) "needs" else "limit"
        return "${fmt(v)}${unitSuffix()}, $needs ${fmt(threshold)}${unitSuffix()}"
    }

    private fun unitSuffix() = if (unit.isBlank()) "" else " $unit"

    private fun fmt(d: Double): String =
        if (d >= 10 || d == d.toLong().toDouble()) d.toLong().toString()
        else String.format("%.2f", d)
}

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
    /**
     * Every graded component was measured, not just some of them.
     *
     * Defaults to true so clips analysed before the server sent this field
     * keep counting - a history recorded before the distinction existed should
     * not silently empty itself when the distinction arrives.
     */
    val complete: Boolean = true,
    val components: List<ScorePart> = emptyList(),
    val asides: List<Aside> = emptyList(),
    /** One-sided faults (a dropped descent), measured and penalised. Kept
     *  beside the components rather than folded into them: a penalty absent
     *  costs nothing, and its `why` is the plain-language description. */
    val penalties: List<ScorePart> = emptyList(),
    /** Small copy of the rep's own trace, for drawing. */
    val trace: List<Float> = emptyList(),
    /** The faults the server measured, each with its own number. */
    val faults: List<MeasuredFault> = emptyList(),
    /** Measurements this rep could not produce. Not the same as clean: a fault
     *  whose evidence is missing did not fire, and did not pass either. */
    val unmeasured: List<String> = emptyList(),
    /** Measurements the camera angle cannot support - knee valgus needs a
     *  frontal view, a sagging hip line a side-on one. */
    val viewBlocked: List<String> = emptyList(),
    /**
     * Every check the movement defines, with its verdict: observed,
     * not_observed or unobservable (and why). `faults` is the observed
     * subset; this is the population it was drawn from, so an empty fault
     * list can be told apart from a rep nothing could be checked on.
     * Empty on payloads older than measurement version 2.
     */
    val assessments: List<Assessment> = emptyList(),
    /** Phase name -> [start, end] seconds in the source video. */
    val phases: Map<String, List<Double>> = emptyMap(),
    /** Non-null when the whole rep was withheld from assessment - an
     *  implausible pose, too little tracking - with the reason. */
    val assessmentBlocked: String? = null,
) {
    val checked: Int get() = assessments.count { it.status != Assessment.UNOBSERVABLE }
    val unobservable: List<Assessment> get() = assessments.filter { it.status == Assessment.UNOBSERVABLE }
}

/**
 * One rule applied to one rep: the verdict and the evidence behind it.
 *
 * `status` is three-valued on purpose. `not_observed` is a check that was
 * made and came back clean; `unobservable` is a check that could not be made
 * - the camera angle, too little of the phase tracked, a joint never seen -
 * and must never be rendered as a pass.
 */
data class Assessment(
    val errorId: String,
    val name: String,
    val phase: String,
    val status: String,
    val intervalS: List<Double> = emptyList(),
    val value: Double? = null,
    val threshold: Double = 0.0,
    val comparison: String = "",
    val unit: String = "",
    /** Why it could not be checked, when `status` is unobservable. */
    val reason: String = "",
    val reasonDetail: String = "",
    /** The verdict depends on a variant (strict / kipping) nobody declared. */
    val variantDependent: Boolean = false,
    /** "geometry" for the measured pipeline; "vision-advisory" rows never
     *  arrive here - they live in Analysis.visionObservations. */
    val source: String = SOURCE_GEOMETRY,
) {
    val observed: Boolean get() = status == OBSERVED

    /** Plain words for the availability reason. */
    fun reasonLabel(): String = when {
        reason.startsWith("unsuitable view") -> "needs a different camera angle"
        reason.startsWith("insufficient temporal evidence") -> "too little of this phase was tracked"
        reason.startsWith("unsupported variant") -> "depends on the variant"
        reason.startsWith("not applicable") -> "not defined for this movement"
        reason.startsWith("tracking loss") -> "the joints it needs were lost by the tracker"
        reason.startsWith("missing primitive") -> "no measurement of this in the clip"
        reason.isNotBlank() -> "not tracked"
        else -> ""
    }

    companion object {
        const val OBSERVED = "observed"
        const val NOT_OBSERVED = "not_observed"
        const val UNOBSERVABLE = "unobservable"
        const val SOURCE_GEOMETRY = "geometry"
    }
}

/**
 * What the vision model said it saw, validated server-side against the
 * request it was sent. Advisory: it is shown beside the measured rows and
 * never counted as a fault.
 */
data class VisionObservation(
    val rep: String,
    val errorId: String,
    val name: String,
    val phase: String,
    val status: String,
    val description: String,
    val frames: List<String> = emptyList(),
)

/** The declared technique variant, or unspecified. Never inferred. */
data class Variant(
    val name: String = UNSPECIFIED,
    val source: String = "none",
    /** A declaration the server did not recognise, kept so the user can see
     *  their word was not applied. */
    val declared: String? = null,
) {
    val isSpecified: Boolean get() = name != UNSPECIFIED
    companion object { const val UNSPECIFIED = "unspecified" }
}

/** Clip-level roll-up of one check across the reps. */
data class CheckSummary(
    val errorId: String,
    val name: String,
    val phase: String,
    val observed: Int,
    val notObserved: Int,
    val unobservable: Int,
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

/** What the objectives chat asked for and got back from the server.
 *  `goals` is null until the model has enough to fill one in. */
data class ChatResult(
    val reply: String,
    val goals: Goals? = null,
)

/**
 * The training objectives the intake chat extracted. Blank fields mean "not
 * captured yet"; [merge] fills only the gaps, so a partial JSON block that
 * arrives mid-conversation never wipes an earlier value.
 */
data class Goals(
    val name: String = "",
    val age: Int = 0,
    val activity: String = "",
    val goal: String = "",
    val focusExercise: String = "",
    /** Added load (kg) the athlete trains with, when they capture it. The
     *  model's load estimate is a stocktake, never an override of this. */
    val loadKg: Double = 0.0,
) {
    fun merge(other: Goals): Goals = Goals(
        name = other.name.ifBlank { name },
        age = if (other.age > 0) other.age else age,
        activity = other.activity.ifBlank { activity },
        goal = other.goal.ifBlank { goal },
        focusExercise = other.focusExercise.ifBlank { focusExercise },
        loadKg = if (other.loadKg > 0.0) other.loadKg else loadKg,
    )
}
