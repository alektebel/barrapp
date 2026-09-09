package com.barrapp

import java.util.Calendar

/**
 * Is the fault getting better?
 *
 * Reads the per-day fault ledger the session store keeps and answers one
 * question per fault: how many reps showed it in the last N days, and how that
 * compares with the N days before. A count that is falling is the only
 * evidence the coach screen has that a cue is working, and it is a fact about
 * measured reps rather than a feeling about the training.
 *
 * The comparison is deliberately raw counts, not a rate. Rates need a rep
 * total per window, and a window with three reps in it would swing wildly;
 * "twelve reps flared the elbow last month, five this month" is the honest
 * version and the one the athlete can act on.
 */
object FaultTrend {

    data class Row(
        /** The measured fault key — feed it to [faultEs] to display. */
        val fault: String,
        /** Reps showing it in the recent window. */
        val count: Int,
        /** Recent minus previous. Negative is improvement. */
        val delta: Int,
        /** Reps showing it in the previous window. */
        val previous: Int,
    ) {
        val improving: Boolean get() = delta < 0
        /** How much it fell, as a percentage of the previous window. Null when
         *  there is no previous window to compare against. */
        val improvementPct: Int?
            get() = if (previous <= 0) null
                    else (((previous - count).toFloat() / previous) * 100).toInt()
    }

    /**
     * The faults of the last [windowDays] days, worst first, each against the
     * [windowDays] before it.
     */
    fun rows(
        ledger: Map<String, Map<String, Int>>,
        windowDays: Int = 28,
        today: Calendar = Calendar.getInstance(),
    ): List<Row> {
        val recentFrom = iso(shifted(today, -windowDays))
        val previousFrom = iso(shifted(today, -2 * windowDays))
        val recent = mutableMapOf<String, Int>()
        val previous = mutableMapOf<String, Int>()
        ledger.forEach { (date, counts) ->
            val bucket = when {
                date > recentFrom -> recent
                date > previousFrom -> previous
                else -> null
            }
            bucket?.let { b -> counts.forEach { (fault, n) -> b.merge(fault, n, Int::plus) } }
        }
        return recent.entries
            .sortedByDescending { it.value }
            .map { (fault, count) ->
                val was = previous[fault] ?: 0
                Row(fault = fault, count = count, delta = count - was, previous = was)
            }
    }

    /** Total reps that showed any fault in the window — the denominator the
     *  coach screen uses when it says "N reps afectadas". */
    fun affected(rows: List<Row>): Int = rows.sumOf { it.count }

    private fun shifted(from: Calendar, days: Int): Calendar =
        (from.clone() as Calendar).apply { add(Calendar.DAY_OF_YEAR, days) }

    private fun iso(c: Calendar): String = "%04d-%02d-%02d".format(
        c.get(Calendar.YEAR), c.get(Calendar.MONTH) + 1, c.get(Calendar.DAY_OF_MONTH),
    )
}
