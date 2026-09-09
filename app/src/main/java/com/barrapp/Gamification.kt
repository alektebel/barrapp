package com.barrapp

import com.barrapp.data.DayEntry
import com.barrapp.data.Profile
import java.util.Calendar
import java.util.Locale

/**
 * The design's progression furniture — streak, XP, level, badges — computed
 * from measured training and nothing else.
 *
 * The mockup ships these as literals (18 days, 2340 XP, level 7, four badges,
 * three of them lit). Shipping the literals would put a number on the home
 * screen that reads as the athlete's own record and is not; the app has an
 * explicit rule against that. So every value here is derived, and every one of
 * them is zero on a phone that has measured nothing.
 *
 * The rules, stated once so they are arguable rather than magic:
 *
 *  - A **training day** is a day with at least one rep barra could measure.
 *  - The **streak** is the run of consecutive training days ending today or
 *    yesterday. Yesterday counts because a streak should not die at midnight
 *    on a day that is not over.
 *  - **XP** is `score / 5` per verified rep plus 50 per training day. A rep
 *    that could not be scored earns nothing — not because it did not happen,
 *    but because there is no evidence of how it went.
 *  - A **level** costs `400 + 200 * (level - 1)` XP, so the ladder lengthens
 *    but never runs away.
 */
object Gamification {

    /** XP a single verified rep is worth, given its score. */
    private fun repXp(score: Int): Int = score / 5

    private const val DAY_XP = 50

    /** The cost of finishing the given level. */
    fun levelCost(level: Int): Int = 400 + 200 * (level - 1)

    /** Level titles, in the app's language. Level 7 and 8 are the mockup's
     *  own — "Técnico Avanzado" and the "Maestro de Técnica" it dangles. */
    private val TITLES = listOf(
        "Primer colgado",
        "Aprendiz de barra",
        "Repetición limpia",
        "Constante",
        "Técnico",
        "Técnico Sólido",
        "Técnico Avanzado",
        "Maestro de Técnica",
        "Referente de la barra",
        "Leyenda",
    )

    fun title(level: Int): String = TITLES.getOrElse(level - 1) { TITLES.last() }

    data class Standing(
        val level: Int,
        val title: String,
        val nextTitle: String,
        /** XP earned inside the current level. */
        val xp: Int,
        /** XP the current level costs. */
        val maxXp: Int,
        val totalXp: Int,
        val streak: Int,
        val trainingDays: Int,
        val verifiedReps: Int,
    ) {
        val fraction: Float get() = if (maxXp <= 0) 0f else (xp.toFloat() / maxXp).coerceIn(0f, 1f)
        val toNext: Int get() = (maxXp - xp).coerceAtLeast(0)
        /** Nothing measured yet: the bar, the level and the streak are all
         *  empty, and the screens say so instead of drawing a full one. */
        val empty: Boolean get() = totalXp == 0
    }

    fun standing(days: List<DayEntry>): Standing {
        val measured = days.filter { it.verifiedReps > 0 }
        val verifiedReps = measured.sumOf { it.verifiedReps }
        val total = measured.sumOf { day ->
            val score = day.score ?: 0
            day.verifiedReps * repXp(score) + DAY_XP
        }
        var level = 1
        var left = total
        while (left >= levelCost(level) && level < TITLES.size) {
            left -= levelCost(level)
            level++
        }
        return Standing(
            level = level,
            title = title(level),
            nextTitle = title(level + 1),
            xp = left,
            maxXp = levelCost(level),
            totalXp = total,
            streak = streak(days),
            trainingDays = measured.size,
            verifiedReps = verifiedReps,
        )
    }

    /** Consecutive training days ending today or yesterday. */
    fun streak(days: List<DayEntry>, today: Calendar = Calendar.getInstance()): Int {
        val trained = days.filter { it.reps > 0 }.map { it.date }.toSet()
        if (trained.isEmpty()) return 0
        val cursor = today.clone() as Calendar
        // A streak may end yesterday: today is not over yet.
        if (iso(cursor) !in trained) {
            cursor.add(Calendar.DAY_OF_YEAR, -1)
            if (iso(cursor) !in trained) return 0
        }
        var run = 0
        while (iso(cursor) in trained) {
            run++
            cursor.add(Calendar.DAY_OF_YEAR, -1)
        }
        return run
    }

    /** One cell of the home screen's week strip. */
    data class WeekDay(
        val label: String,
        val date: String,
        val done: Boolean,
        val today: Boolean,
        val score: Int?,
    )

