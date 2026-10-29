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
    private const val FAULTS = "faults"
    private const val UNSEEN = "unseen"

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    // ---- days -------------------------------------------------------------
    /** Every job id the calendar already holds, so a history sync can tell a
     *  job the phone has never folded in from one it already has. */
    fun knownJobIds(context: Context): Set<String> =
        days(context).flatMap { it.jobIds }.toSet()

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
                last = o.optJSONObject("last")?.let(::summaryFrom),
                sessions = o.optJSONArray("sessions")?.let { a ->
                    (0 until a.length()).mapNotNull { i -> a.optJSONObject(i)?.let(::summaryFrom) }
                } ?: emptyList(),
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

    private fun summaryFrom(l: JSONObject) = JobSummary(
        jobId = l.optString("jobId"),
        exercise = l.optString("exercise"),
        label = l.optString("label"),
        reps = l.optInt("reps"),
        verified = l.optInt("verified"),
        score = if (l.isNull("score") || !l.has("score")) null else l.optInt("score"),
        at = l.optString("at"),
        sessionScore = if (l.isNull("sessionScore") || !l.has("sessionScore")) null else l.optInt("sessionScore"),
        scoreSum = l.optInt("scoreSum"),
    )

    private fun summaryJson(l: JobSummary) = JSONObject()
        .put("jobId", l.jobId).put("exercise", l.exercise)
        .put("label", l.label).put("reps", l.reps)
        .put("verified", l.verified)
        .put("score", l.score ?: JSONObject.NULL).put("at", l.at)
        .put("sessionScore", l.sessionScore ?: JSONObject.NULL)
        .put("scoreSum", l.scoreSum)

    /**
     * Fold one finished job into its day.
     *
     * Several clips on one day are one training day, so reps add up and the
     * score is the rep-weighted mean of the days's measured reps - not the mean
     * of the clip scores, which would let a one-rep clip outvote a five-rep one.
     */
    fun record(context: Context, jobId: String, analysis: Analysis, at: String = "") {
        val date = analysis.sessionDate.ifBlank { today() }
        val existing = days(context).associateBy { it.date }.toMutableMap()
        // Each job is folded in exactly once. The upload queue records a job
        // when it finishes, and the late-text follow-up, refresh() and the
        // history sync all hand the same job back; adding it again doubled
        // the day's reps and score sum.
        if (existing.values.any { jobId in it.jobIds }) return
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

        val summary = JobSummary(
            jobId = jobId,
            exercise = key,
            label = analysis.detected?.label ?: key,
            reps = analysis.repCount,
            verified = verified.size,
            score = if (verified.isEmpty()) null else verified.sumOf { it.score ?: 0 } / verified.size,
            at = at,
            sessionScore = analysis.sessionScore,
            scoreSum = verified.sumOf { it.score ?: 0 },
        )
        val before = prior?.last
        // A clip older than the one already kept (history arrives in any
        // order) must not displace it.
        val last = if (before == null || at.isBlank() || before.at.isBlank() || at >= before.at)
            summary else before

        existing[date] = DayEntry(
            date = date,
            last = last,
            exercise = dominant?.exercise ?: prior?.exercise.orEmpty(),
            exerciseLabel = dominant?.label ?: prior?.exerciseLabel.orEmpty(),
            reps = byMovement.values.sumOf { it.reps },
            score = score,
            band = bandFor(score),
            jobIds = ((prior?.jobIds ?: emptyList()) + jobId).distinct(),
            sessions = ((prior?.sessions ?: emptyList()).filterNot { it.jobId == jobId } + summary),
            byMovement = byMovement,
            // Kept so a day recorded weeks ago can still be replayed against
            // the exact run that produced its score, rather than a re-run that
            // may not reproduce it.
            traces = (prior?.traces ?: emptyMap()) +
                if (analysis.traceId.isBlank()) emptyMap()
                else mapOf(jobId to analysis.traceId),
        )
        write(context, existing.values.sortedByDescending { it.date })
        recordFaults(context, date, analysis)
    }

    /** Drop the whole local calendar.
     *
     *  Signing out has to clear this: the days cached here belong to whoever
     *  was signed in, and leaving them would show one account's training to
     *  the next person to open the app. The measurements themselves are safe
     *  on the server - a refresh rebuilds this from whoever is signed in now. */
    fun forgetAll(context: Context) {
        write(context, emptyList())
        prefs(context).edit { remove(FAULTS); remove(UNSEEN) }
    }

    fun forget(context: Context, jobId: String) {
        markSeen(context, jobId)
        val kept = days(context).mapNotNull { day ->
            if (jobId !in day.jobIds) day
            else {
                val ids = day.jobIds - jobId
                val sessions = day.sessions.filterNot { it.jobId == jobId }
                if (ids.isEmpty()) null
                // Every clip left has its own record: the day is rebuilt from
                // them, exactly, instead of being left without a score.
                else if (sessions.isNotEmpty() && sessions.map { it.jobId }.toSet() == ids.toSet())
                    rebuilt(day, ids, sessions)
                else day.copy(
                    jobIds = ids,
                    traces = day.traces - jobId,
                    // A day stored before the per-clip list was kept has no
                    // per-clip sums to subtract, so mark it stale rather than
                    // showing a ghost score. The next refresh() from the
                    // server rebuilds the aggregates.
                    byMovement = emptyMap(),
                    last = day.last?.takeIf { it.jobId != jobId },
                    sessions = sessions,
                    reps = ids.size,
                    score = null,
                    band = "unmeasured",
                )
            }
        }
        write(context, kept)
    }

    /** A day recomputed from its clips: reps add up, and the score is the
     *  mean over every fully scored rep of the day, so a one-rep clip cannot
     *  outvote a five-rep one. A clip with no scored reps weighs nothing. */
    private fun rebuilt(day: DayEntry, ids: List<String>, sessions: List<JobSummary>): DayEntry {
        val byMovement = sessions.groupBy { it.exercise }.mapValues { (key, js) ->
            MovementDay(
                exercise = key,
                label = js.last().label,
                reps = js.sumOf { it.reps },
                verified = js.sumOf { it.verified },
                scoreSum = js.sumOf { it.scoreSum },
            )
        }
        val verified = byMovement.values.sumOf { it.verified }
        val score = if (verified > 0) byMovement.values.sumOf { it.scoreSum } / verified else null
        val dominant = byMovement.values.maxByOrNull { it.reps }
        return day.copy(
            exercise = dominant?.exercise.orEmpty(),
            exerciseLabel = dominant?.label.orEmpty(),
            reps = byMovement.values.sumOf { it.reps },
            score = score,
            band = bandFor(score),
            jobIds = ids,
            traces = day.traces.filterKeys { it in ids },
            byMovement = byMovement,
            last = sessions.maxWithOrNull(compareBy({ it.at.isBlank().not() }, { it.at })),
            sessions = sessions,
        )
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
                    .put("last", d.last?.let(::summaryJson) ?: JSONObject.NULL)
                    .put("sessions", JSONArray().also { a -> d.sessions.forEach { a.put(summaryJson(it)) } })
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

    // ---- results not looked at yet ------------------------------------------
    //
    // A clip that finishes while the athlete is somewhere else is a result
    // they have not seen. It stays "nuevo" - banner on Inicio, tag in its day -
    // until they open it. Only clips that finished on THIS phone are added: a
    // history sync that brings back last month's sessions is not news.

    fun unseen(context: Context): Set<String> =
        prefs(context).getStringSet(UNSEEN, emptySet()).orEmpty().toSet()

    fun addUnseen(context: Context, jobId: String) {
        if (jobId.isBlank()) return
        prefs(context).edit { putStringSet(UNSEEN, unseen(context) + jobId) }
    }

    fun markSeen(context: Context, jobId: String) {
        val now = unseen(context)
        if (jobId in now) prefs(context).edit { putStringSet(UNSEEN, now - jobId) }
    }

    // ---- fault ledger ------------------------------------------------------
    //
    // The day summary above is enough to draw a calendar, but not enough to
    // answer "is the elbow flare getting better?" - the question the coach and
    // progress screens exist to answer. A clip's faults are gone the moment the
    // analysis is replaced, so the counts are folded into a small per-day ledger
    // as each job lands.
    //
    // Counts, not rep ids: this ledger is read to draw a trend line, never to
    // re-litigate a single rep. The analysis on the server stays the record for
    // that.

    /** date -> fault name -> how many reps showed it that day. */
    fun faults(context: Context): Map<String, Map<String, Int>> {
        val raw = prefs(context).getString(FAULTS, "{}").orEmpty()
        val root = runCatching { JSONObject(raw) }.getOrElse { JSONObject() }
        return root.keys().asSequence().associateWith { date ->
            val day = root.optJSONObject(date) ?: JSONObject()
            day.keys().asSequence().associateWith { fault -> day.optInt(fault) }
        }
    }

    /** Fold one analysis's measured faults into its day. Counts add up, so a
     *  second clip on the same day extends the day rather than replacing it. */
    fun recordFaults(context: Context, date: String, analysis: Analysis) {
        val counts = mutableMapOf<String, Int>()
        analysis.reps.forEach { rep ->
            com.barrapp.repFaults(rep).forEach { counts.merge(it, 1, Int::plus) }
        }
        if (counts.isEmpty()) return
        val existing = faults(context).toMutableMap()
        val day = existing[date].orEmpty().toMutableMap()
        counts.forEach { (fault, n) -> day.merge(fault, n, Int::plus) }
        existing[date] = day
        val root = JSONObject()
        // A year of training is a few hundred rows; the ledger is capped at the
        // last 180 days so it cannot grow without bound on a long-lived phone.
        existing.entries.sortedByDescending { it.key }.take(180).forEach { (d, m) ->
            root.put(d, JSONObject(m as Map<*, *>))
        }
        prefs(context).edit { putString(FAULTS, root.toString()) }
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
