package com.barrapp.data

import android.content.Context
import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** Phone-local Round 2 timings. Monotonic values are comparable only while
 * the boot ID is unchanged; wall time is retained for diagnostics, not math. */
object Round2TimingStore {
    data class Attempt(
        val attemptId: String,
        val bootId: String,
        val startedNs: Long,
        val completeOrigin: Boolean = true,
        val jobId: String = "",
        val submittedNs: Long = 0,
        val resultNs: Long = 0,
        val renderedNs: Long = 0,
        val wallStartedMs: Long = 0,
        val wallRenderedMs: Long = 0,
        val traceId: String = "",
        val countStatus: String? = null,
        val repCount: Int? = null,
        val preparationMs: Long? = null,
        val trimExportMs: Long? = null,
        val trimVideoBitrateBps: Long? = null,
        val sourceBytes: Long? = null,
        val preparedBytes: Long? = null,
        val trimConfirmedNs: Long = 0,
        val trimConfirmedBootId: String = "",
        val pollCount: Int? = null,
        val phaseMs: Map<String, Long> = emptyMap(),
    ) {
        fun durationMs(endNs: Long): Long? = monotonicDurationMs(
            startedNs, endNs, bootId, currentBootId(), completeOrigin)

        fun intervalMs(startNs: Long, endNs: Long): Long? = monotonicDurationMs(
            startNs, endNs, bootId, currentBootId())

        fun confirmedToRenderedMs(endNs: Long): Long? = monotonicDurationMs(
            trimConfirmedNs, endNs, trimConfirmedBootId, currentBootId())
    }

    private const val LIMIT = 100
    private fun file(context: Context) = File(context.filesDir, "round2-timings.json")

    private fun currentBootId(): String = runCatching {
        File("/proc/sys/kernel/random/boot_id").readText().trim()
    }.getOrDefault("")

    @Synchronized private fun read(context: Context): MutableList<Attempt> {
        val raw = runCatching { JSONArray(file(context).readText()) }.getOrNull()
            ?: return mutableListOf()
        return (0 until raw.length()).mapNotNull { i ->
            val o = raw.optJSONObject(i) ?: return@mapNotNull null
            val id = o.optString("attemptId")
            if (id.isBlank()) return@mapNotNull null
            Attempt(
                attemptId = id,
                bootId = o.optString("bootId"),
                startedNs = o.optLong("startedNs"),
                completeOrigin = o.optBoolean("completeOrigin", true),
                jobId = o.optString("jobId"),
                submittedNs = o.optLong("submittedNs"),
                resultNs = o.optLong("resultNs"),
                renderedNs = o.optLong("renderedNs"),
                wallStartedMs = o.optLong("wallStartedMs"),
                wallRenderedMs = o.optLong("wallRenderedMs"),
                traceId = o.optString("traceId"),
                countStatus = if (o.isNull("countStatus")) null else o.optString("countStatus"),
                repCount = if (o.isNull("repCount")) null else o.optInt("repCount"),
                preparationMs = if (o.has("preparationMs") && !o.isNull("preparationMs")) o.optLong("preparationMs") else null,
                trimExportMs = if (o.has("trimExportMs") && !o.isNull("trimExportMs")) o.optLong("trimExportMs") else null,
                trimVideoBitrateBps = if (o.has("trimVideoBitrateBps") && !o.isNull("trimVideoBitrateBps")) o.optLong("trimVideoBitrateBps") else null,
                sourceBytes = if (o.has("sourceBytes") && !o.isNull("sourceBytes")) o.optLong("sourceBytes") else null,
                preparedBytes = if (o.has("preparedBytes") && !o.isNull("preparedBytes")) o.optLong("preparedBytes") else null,
                trimConfirmedNs = o.optLong("trimConfirmedNs"),
                trimConfirmedBootId = o.optString("trimConfirmedBootId"),
                pollCount = if (o.has("pollCount") && !o.isNull("pollCount"))
                    o.optInt("pollCount") else null,
                phaseMs = o.optJSONObject("phaseMs")?.let { phases ->
                    phases.keys().asSequence().associateWith { phases.optLong(it) }
                } ?: emptyMap(),
            )
        }.toMutableList()
    }

