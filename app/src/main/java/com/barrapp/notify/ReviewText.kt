package com.barrapp.notify

import com.barrapp.data.DayEntry
import com.barrapp.data.Profile
import java.util.Calendar

/**
 * The weekly review, as arithmetic over plain data.
 *
 * Deliberately free of Android: no Context, no Worker, no notification. That is
 * partly good structure and partly the only way to test it - the Compose and
 * androidx toolchain cannot be fetched in this environment, so anything that
 * touches it can be parsed but never run. This can be run.
 *
 * It only produces a review when there is something to report. A notification
 * that arrives every Monday whether or not you trained is one people turn off
 * in a fortnight.
 */
object ReviewText {

    const val FLOOR = 3

    /** Below this the difference is inside the noise of a proxy built from
     *  three bounded components; calling it a trend would be an invention. */
    const val MIN_MEANINGFUL_DELTA = 8

    data class Review(val title: String, val body: String)

    fun compose(profile: Profile, all: List<DayEntry>, since: String = weekAgo()): Review? {
        val week = all.filter { it.date >= since }
        if (week.isEmpty()) return null

        val reps = week.sumOf { it.reps }
        val comparable = week.count { it.reps >= FLOOR }
        val measured = week.filter { it.measured }
        val name = profile.firstName

        val title = "$name \u2014 ${week.size} session${if (week.size == 1) "" else "s"} this week"
        val body = buildString {
            append("$reps rep${if (reps == 1) "" else "s"} measured across ")
            append("${week.size} day${if (week.size == 1) "" else "s"}. ")
            when (comparable) {
                0 -> append(
                    "None reached $FLOOR measured reps, so none can be compared with another " +
                        "session yet. Aim for ${profile.repTarget} in one set."
                )
                1 -> append(
                    "One session reached the $FLOOR-rep floor. One more and there is something " +
                        "to compare it against."
                )
                else -> {
                    append("$comparable sessions cleared the $FLOOR-rep floor. ")
                    append(trendSentence(measured)
                        ?: "Scores held level within their own spread.")
                }
            }
        }
        return Review(title, body)
    }

    fun trendSentence(measured: List<DayEntry>): String? {
        if (measured.size < 2) return null
        val ordered = measured.sortedBy { it.date }
        val delta = (ordered.last().score ?: 0) - (ordered.first().score ?: 0)
        if (kotlin.math.abs(delta) < MIN_MEANINGFUL_DELTA) return null
        return if (delta > 0)
            "The baseline proxy is up $delta points across the week, which is worth a look " +
                "but has not been tested against your own rep-to-rep variation."
        else
            "The baseline proxy is down ${-delta} points across the week."
    }

    fun weekAgo(): String {
        val c = Calendar.getInstance()
        c.add(Calendar.DAY_OF_YEAR, -7)
        return "%04d-%02d-%02d".format(
            c.get(Calendar.YEAR), c.get(Calendar.MONTH) + 1, c.get(Calendar.DAY_OF_MONTH)
        )
    }
}
