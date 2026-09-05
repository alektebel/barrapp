package com.barrapp.data

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * A work: one clip on its way to becoming a session.
 *
 * Several can be in flight at once, so the wait is a list rather than a
 * screen. Each carries its own log — created, sent, queued, each server
 * stage, and, when a work goes wrong, the exact step it was on and why.
 * The log is the difference between "it failed" and a sentence a person can
 * act on, which is why it survives the process: the phone may be killed
 * while a clip is mid-flight, and the reason must still be there.
 *
 * Bounded at [MAX_WORKS] works and [LOG_LIMIT] entries each: a queue, not an
 * archive — finished works become sessions in the calendar, failed ones stay
 * until retried or dismissed.
 */
/** One clip on its way to being a session. Lives at the top level because the
 *  queue, the works list and the log screen all speak in it. */
data class Work(
    val id: String,             // local id, fixed at enqueue time
    val createdAt: Long,
    val status: String,
    val jobId: String = "",     // the server's name for it, once known
    val stage: String = "",     // where the work is, in words
    val exercise: String = "",  // what it turned out to be, when done
    val error: String? = null,
    val traceId: String = "",
    val clipPath: String = "",  // the phone's copy, for retry and replay
    val log: List<WorkStore.Entry> = emptyList(),
) {
    val active: Boolean
        get() = status in setOf(
            WorkStore.STATUS_WAITING, WorkStore.STATUS_SENDING,
            WorkStore.STATUS_QUEUED, WorkStore.STATUS_MEASURING)

    /** One line for the list: the stage when it means something, the error
     *  when there is one, the plain status otherwise. */
    val line: String
        get() = when {
            status == WorkStore.STATUS_FAILED && !error.isNullOrBlank() -> error.orEmpty()
            stage.isNotBlank() -> stage
            else -> status
        }
}

object WorkStore {
    const val STATUS_WAITING = "waiting"        // known locally, not yet sent
    const val STATUS_SENDING = "sending"        // upload in flight
    const val STATUS_QUEUED = "queued"          // the server holds the clip
    const val STATUS_MEASURING = "measuring"    // the server's worker is running
    const val STATUS_DONE = "done"
    const val STATUS_FAILED = "failed"

    const val MAX_WORKS = 12
    const val LOG_LIMIT = 80

    enum class Level { INFO, WARN, ERROR }

    data class Entry(
        val at: Long,
        val level: Level,
        val message: String,
    )

    private fun file(context: Context) = File(context.filesDir, "works.json")

    private fun read(context: Context): MutableList<Work> {
        val raw = runCatching { file(context).readText() }.getOrNull().orEmpty()
        val arr = runCatching { JSONArray(raw) }.getOrElse { return mutableListOf() }
        return (0 until arr.length()).mapNotNull { i ->
            val o = arr.optJSONObject(i) ?: return@mapNotNull null
            val logJson = o.optJSONArray("log") ?: JSONArray()
            Work(
                id = o.optString("id"),
                createdAt = o.optLong("createdAt"),
                status = o.optString("status", STATUS_FAILED),
                jobId = o.optString("jobId"),
                stage = o.optString("stage"),
                exercise = o.optString("exercise"),
                error = o.optString("error").ifBlank { null },
                traceId = o.optString("traceId"),
                clipPath = o.optString("clipPath"),
                log = (0 until logJson.length()).mapNotNull { j ->
                    val e = logJson.optJSONObject(j) ?: return@mapNotNull null
                    Entry(
                        at = e.optLong("at"),
                        level = runCatching { Level.valueOf(e.optString("level")) }
                            .getOrDefault(Level.INFO),
                        message = e.optString("message"),
                    )
                },
            )
        }.toMutableList()
    }

    private fun write(context: Context, works: List<Work>) {
        val arr = JSONArray()
        works.forEach { w ->
            val log = JSONArray()
            w.log.forEach { e ->
                log.put(JSONObject().put("at", e.at)
                    .put("level", e.level.name).put("message", e.message))
            }
            arr.put(JSONObject()
                .put("id", w.id).put("createdAt", w.createdAt).put("status", w.status)
                .put("jobId", w.jobId).put("stage", w.stage).put("exercise", w.exercise)
                .put("error", w.error.orEmpty()).put("traceId", w.traceId)
                .put("clipPath", w.clipPath).put("log", log))
        }
        file(context).writeText(arr.toString())
    }

    fun all(context: Context): List<Work> = read(context)

    fun get(context: Context, id: String): Work? =
        read(context).firstOrNull { it.id == id }

    /** Insert or replace by id, oldest last; the queue is short on purpose. */
    fun put(context: Context, work: Work) {
        val works = read(context).filterNot { it.id == work.id }.toMutableList()
        works.add(work)
        write(context, works.takeLast(MAX_WORKS))
    }

    /** One line into the work's own log, newest last. Never throws: a log
     *  that cannot be written must not take the work down with it. */
    fun append(context: Context, id: String, level: Level, message: String) {
        runCatching {
            val works = read(context)
            val i = works.indexOfFirst { it.id == id }
            if (i < 0) return
            val w = works[i]
            works[i] = w.copy(log = (w.log + Entry(System.currentTimeMillis(), level, message))
                .takeLast(LOG_LIMIT))
            write(context, works)
        }
    }

    fun forget(context: Context, id: String) {
        runCatching {
            write(context, read(context).filterNot { it.id == id })
        }
    }
}