    private val LETTERS = listOf("L", "M", "X", "J", "V", "S", "D")

    /** Monday to Sunday of the week `today` falls in. */
    fun week(days: List<DayEntry>, today: Calendar = Calendar.getInstance()): List<WeekDay> {
        val byDate = days.associateBy { it.date }
        val todayIso = iso(today)
        val monday = (today.clone() as Calendar).apply {
            // Calendar.MONDAY is 2; this walks back to it whatever the locale's
            // first day of week happens to be.
            val shift = (get(Calendar.DAY_OF_WEEK) + 5) % 7
            add(Calendar.DAY_OF_YEAR, -shift)
        }
        return LETTERS.mapIndexed { i, letter ->
            val cell = (monday.clone() as Calendar).apply { add(Calendar.DAY_OF_YEAR, i) }
            val date = iso(cell)
            val day = byDate[date]
            WeekDay(
                label = letter,
                date = date,
                done = (day?.reps ?: 0) > 0,
                today = date == todayIso,
                score = day?.score,
            )
        }
    }

    /** A badge and whether the training actually earned it. */
    data class Badge(
        val icon: String,
        val label: String,
        val unlocked: Boolean,
    )

    private const val STREAK_BADGE = 7
    private const val REPS_BADGE = 100

    fun badges(days: List<DayEntry>, focusExercise: String?): List<Badge> {
        val standing = standing(days)
        val strongDay = days.any { it.band == "strong" }
        val earned = Progression.verdicts(days, focusExercise)
            .firstOrNull { v -> v.step != null && v.qualifyingDays.size >= v.step.days }
        return listOf(
            Badge(
                icon = "🔥",
                label = if (standing.streak >= STREAK_BADGE) "${standing.streak} días seguidos"
                        else "$STREAK_BADGE días seguidos",
                unlocked = standing.streak >= STREAK_BADGE,
            ),
            Badge("💎", "Serie fuerte", strongDay),
            Badge(
                icon = "💪",
                label = "$REPS_BADGE reps medidas",
                unlocked = standing.verifiedReps >= REPS_BADGE,
            ),
            Badge(
                icon = "👑",
                label = earned?.label?.replaceFirstChar { it.uppercase() } ?: "Primer peldaño",
                unlocked = earned != null,
            ),
        )
    }

    /**
     * Today's mission.
     *
     * Not a plan the app invented: the movement is the one the ladder is
     * currently refereeing (or the declared focus), the target is the rep
     * count the profile already implies, and `done` is what was measured
     * today. When nothing has been measured, the mission is to film a set.
     */
    data class Mission(
        /** The movement key, for the UI to name in its own language. */
        val movementKey: String,
        val movement: String,
        val targetReps: Int,
        val doneReps: Int,
        val focus: String,
        val xpReward: Int,
    ) {
        val fraction: Float
            get() = if (targetReps <= 0) 0f else (doneReps.toFloat() / targetReps).coerceIn(0f, 1f)
        val complete: Boolean get() = doneReps >= targetReps
    }

    fun mission(
        days: List<DayEntry>,
        profile: Profile,
        focusExercise: String?,
        focusCue: String,
        today: Calendar = Calendar.getInstance(),
    ): Mission {
        val verdicts = Progression.verdicts(days, focusExercise)
        val current = verdicts.firstOrNull { it.step != null && it.qualifyingDays.size < it.step.days }
        val key = current?.movement ?: focusExercise
            ?: days.firstOrNull { it.reps > 0 }?.exercise.orEmpty()
        val movement = (current?.label ?: focusExercise ?: days.firstOrNull()?.exerciseLabel)
            ?.replace('_', ' ')
            ?.replaceFirstChar { it.titlecase(Locale.getDefault()) }
            .orEmpty()
            .ifBlank { "tu movimiento" }
        val target = current?.step?.reps?.takeIf { it > 0 } ?: profile.repTarget
        val doneToday = days.firstOrNull { it.date == iso(today) }?.reps ?: 0
        return Mission(
            movementKey = key,
            movement = movement,
            targetReps = target,
            doneReps = doneToday,
            focus = focusCue,
            xpReward = target * repXp(Progression.SOLID) + DAY_XP,
        )
    }

    private fun iso(c: Calendar): String = "%04d-%02d-%02d".format(
        c.get(Calendar.YEAR), c.get(Calendar.MONTH) + 1, c.get(Calendar.DAY_OF_MONTH),
    )
}