    @Synchronized private fun write(context: Context, rows: List<Attempt>) {
        // Measurement must never take an upload or rendered result down.
        runCatching {
            val array = JSONArray()
            rows.takeLast(LIMIT).forEach { a ->
                val row = JSONObject()
                    .put("attemptId", a.attemptId).put("bootId", a.bootId)
                    .put("startedNs", a.startedNs).put("completeOrigin", a.completeOrigin)
                    .put("jobId", a.jobId)
                    .put("submittedNs", a.submittedNs).put("resultNs", a.resultNs)
                    .put("renderedNs", a.renderedNs).put("wallStartedMs", a.wallStartedMs)
                    .put("wallRenderedMs", a.wallRenderedMs).put("traceId", a.traceId)
                    .put("countStatus", a.countStatus).put("repCount", a.repCount)
                    .put("preparationMs", a.preparationMs).put("trimExportMs", a.trimExportMs)
                    .put("trimVideoBitrateBps", a.trimVideoBitrateBps)
                    .put("sourceBytes", a.sourceBytes).put("preparedBytes", a.preparedBytes)
                    .put("trimConfirmedNs", a.trimConfirmedNs).put("trimConfirmedBootId", a.trimConfirmedBootId)
                    .put("phaseMs", JSONObject().apply { a.phaseMs.forEach { (key, value) -> put(key, value) } })
                a.pollCount?.let { row.put("pollCount", it) }
                array.put(row)
            }
            val target = file(context)
            val temp = File(context.filesDir, "round2-timings.json.tmp")
            temp.writeText(array.toString())
            if (!temp.renameTo(target)) {
                target.writeText(temp.readText())
                temp.delete()
            }
        }
    }

    @Synchronized fun begin(context: Context, attemptId: String, completeOrigin: Boolean = true) {
        val rows = read(context)
        val existing = rows.indexOfLast { it.attemptId == attemptId }
        if (existing >= 0) {
            if (rows[existing].startedNs == 0L) rows[existing] = rows[existing].copy(
                bootId = currentBootId(), startedNs = SystemClock.elapsedRealtimeNanos(),
                completeOrigin = completeOrigin, wallStartedMs = System.currentTimeMillis())
            write(context, rows)
            return
        }
        rows.add(Attempt(attemptId, currentBootId(), SystemClock.elapsedRealtimeNanos(),
            completeOrigin = completeOrigin,
            wallStartedMs = System.currentTimeMillis()))
        write(context, rows)
    }

    @Synchronized fun preparationDuration(context: Context, attemptId: String, durationMs: Long) =
        updateOrCreate(context, attemptId) { it.copy(preparationMs = durationMs.coerceAtLeast(0)) }

    @Synchronized fun trimExportDuration(context: Context, attemptId: String, durationMs: Long) =
        updateOrCreate(context, attemptId) { it.copy(trimExportMs = durationMs.coerceAtLeast(0)) }

    @Synchronized fun trimVideoBitrate(context: Context, attemptId: String, bitrateBps: Int?) =
        updateOrCreate(context, attemptId) {
            it.copy(trimVideoBitrateBps = bitrateBps?.takeIf { rate -> rate > 0 }?.toLong())
        }

    /** Retain original bytes across a resumed upload and record the exact file
     * sent to storage. A missing or empty file stays unavailable, not zero. */
    @Synchronized fun clipBytes(
        context: Context, attemptId: String, sourceBytes: Long, preparedBytes: Long,
    ) = updateOrCreate(context, attemptId) {
        it.copy(
            sourceBytes = it.sourceBytes?.takeIf { size -> size > 0 }
                ?: sourceBytes.takeIf { size -> size > 0 },
            preparedBytes = preparedBytes.takeIf { size -> size > 0 } ?: it.preparedBytes,
        )
    }

