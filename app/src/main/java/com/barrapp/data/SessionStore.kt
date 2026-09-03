package com.barrapp.data

import android.content.Context
import com.barrapp.Progression
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
                traces = o.optJSONObject("traces")?.let { t ->
                    t.keys().asSequence().associateWith { k -> t.optString(k) }
                } ?: emptyMap(),
                byMovement = o.optJSONObject("byMovement")?.let { m ->
                    m.keys().asSequence().mapNotNull { k ->
                        m.optJSONObject(k)?.let { e ->
                            k to MovementDay(
                                exercise = k,
                                label = e.optString("label", k),
                                reps = e.optInt("reps"),
                                verified = e.optInt("verified"),
                                scoreSum = e.optInt("scoreSum"),
                            )
                        }
                    }.toMap()
                } ?: emptyMap(),
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

        // Only reps scored on ALL their components carry evidence towards a
        // progression. A rep scored on part of its definition is a weaker fact:
        // on a head-on push-up clip the torso ruler fails for the whole set, so
        // those reps say nothing about how deep they were. Clips analysed
        // before the flag existed default to complete rather than vanishing
        // from a history recorded before the distinction did.
        val verified = analysis.reps.filter { it.score != null && it.complete }
        val key = analysis.exercise.ifBlank { "unknown" }
        val was = prior?.byMovement?.get(key)
        val merged = MovementDay(
            exercise = key,
            label = analysis.detected?.label ?: was?.label ?: key,
            reps = (was?.reps ?: 0) + analysis.repCount,
            verified = (was?.verified ?: 0) + verified.size,
            scoreSum = (was?.scoreSum ?: 0) + verified.sumOf { it.score ?: 0 },
        )
        val byMovement = (prior?.byMovement ?: emptyMap()) + (key to merged)

        // The day's score is the rep-weighted mean over every VERIFIED rep of
        // the day, across movements. Weighting by total reps - as this did
        // before the breakdown existed - let unscorable reps dilute a score
        // they contributed nothing to.
        val totalVerified = byMovement.values.sumOf { it.verified }
        val totalSum = byMovement.values.sumOf { it.scoreSum }
        val score = if (totalVerified > 0) totalSum / totalVerified else null
        // The movement the day was mostly about, rather than whichever clip
        // happened to be uploaded last.
        val dominant = byMovement.values.maxByOrNull { it.reps }

        existing[date] = DayEntry(
            date = date,
            exercise = dominant?.exercise ?: prior?.exercise.orEmpty(),
            exerciseLabel = dominant?.label ?: prior?.exerciseLabel.orEmpty(),
            reps = byMovement.values.sumOf { it.reps },
            score = score,
            band = bandFor(score),
            jobIds = ((prior?.jobIds ?: emptyList()) + jobId).distinct(),
            byMovement = byMovement,
            // Kept so a day recorded weeks ago can still be replayed against
            // the exact run that produced its score, rather than a re-run that
            // may not reproduce it.
            traces = (prior?.traces ?: emptyMap()) +
                if (analysis.traceId.isBlank()) emptyMap()
                else mapOf(jobId to analysis.traceId),
        )
        write(context, existing.values.sortedByDescending { it.date })
    }

    fun forget(context: Context, jobId: String) {
        val kept = days(context).mapNotNull { day ->
            if (jobId !in day.jobIds) day
            else {
                val ids = day.jobIds - jobId
                if (ids.isEmpty()) null
                else day.copy(
                    jobIds = ids,
                    traces = day.traces - jobId,
                    // We don't have per-job verified/scoreSum to subtract accurately,
                    // so mark the day as stale rather than showing a ghost score.
                    // Next refresh() from the server will rebuild aggregates.
                    byMovement = emptyMap(),
                    reps = ids.size,
                    score = null,
                    band = "unmeasured",
                )
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
                    .put("traces", JSONObject(d.traces as Map<*, *>))
                    .put("byMovement", JSONObject().also { m ->
                        d.byMovement.forEach { (k, v) ->
                            m.put(k, JSONObject()
                                .put("label", v.label)
                                .put("reps", v.reps)
                                .put("verified", v.verified)
                                .put("scoreSum", v.scoreSum))
                        }
                    })
            )
        }
        prefs(context).edit { putString(DAYS, arr.toString()) }
    }

    private fun bandFor(score: Int?): String = when {
        score == null -> "unmeasured"
        score >= Progression.STRONG -> "strong"
        score >= Progression.SOLID -> "solid"
        score >= Progression.SHAKY -> "shaky"
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
