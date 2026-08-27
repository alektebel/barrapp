package com.barrapp.data

import android.content.Context
import android.net.Uri
import com.barrapp.BuildConfig
import com.barrapp.DeviceId
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class BarraApi(context: Context) {
    private val deviceId = DeviceId.get(context)
    private val baseUrl = BuildConfig.API_BASE_URL.trimEnd('/')
    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .writeTimeout(120, TimeUnit.SECONDS)
        .build()

    fun createJob(exercise: String): CreatedJob {
        val body = JSONObject()
            .put("exercise", exercise)
            .toString()
            .toRequestBody(JSON)
        val request = authed(Request.Builder().url("$baseUrl/v1/jobs").post(body)).build()
        val json = call(request)
        return CreatedJob(
            job = parseJob(json),
            uploadUrl = json.optString("uploadUrl"),
            uploadMethod = json.optString("uploadMethod", "PUT"),
        )
    }

    fun uploadVideo(context: Context, uploadUrl: String, method: String, uri: Uri) {
        val bytes = context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
            ?: error("Could not read video")
        val mime = context.contentResolver.getType(uri) ?: "video/mp4"
        val url = if (uploadUrl.startsWith("http")) uploadUrl else "$baseUrl$uploadUrl"
        val builder = Request.Builder()
            .url(url)
            .method(method, bytes.toRequestBody(mime.toMediaType()))
        if (!isS3(url)) {
            builder.header("X-Device-Id", deviceId)
        }
        call(builder.build())
    }

    fun submit(jobId: String): Job {
        val request = authed(
            Request.Builder().url("$baseUrl/v1/jobs/$jobId/submit").post("{}".toRequestBody(JSON))
        ).build()
        return parseJob(call(request))
    }

    fun getJob(jobId: String): Job {
        val request = authed(Request.Builder().url("$baseUrl/v1/jobs/$jobId").get()).build()
        return parseJob(call(request))
    }

    fun listJobs(): List<Job> {
        val request = authed(Request.Builder().url("$baseUrl/v1/jobs").get()).build()
        val json = call(request)
        val items = json.optJSONArray("jobs") ?: JSONArray()
        return (0 until items.length()).map { parseJob(items.getJSONObject(it)) }
    }

    fun deleteJob(jobId: String) {
        val request = authed(Request.Builder().url("$baseUrl/v1/jobs/$jobId").delete()).build()
        call(request)
    }

    private fun authed(builder: Request.Builder): Request.Builder =
        builder.header("X-Device-Id", deviceId)

    private fun isS3(url: String): Boolean =
        url.contains(".amazonaws.com") || url.contains(".s3.")

    private fun call(request: Request): JSONObject {
        client.newCall(request).execute().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                val message = runCatching { JSONObject(text).optString("error") }
                    .getOrNull()
                    ?.ifBlank { null }
                    ?: text.ifBlank { "HTTP ${response.code}" }
                error(message)
            }
            return if (text.isBlank()) JSONObject() else JSONObject(text)
        }
    }

    companion object {
        private val JSON = "application/json; charset=utf-8".toMediaType()

        fun parseJob(json: JSONObject): Job {
            val resultJson = json.optJSONObject("result")
            return Job(
                id = json.optString("id"),
                status = json.optString("status"),
                exercise = json.optString("exercise"),
                createdAt = json.optString("createdAt"),
                error = json.optString("error").ifBlank { null },
                result = resultJson?.let { parseAnalysis(it) },
            )
        }

        fun parseAnalysis(json: JSONObject): Analysis {
            val sessions = json.optJSONArray("sessions") ?: JSONArray()
            val reps = json.optJSONArray("reps") ?: JSONArray()
            val blockers = json.optJSONArray("blockers") ?: JSONArray()
            return Analysis(
                headline = json.optString("headline"),
                narrative = json.optString("narrative"),
                sessions = (0 until sessions.length()).map {
                    val row = sessions.getJSONObject(it)
                    SessionRow(
                        date = row.optString("date"),
                        reps = row.optInt("reps"),
                        note = row.optString("note"),
                    )
                },
                reps = (0 until reps.length()).map {
                    val row = reps.getJSONObject(it)
                    val metricsJson = row.optJSONArray("metrics") ?: JSONArray()
                    val problemsJson = row.optJSONArray("problems") ?: JSONArray()
                    RepRow(
                        session = row.optString("session"),
                        label = row.optString("label"),
                        transitionS = row.optString("transition_s"),
                        totalS = row.optString("total_s"),
                        cls = row.optString("class"),
                        metrics = (0 until metricsJson.length()).map { m ->
                            val line = metricsJson.getJSONObject(m)
                            MetricLine(
                                name = line.optString("name"),
                                value = line.optString("value"),
                                cls = line.optString("class"),
                            )
                        },
                        problems = (0 until problemsJson.length()).map { problemsJson.getString(it) },
                        plausible = row.optBoolean("plausible", true),
                    )
                },
                blockers = (0 until blockers.length()).map { blockers.getString(it) },
                nextSession = json.optString("nextSession"),
            )
        }

        fun sampleFromAssets(context: Context): Analysis {
            val text = context.assets.open("sample_report.json").bufferedReader().use { it.readText() }
            return parseAnalysis(JSONObject(text))
        }
    }
}