    @Synchronized fun phaseDuration(context: Context, attemptId: String, phase: String, durationMs: Long) =
        updateOrCreate(context, attemptId) {
            val key = phase.take(48)
            it.copy(phaseMs = it.phaseMs + (key to ((it.phaseMs[key] ?: 0L) + durationMs.coerceAtLeast(0L))))
        }

    @Synchronized fun trimConfirmed(
        context: Context, attemptId: String, confirmedNs: Long = SystemClock.elapsedRealtimeNanos(),
    ) = updateOrCreate(context, attemptId) {
        it.copy(trimConfirmedNs = confirmedNs, trimConfirmedBootId = currentBootId())
    }

    @Synchronized fun bindJob(context: Context, attemptId: String, jobId: String) = update(context, attemptId) {
        if (it.jobId.isNotBlank()) it else it.copy(jobId = jobId)
    }

    @Synchronized fun submitted(context: Context, attemptId: String) = update(context, attemptId) {
        if (it.submittedNs != 0L) it else it.copy(submittedNs = SystemClock.elapsedRealtimeNanos())
    }

    @Synchronized fun resultReceived(
        context: Context,
        attemptId: String,
        traceId: String,
        countStatus: String? = null,
        repCount: Int? = null,
        pollCount: Int = 0,
        pollGetMs: Long = 0,
        pollSleepMs: Long = 0,
        pollHandleMs: Long = 0,
    ) = update(context, attemptId) {
        if (it.resultNs != 0L) it else it.copy(
            resultNs = SystemClock.elapsedRealtimeNanos(), traceId = traceId,
            countStatus = countStatus, repCount = repCount,
            pollCount = pollCount.coerceAtLeast(0),
            phaseMs = it.phaseMs + mapOf(
                "pollGet" to pollGetMs.coerceAtLeast(0),
                "pollSleep" to pollSleepMs.coerceAtLeast(0),
                "pollHandle" to pollHandleMs.coerceAtLeast(0),
            ))
    }

    /** Called after Compose applies a valid result page; repeated renders are ignored. */
    @Synchronized fun rendered(
        context: Context, jobId: String, traceId: String, renderedNs: Long = SystemClock.elapsedRealtimeNanos(),
    ): Attempt? {
        val rows = read(context)
        val index = rows.indexOfLast { it.jobId == jobId && it.resultNs != 0L }
        if (index < 0) return null
        val old = rows[index]
        if (old.renderedNs != 0L) return old
        val updated = old.copy(renderedNs = renderedNs,
            wallRenderedMs = System.currentTimeMillis(), traceId = traceId.ifBlank { old.traceId })
        rows[index] = updated
        write(context, rows)
        return updated
    }

    private inline fun update(context: Context, attemptId: String, transform: (Attempt) -> Attempt) {
        val rows = read(context)
        val index = rows.indexOfLast { it.attemptId == attemptId }
        if (index < 0) return
        rows[index] = transform(rows[index])
        write(context, rows)
    }

    private inline fun updateOrCreate(context: Context, attemptId: String, transform: (Attempt) -> Attempt) {
        val rows = read(context)
        val index = rows.indexOfLast { it.attemptId == attemptId }
        if (index >= 0) rows[index] = transform(rows[index])
        else rows.add(transform(Attempt(attemptId, currentBootId(), 0L, completeOrigin = false)))
        write(context, rows)
    }
}

internal fun monotonicDurationMs(
    startedNs: Long,
    endedNs: Long,
    startBootId: String,
    endBootId: String,
    completeOrigin: Boolean = true,
): Long? = if (completeOrigin && startBootId.isNotBlank() && startBootId == endBootId && endedNs >= startedNs)
    (endedNs - startedNs) / 1_000_000 else null
