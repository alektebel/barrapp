package com.barrapp.data

import android.content.Context
import androidx.core.content.edit
import org.json.JSONArray
import org.json.JSONObject

/**
 * A ring buffer of what the app did, on the phone.
 *
 * The failures worth debugging are the ones nobody was watching: an upload that
 * died on a train, a job that came back empty overnight. Logcat is gone by the
 * time anyone asks and a crash reporter would not see these at all, because
 * none of them are crashes.
 *
 * So each one is written here with its trace id, and Diagnostics shows the
 * list. A report then names a specific run of a specific build rather than
 * "it didn't work".
 *
 * Bounded at [LIMIT] entries. It is a debugging aid, not an audit trail, and an
 * unbounded log in SharedPreferences would eventually be a performance bug of
 * its own.
 */
object EventLog {
    private const val PREFS = "barrapp_events"
    private const val KEY = "events"
    const val LIMIT = 120

    enum class Level { INFO, WARN, ERROR }

    data class Event(
        val at: Long,
        val level: Level,
        val what: String,
        val detail: String = "",
        val traceId: String = "",
        val jobId: String = "",
    ) {
        val line: String
            get() = buildString {
                append(what)
                if (detail.isNotBlank()) append(" — ").append(detail)
            }
    }

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun all(context: Context): List<Event> {
        val raw = prefs(context).getString(KEY, "[]").orEmpty()
        val arr = runCatching { JSONArray(raw) }.getOrElse { JSONArray() }
        return (0 until arr.length()).mapNotNull { arr.optJSONObject(it) }.map { o ->
            Event(
                at = o.optLong("at"),
                level = runCatching { Level.valueOf(o.optString("level")) }
                    .getOrDefault(Level.INFO),
                what = o.optString("what"),
                detail = o.optString("detail"),
                traceId = o.optString("traceId"),
                jobId = o.optString("jobId"),
            )
        }.reversed()          // newest first, which is the only order anyone reads
    }

    fun add(
        context: Context,
        level: Level,
        what: String,
        detail: String = "",
        traceId: String = "",
        jobId: String = "",
    ) {
        val kept = all(context).reversed().takeLast(LIMIT - 1) +
            Event(System.currentTimeMillis(), level, what, detail, traceId, jobId)
        val arr = JSONArray()
        kept.forEach {
            arr.put(
                JSONObject()
                    .put("at", it.at).put("level", it.level.name)
                    .put("what", it.what).put("detail", it.detail)
                    .put("traceId", it.traceId).put("jobId", it.jobId)
            )
        }
        prefs(context).edit { putString(KEY, arr.toString()) }
    }

    fun info(context: Context, what: String, detail: String = "",
             traceId: String = "", jobId: String = "") =
        add(context, Level.INFO, what, detail, traceId, jobId)

    fun warn(context: Context, what: String, detail: String = "",
             traceId: String = "", jobId: String = "") =
        add(context, Level.WARN, what, detail, traceId, jobId)

    fun error(context: Context, what: String, detail: String = "",
              traceId: String = "", jobId: String = "") =
        add(context, Level.ERROR, what, detail, traceId, jobId)

    fun forget(context: Context) {
        prefs(context).edit { putString(KEY, "[]") }
    }

    /** One block of text to paste into a bug report. Everything needed to
     *  reproduce, and nothing that identifies the athlete. */
    fun report(context: Context, deviceId: String, apiBase: String): String {
        val events = all(context).take(40)
        return buildString {
            appendLine("barrapp diagnostics")
            appendLine("device   $deviceId")
            appendLine("api      $apiBase")
            appendLine("android  ${android.os.Build.VERSION.SDK_INT} " +
                "(${android.os.Build.MANUFACTURER} ${android.os.Build.MODEL})")
            appendLine("events   ${events.size} of ${LIMIT} kept")
            appendLine()
            events.forEach { e ->
                append(java.text.SimpleDateFormat("MM-dd HH:mm:ss", java.util.Locale.UK)
                    .format(java.util.Date(e.at)))
                append("  ").append(e.level.name.padEnd(5)).append("  ").append(e.line)
                if (e.traceId.isNotBlank()) append("  [trace ${e.traceId}]")
                if (e.jobId.isNotBlank()) append("  [job ${e.jobId}]")
                appendLine()
            }
        }
    }
}
