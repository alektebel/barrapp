package com.barrapp

import com.barrapp.data.DayEntry
import kotlin.math.abs

/**
 * Answers built from the measurements already on the phone.
 *
 * Deliberately not a language model call. Every sentence here is arithmetic
 * over the user's own sessions, which means the coach physically cannot invent
 * a PR, a trend, or a technique diagnosis - the failure mode a chat feature in a
 * measurement app is most likely to have, and the most damaging one.
 *
 * The server's prose model still writes the per-clip read-out, where the payload
 * it is given bounds what it can say. This is the conversational surface, and it
 * answers "how do you know that?" with the number it used.
 *
 * When a question is outside what the data supports, it says so and offers the
 * question it can answer instead. That is a better experience than a fluent
 * paragraph that happens to be fiction.
 */
object Coach {

    private const val FLOOR = 3

    fun answer(question: String, state: UiState): String {
        val q = question.lowercase()
        val days = state.days.sortedBy { it.date }
        val name = state.profile.firstName

        if (days.isEmpty()) {
            return "Nothing has been measured yet, so there is nothing I can tell you that " +
                "would be true. Add a clip of a set and I will have something to work with."
        }

        return when {
            q.containsAny("better", "progress", "improving", "improve", "trend", "noise") ->
                progress(days)

            q.containsAny("last session", "last one", "latest", "yesterday", "today", "show") ->
                lastSession(days)

            q.containsAny("no score", "not scored", "unmeasured", "why is", "rejected", "missing") ->
                whyUnscored()

            q.containsAny("film", "record", "camera", "phone", "angle", "next one") ->
                filming(state.profile.repTarget)

            q.containsAny("score", "quality", "number", "mean") ->
                whatTheScoreIs()

            q.containsAny("how many", "reps", "volume", "count") ->
                volume(days)

            else -> fallback(name, days)
        }
    }

    private fun progress(days: List<DayEntry>): String {
        val comparable = days.filter { it.reps >= FLOOR }
        if (comparable.size < 2) {
            val have = comparable.size
            return "Not yet, and I would rather say so than guess. Comparing two sessions " +
                "needs each of them to have at least $FLOOR measured reps — otherwise the " +
                "session's median is one or two reps and there is no way to separate how much " +
                "you vary between reps from a real change. You have $have session" +
                (if (have == 1) "" else "s") + " at or above that floor."
        }
        val measured = comparable.filter { it.measured }
        if (measured.size < 2) {
            return "You have ${comparable.size} sessions with enough reps, but fewer than two " +
                "of them produced a score. Usually that is a filming problem rather than a " +
                "training one — ask me how to film the next one."
        }
        val first = measured.first()
        val last = measured.last()
        val delta = (last.score ?: 0) - (first.score ?: 0)
        val direction = if (delta > 0) "up" else "down"
        return if (abs(delta) < 8) {
            "Flat, within the resolution this has. The baseline proxy went from " +
                "${first.score} on ${first.date} to ${last.score} on ${last.date}, and a gap " +
                "that small is inside the noise of a proxy built from three bounded components. " +
                "Stable is a real answer, not a non-answer."
        } else {
            "The baseline proxy is $direction ${abs(delta)} points, ${first.score} on " +
                "${first.date} to ${last.score} on ${last.date}, across ${measured.size} " +
                "measured sessions. Worth a look. It is not proof: that number has no null " +
                "distribution behind it, so it has not been tested against your own " +
                "rep-to-rep variation."
        }
    }

    private fun lastSession(days: List<DayEntry>): String {
        val last = days.last()
        val head = "${last.date}: ${last.exerciseLabel.ifBlank { last.exercise }}, " +
            "${last.reps} rep${if (last.reps == 1) "" else "s"} measured"
        return if (last.measured) {
            "$head, baseline proxy ${last.score} (${last.band}). " +
                if (last.reps >= FLOOR)
                    "That is enough reps for the session to take part in a comparison."
                else
                    "That is under the $FLOOR-rep floor, so it cannot be compared with another " +
                        "session yet."
        } else {
            "$head, but nothing scored. The reps were found and then rejected — open the " +
                "session and the reason is written on each one."
        }
    }

    private fun whyUnscored(): String =
        "A rep gets no score when the pose estimate is not physically possible or too little " +
            "of it was tracked. The commonest cause is being too far from the camera: the " +
            "estimator returns confident nonsense rather than admitting it cannot see you. " +
            "It is shown as an em dash rather than a low score on purpose — a filming failure " +
            "is not bad technique, and marking it as one would be the most misleading thing " +
            "this app could do."

    private fun filming(target: Int): String =
        "Five things, in the order they cost you:\n\n" +
            "1. Fill the frame, and keep the top of the rep in it. A rep whose turnaround is " +
            "not seen is discarded whole.\n" +
            "2. Phone on a tripod, position marked on the floor. A camera that moves a few " +
            "degrees between sessions shifts the measurement more than a real technique change.\n" +
            "3. Same side every session. Front and behind are mirror images and cannot be " +
            "pooled.\n" +
            "4. $target reps in one set — above the $FLOOR-rep floor with margin.\n" +
            "5. Start recording as you reach up, stop when you drop off."

    private fun whatTheScoreIs(): String =
        "It is a baseline proxy, not a technique grade. Three parts: how much of the range " +
            "your own arm length makes available you used (40%), whether the descent was " +
            "lowered or dropped (25%), and whether the ascent stalled (35%). Open any rep and " +
            "all three are shown with their own numbers.\n\n" +
            "Swing and left-right asymmetry are measured but deliberately left out of it. They " +
            "are horizontal, so including them would make the number depend on where you stood " +
            "your phone."

    private fun volume(days: List<DayEntry>): String {
        val total = days.sumOf { it.reps }
        val ready = days.count { it.reps >= FLOOR }
        return "$total measured rep${if (total == 1) "" else "s"} across ${days.size} " +
            "day${if (days.size == 1) "" else "s"}. $ready of those days reached the $FLOOR-rep " +
            "floor that a comparison needs."
    }

    private fun fallback(name: String, days: List<DayEntry>): String =
        "I only answer from what has been measured, $name, and I cannot see that in your " +
            "${days.size} recorded session${if (days.size == 1) "" else "s"}. Things I can " +
            "answer: what your last session showed, whether a change is real or noise, why a " +
            "rep got no score, what the score is made of, and how to film the next one."

    private fun String.containsAny(vararg needles: String): Boolean =
        needles.any { this.contains(it) }
}
