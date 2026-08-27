package com.barrapp.data

import android.content.Context
import androidx.core.content.edit
import org.json.JSONArray
import org.json.JSONObject

/**
 * The calendar's memory, on the phone.
 *
 * The server is the source of truth for measurements, but the calendar has to
 * paint the instant the app opens, offline, on a train, before any request
 * finishes. So every finished job is folded into a small local record and the
 * calendar reads from that. A refresh reconciles it with the server; nothing is
 * ever invented locally that the server did not measure.
 *
 * Kept as JSON in SharedPreferences rather than a database. A year of training
 * is a few hundred rows, and a schema migration is a worse problem to have than
 * a slightly larger string.
 */
object SessionStore {
    private const val PREFS = "barrapp_sessions"
    private const val DAYS = "days"
    private const val CHAT = "chat"
    private const val LAST_REVIEW = "last_review_at"

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    // ---- days -------------------------------------------------------------
    fun days(context: Context): List<DayEntry> {
        val raw = prefs(context).getString(DAYS, "[]").orEmpty()
        val arr = runCatching { JSONArray(raw) }.getOrElse { JSONArray() }
        return (0 until arr.length()).mapNotNull { arr.optJSONObject(it) }.map { o ->
            val ids = o.optJSONArray("jobIds") ?: JSONArray()
            DayEntry(
                date = o.optString("date"),
                exercise = o.optString("exercise"),
                exerciseLabel = o.optString("exerciseLabel"),
                reps = o.optInt("reps"),
                score = if (o.isNull("score")) null else o.optInt("score"),
                band = o.optString("band").ifBlank { "unmeasured" },
                jobIds = (0 until ids.length()).map { i -> ids.optString(i) },
            )
        }.sortedByDescending { it.date }
    }

    /**
     * Fold one finished job into its day.
     *
     * Several clips on one day are one training day, so reps add up and the
     * score is the rep-weighted mean of the days's measured reps - not the mean
     * of the clip scores, which would let a one-rep clip outvote a five-rep one.
     */
    fun record(context: Context, jobId: String, analysis: Analysis) {
        val date = analysis.sessionDate.ifBlank { today() }
        val existing = days(context).associateBy { it.date }.toMutableMap()
        val prior = existing[date]

        val measured = analysis.reps.count { it.score != null }
        val sum = analysis.reps.sumOf { it.score ?: 0 }

        val priorMeasured = if (prior?.score != null) prior.reps else 0
        val priorSum = (prior?.score ?: 0) * priorMeasured
        val totalMeasured = priorMeasured + measured
        val score = if (totalMeasured > 0) (priorSum + sum) / totalMeasured else null

        existing[date] = DayEntry(
            date = date,
            exercise = analysis.exercise.ifBlank { prior?.exercise.orEmpty() },
            exerciseLabel = analysis.detected?.label
                ?: prior?.exerciseLabel.orEmpty().ifBlank { analysis.exercise },
            reps = (prior?.reps ?: 0) + analysis.repCount,
            score = score,
            band = bandFor(score),
            jobIds = ((prior?.jobIds ?: emptyList()) + jobId).distinct(),
        )
        write(context, existing.values.sortedByDescending { it.date })
    }

    fun forget(context: Context, jobId: String) {
        val kept = days(context).mapNotNull { day ->
            if (jobId !in day.jobIds) day
            else {
                val ids = day.jobIds - jobId
                if (ids.isEmpty()) null else day.copy(jobIds = ids)
            }
        }
        write(context, kept)
    }

    private fun write(context: Context, entries: List<DayEntry>) {
        val arr = JSONArray()
        entries.forEach { d ->
            arr.put(
                JSONObject()
                    .put("date", d.date)
                    .put("exercise", d.exercise)
                    .put("exerciseLabel", d.exerciseLabel)
                    .put("reps", d.reps)
                    .put("score", d.score ?: JSONObject.NULL)
                    .put("band", d.band)
                    .put("jobIds", JSONArray(d.jobIds))
            )
        }
        prefs(context).edit { putString(DAYS, arr.toString()) }
    }

    private fun bandFor(score: Int?): String = when {
        score == null -> "unmeasured"
        score >= 80 -> "strong"
        score >= 60 -> "solid"
        score >= 40 -> "shaky"
        else -> "broken down"
    }

    // ---- coach conversation ----------------------------------------------
    fun chat(context: Context): List<ChatTurn> {
        val raw = prefs(context).getString(CHAT, "[]").orEmpty()
        val arr = runCatching { JSONArray(raw) }.getOrElse { JSONArray() }
        return (0 until arr.length()).mapNotNull { arr.optJSONObject(it) }.map {
            ChatTurn(it.optBoolean("fromUser"), it.optString("text"), it.optLong("at"))
        }
    }

    fun appendChat(context: Context, turn: ChatTurn) {
        val arr = JSONArray()
        (chat(context) + turn).takeLast(200).forEach {
            arr.put(
                JSONObject().put("fromUser", it.fromUser).put("text", it.text).put("at", it.at)
            )
        }
        prefs(context).edit { putString(CHAT, arr.toString()) }
    }

    fun clearChat(context: Context) {
        prefs(context).edit { putString(CHAT, "[]") }
    }

    // ---- weekly review ----------------------------------------------------
    fun lastReviewAt(context: Context): Long = prefs(context).getLong(LAST_REVIEW, 0L)

    fun markReviewed(context: Context) {
        prefs(context).edit { putLong(LAST_REVIEW, System.currentTimeMillis()) }
    }

    fun today(): String {
        val c = java.util.Calendar.getInstance()
        return "%04d-%02d-%02d".format(
            c.get(java.util.Calendar.YEAR),
            c.get(java.util.Calendar.MONTH) + 1,
            c.get(java.util.Calendar.DAY_OF_MONTH),
        )
    }
}
