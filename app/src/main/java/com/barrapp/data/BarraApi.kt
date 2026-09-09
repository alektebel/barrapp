package com.barrapp.data

import android.content.Context
import android.net.Uri
import com.barrapp.BuildConfig
import com.barrapp.DeviceId
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okio.BufferedSink
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class BarraApi(context: Context) {
    private val app = context.applicationContext
    private val deviceId = DeviceId.get(context)
    private val baseUrl = BuildConfig.API_BASE_URL.trimEnd('/')
    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .writeTimeout(120, TimeUnit.SECONDS)
        .build()

    /**
     * `variant` and `view` are DECLARATIONS the athlete makes, sent only when
     * made: the server never infers a technique standard from one posture,
     * and an unknown word comes back as `unspecified` with the word beside it
     * rather than switching on the wrong fault taxonomy.
     */
    fun createJob(exercise: String, variant: String? = null, view: String? = null): CreatedJob {
        val body = JSONObject()
            .put("exercise", exercise)
            .apply {
                variant?.takeIf { it.isNotBlank() }?.let { put("variant", it) }
                view?.takeIf { it.isNotBlank() }?.let { put("view", it) }
            }
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
        val mime = context.contentResolver.getType(uri) ?: "video/mp4"
        val url = if (uploadUrl.startsWith("http")) uploadUrl else "$baseUrl$uploadUrl"
        val cr = context.contentResolver
        val length = try {
            cr.openAssetFileDescriptor(uri, "r")?.use { it.length } ?: -1L
        } catch (_: Exception) { -1L }
        val body = object : RequestBody() {
            override fun contentType() = mime.toMediaType()
            override fun contentLength() = length
            override fun writeTo(sink: BufferedSink) {
                cr.openInputStream(uri)?.use { input ->
                    sink.outputStream().use { out -> input.copyTo(out) }
                } ?: error("Could not read video")
            }
        }
        val builder = Request.Builder()
            .url(url)
            .method(method, body)
        if (!isS3(url)) {
            builder.header("X-Device-Id", deviceId)
        }
        call(builder.build())
    }

    /** Upload a clip the phone already holds - the queue's own copy. The
     *  camera uri a work started from can expire mid-queue; a file cannot. */
    fun uploadClip(clip: java.io.File, uploadUrl: String, method: String) {
        val url = if (uploadUrl.startsWith("http")) uploadUrl else "$baseUrl$uploadUrl"
        val body = object : RequestBody() {
            override fun contentType() = "video/mp4".toMediaType()
            override fun contentLength() = clip.length()
            override fun writeTo(sink: BufferedSink) {
                clip.inputStream().use { input ->
                    sink.outputStream().use { out -> input.copyTo(out) }
                }
            }
        }
        val builder = Request.Builder().url(url).method(method, body)
        if (!isS3(url)) builder.header("X-Device-Id", deviceId)
        call(builder.build())
    }

    // ---- resumable upload: parts, etags, and a server that remembers ----

    data class PartSlot(val partNumber: Int, val etag: String?)

    /** A part already on the server, with the etag the server answered. */
    fun startUpload(jobId: String): Pair<String, Long> {
        val request = authed(
            Request.Builder().url("$baseUrl/v1/jobs/$jobId/upload/start")
                .post("{}".toRequestBody(JSON))
        ).build()
        val json = call(request)
        return json.optString("uploadId") to json.optLong("partSize", 8L * 1024 * 1024)
    }

    fun presignPart(jobId: String, uploadId: String, partNumber: Int): String {
        val body = JSONObject().put("partNumber", partNumber).toString()
            .toRequestBody(JSON)
        val request = authed(
            Request.Builder().url("$baseUrl/v1/jobs/$jobId/upload/part")
                .post(body)
        ).build()
        return call(request).optString("url")
    }

    /** Send one part; returns the server's etag when it gives one. */
    fun putPart(url: String, clip: java.io.File, offset: Long, length: Long): String? {
        val resolved = if (url.startsWith("http")) url else "$baseUrl$url"
        val body = object : RequestBody() {
            // No Content-Type header at all: the presigned URL signs nothing
            // of it, and S3 rejects a signature computed over a header the
            // request then sends differently. Send nothing.
            override fun contentType(): okhttp3.MediaType? = null
            override fun contentLength() = length
            override fun writeTo(sink: BufferedSink) {
                clip.inputStream().use { input ->
                    input.skip(offset)
                    val buf = ByteArray(1 shl 20)
                    var remaining = length
                    while (remaining > 0) {
                        val n = input.read(buf, 0, minOf(buf.size.toLong(), remaining).toInt())
                        if (n < 0) break
                        sink.write(buf, 0, n)
                        remaining -= n
                    }
                }
            }
        }
        val builder = Request.Builder().url(resolved).put(body)
        if (!isS3(resolved)) builder.header("X-Device-Id", deviceId)
        client.newCall(builder.build()).execute().use { response ->
            if (!response.isSuccessful) error("part upload failed: HTTP ${response.code}")
            return response.header("ETag")
                ?: response.header("etag")
        }
    }

    fun completeUpload(jobId: String, parts: List<PartSlot>) {
        val arr = JSONArray()
        parts.sortedBy { it.partNumber }.forEach {
            arr.put(JSONObject().put("partNumber", it.partNumber)
                .put("etag", it.etag ?: "${it.partNumber}"))
        }
        val body = JSONObject().put("parts", arr).toString().toRequestBody(JSON)
        val request = authed(
            Request.Builder().url("$baseUrl/v1/jobs/$jobId/upload/complete")
                .post(body)
        ).build()
        call(request)
    }

    fun abortUpload(jobId: String) {
        val request = authed(
            Request.Builder().url("$baseUrl/v1/jobs/$jobId/upload/abort")
                .post("{}".toRequestBody(JSON))
        ).build()
        runCatching { call(request) }
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

    /** The device's stored history: every finished job with its result. This
     *  is how the calendar survives a cleared app - the measurements live on
     *  the server, the clips do not. */
    fun history(): List<Job> {
        val request = authed(Request.Builder().url("$baseUrl/v1/history").get()).build()
        val json = call(request)
        val items = json.optJSONArray("history") ?: JSONArray()
        return (0 until items.length()).map { parseJob(items.getJSONObject(it)) }
    }

    fun deleteJob(jobId: String) {
        val request = authed(Request.Builder().url("$baseUrl/v1/jobs/$jobId").delete()).build()
        call(request)
    }

    /** Send one conversation turn of the objectives intake. `messages` is the
     *  running chat as role/content pairs, oldest first. */
    fun chat(messages: List<Pair<String, String>>): ChatResult {
        val arr = JSONArray()
        messages.forEach { (role, content) ->
            arr.put(JSONObject().put("role", role).put("content", content))
        }
        val body = JSONObject().put("messages", arr).toString().toRequestBody(JSON)
        val request = authed(Request.Builder().url("$baseUrl/v1/chat").post(body)).build()
        val json = call(request)
        val goalsJson = json.optJSONObject("goals")
        return ChatResult(
            reply = json.optString("reply"),
            goals = goalsJson?.let { g ->
                Goals(
                    name = g.optString("name"),
                    age = g.optInt("age"),
                    activity = g.optString("activity"),
                    goal = g.optString("goal"),
                    focusExercise = g.optString("focusExercise"),
                )
            },
        )
    }

    /** Every call to our own API carries an identity.
     *
     *  Signed in, that is the bearer token and the server answers with the
     *  account's history. Signed out, it is the device id, exactly as before
     *  accounts existed. The device id is sent either way so a claim can name
     *  this phone without a second round trip.
     *
     *  The access token lasts an hour, so it is refreshed here rather than at
     *  every call site - a token that goes stale mid-session must not surface
     *  as "sign in again" while a valid refresh token is sitting on disk. */
    private fun authed(builder: Request.Builder): Request.Builder {
        builder.header("X-Device-Id", deviceId)
        val session = AuthStore.session(app) ?: return builder
        val token = if (session.expired) refreshed(session) else session.accessToken
        if (token.isNotBlank()) builder.header("Authorization", "Bearer $token")
        return builder
    }

    /** Swap the refresh token for a new access token. Returns blank when the
     *  refresh itself fails, which leaves the request to go out as the device
     *  - the caller sees their anonymous history rather than an error. */
    private fun refreshed(session: AuthStore.Session): String = runCatching {
        val body = JSONObject().put("refreshToken", session.refreshToken)
            .toString().toRequestBody(JSON)
        val json = call(
            Request.Builder().url("$baseUrl/v1/auth/refresh").post(body).build())
        val token = json.optString("accessToken")
        if (token.isNotBlank()) {
            AuthStore.save(app, token, json.optString("refreshToken").ifBlank { null },
                json.optLong("expiresIn", 3600), null)
        }
        token
    }.getOrDefault("")

    // ---- accounts ---------------------------------------------------------

    private fun authPost(action: String, fields: Map<String, String>): JSONObject {
        val payload = JSONObject()
        fields.forEach { (k, v) -> payload.put(k, v) }
        return call(
            Request.Builder().url("$baseUrl/v1/auth/$action")
                .post(payload.toString().toRequestBody(JSON))
                .header("X-Device-Id", deviceId)
                .build()
        )
    }

    /** Create the account. The server sends a code; nothing is signed in yet. */
    fun signUp(email: String, password: String) {
        authPost("signup", mapOf("email" to email, "password" to password))
    }

    fun confirm(email: String, code: String) {
        authPost("confirm", mapOf("email" to email, "code" to code))
    }

    fun resendCode(email: String) {
        authPost("resend", mapOf("email" to email))
    }

    fun forgotPassword(email: String) {
        authPost("forgot", mapOf("email" to email))
    }

    fun resetPassword(email: String, code: String, password: String) {
        authPost("reset", mapOf("email" to email, "code" to code, "password" to password))
    }

    /** Sign in and persist the session. */
    fun signIn(email: String, password: String) {
        val json = authPost("login", mapOf("email" to email, "password" to password))
        AuthStore.save(
            app,
            accessToken = json.optString("accessToken"),
            refreshToken = json.optString("refreshToken").ifBlank { null },
            expiresIn = json.optLong("expiresIn", 3600),
            email = email,
        )
    }

    /** Move this phone's anonymous sessions onto the signed-in account.
     *  Returns how many moved. */
    fun claimDevice(): Int {
        val body = JSONObject().put("deviceId", deviceId).toString().toRequestBody(JSON)
        val request = authed(
            Request.Builder().url("$baseUrl/v1/auth/claim").post(body)).build()
        return call(request).optInt("claimed")
    }

    fun deviceId(): String = deviceId

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
                error = json.textOrNull("error"),
                stage = json.optString("stage"),
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
                        startS = row.optDouble("startS", 0.0).orZero(),
                        endS = row.optDouble("endS", 0.0).orZero(),
                        turnS = row.optDouble("turnS", 0.0).orZero(),
                        // Absent means "not measurable", which is not the same
                        // as zero and must never be drawn as a bad rep.
                        score = if (row.isNull("score")) null else row.optInt("score"),
                        band = row.optString("band").ifBlank { "unmeasured" },
                        scoreNote = row.optString("scoreNote"),
                        complete = row.optBoolean("complete", true),
                        components = row.optJSONArray("components").mapObjects { c ->
                            ScorePart(
                                name = c.optString("name"),
                                value = if (c.isNull("value")) null else c.optDouble("value").orZero(),
                                weight = c.optDouble("weight", 0.0).orZero(),
                                why = c.optString("why"),
                            )
                        },
                        asides = row.optJSONArray("aside").mapObjects { a ->
                            Aside(
                                name = a.optString("name"),
                                value = a.optDouble("value", 0.0).orZero(),
                                why = a.optString("why"),
                            )
                        },
                        penalties = row.optJSONArray("penalties").mapObjects { p ->
                            ScorePart(
                                name = p.optString("name"),
                                value = if (p.isNull("value")) null else p.optDouble("value").orZero(),
                                weight = p.optDouble("weight", 0.0).orZero(),
                                why = p.optString("why"),
                            )
                        },
                        trace = row.optJSONArray("trace").let { t ->
                            if (t == null) emptyList()
                            else (0 until t.length()).map { i -> t.optDouble(i, 0.0).toFloat() }
                        },
                        faults = row.optJSONArray("faults").mapObjects { f ->
                            MeasuredFault(
                                name = f.optString("name"),
                                primitive = f.optString("primitive"),
                                value = if (f.isNull("value")) null else f.optDouble("value").orZero(),
                                threshold = f.optDouble("threshold", 0.0).orZero(),
                                comparison = f.optString("comparison"),
                                unit = f.optString("unit"),
                                cls = f.optString("class"),
                                errorId = f.optString("errorId"),
                                phase = f.optString("phase"),
                                intervalS = f.optJSONArray("intervalS").doubles(),
                            )
                        },
                        unmeasured = row.optJSONArray("unmeasured").strings(),
                        viewBlocked = row.optJSONArray("viewBlocked").strings(),
                        assessments = row.optJSONArray("assessments").mapObjects { a ->
                            val ev = a.optJSONObject("evidence")
                            val avail = a.optJSONObject("availability")
                            Assessment(
                                errorId = a.optString("errorId"),
                                name = a.optString("name"),
                                phase = a.optString("phase"),
                                status = a.optString("status"),
                                intervalS = a.optJSONArray("intervalS").doubles(),
                                value = if (ev == null || ev.isNull("value")) null
                                        else ev.optDouble("value").orZero(),
                                threshold = ev?.optDouble("threshold", 0.0)?.orZero() ?: 0.0,
                                comparison = ev?.optString("comparison").orEmpty(),
                                unit = ev?.optString("unit").orEmpty(),
                                reason = avail?.optString("reason").orEmpty(),
                                reasonDetail = avail?.optString("detail").orEmpty(),
                                variantDependent = a.optBoolean("variantDependent", false),
                                source = a.optString("source").ifBlank { Assessment.SOURCE_GEOMETRY },
                            )
                        },
                        phases = row.optJSONObject("phases")?.let { p ->
                            p.keys().asSequence().associateWith { k -> p.optJSONArray(k).doubles() }
                        } ?: emptyMap(),
                        assessmentBlocked = row.textOrNull("assessmentBlocked"),
                    )
                },
                blockers = (0 until blockers.length()).map { blockers.getString(it) },
                nextSession = json.optString("nextSession"),
                exercise = json.optString("exercise"),
                detected = json.optJSONObject("detected")?.let { d ->
                    Detected(
                        exercise = d.optString("exercise"),
                        label = d.optString("label"),
                        confidence = d.optDouble("confidence", 0.0).orZero(),
                        reason = d.optString("reason"),
                        runnerUp = d.textOrNull("runnerUp"),
                        certainty = d.optString("certainty")
                            .ifBlank { Detected.MARGIN_TO_THRESHOLD },
                    )
                },
                model = json.optJSONObject("model")?.let { mm ->
                    ModelVerdict(
                        classification = mm.optJSONObject("classification")?.let { c ->
                            ModelClassification(
                                exercise = c.optString("exercise"),
                                confidence = c.optDouble("confidence", 0.0).orZero(),
                                runnerUp = c.textOrNull("runnerUp"),
                                marginToRunnerUp = c.optDouble("marginToRunnerUp", 0.0).orZero(),
                                probabilities = c.optJSONObject("probabilities")
                                    .toDoubleMap(),
                                modelVersion = c.optString("model"),
                            )
                        },
                        load = mm.optJSONObject("load")?.let { l ->
                            LoadEstimate(
                                kg = l.optDouble("kg", 0.0).orZero(),
                                estimated = l.optBoolean("estimated", false),
                                note = l.optString("note"),
                            )
                        },
                    )
                },
                trim = json.optJSONObject("trim")?.let { t ->
                    Trim(t.optDouble("startS", 0.0).orZero(), t.optDouble("endS", 0.0).orZero())
                },
                sessionDate = json.optString("session"),
                sessionScore = if (json.isNull("sessionScore")) null else json.optInt("sessionScore"),
                sessionBand = json.optString("sessionBand").ifBlank { "unmeasured" },
                repCount = json.optInt("n_reps"),
                candidateCount = json.optInt("n_candidates"),
                durationS = json.optDouble("duration_s", 0.0).orZero(),
                traceId = json.optString("traceId"),
                provenance = json.optJSONObject("provenance")?.let { p ->
                    Provenance(
                        barra = p.optString("barra"),
                        commit = p.optString("commit"),
                        python = p.optString("python"),
                        platform = p.optString("platform"),
                        poseModel = p.optJSONObject("poseModel")
                            ?.optString("sha256_12").orEmpty(),
                    )
                },
                variant = json.optJSONObject("variant")?.let { v ->
                    Variant(
                        name = v.optString("name").ifBlank { Variant.UNSPECIFIED },
                        source = v.optString("source").ifBlank { "none" },
                        declared = v.textOrNull("declared"),
                    )
                } ?: Variant(),
                measurementVersion = json.optInt("measurementVersion", 0),
                checks = json.optJSONObject("assessment")
                    ?.optJSONArray("checks").mapObjects { c ->
                        CheckSummary(
                            errorId = c.optString("errorId"),
                            name = c.optString("name"),
                            phase = c.optString("phase"),
                            observed = c.optInt("observed"),
                            notObserved = c.optInt("notObserved"),
                            unobservable = c.optInt("unobservable"),
                        )
                    },
                visionObservations = json.optJSONArray("visionObservations").mapObjects { o ->
                    VisionObservation(
                        rep = o.optString("rep"),
                        errorId = o.optString("errorId"),
                        name = o.optString("name"),
                        phase = o.optString("phase"),
                        status = o.optString("status"),
                        description = o.optString("description"),
                        frames = o.optJSONArray("frames").strings(),
                    )
                },
                visionDisagreesOnMovement = json.optJSONObject("visionMovement")
                    ?.optBoolean("review", false) ?: false,
            )
        }

        /** JSONObject.optDouble returns NaN for a missing key, which then
         *  propagates silently into every arithmetic result downstream. */
        private fun Double.orZero(): Double = if (isNaN() || isInfinite()) 0.0 else this

        /** A string the server may send as JSON `null`. `optString` renders
         *  that as the four letters "null", which then reads as a real reason
         *  ("not judged — null"); this reads it as absent. */
        private fun JSONObject.textOrNull(key: String): String? =
            if (isNull(key)) null else optString(key).ifBlank { null }

        private fun <T> JSONArray?.mapObjects(block: (JSONObject) -> T): List<T> {
            if (this == null) return emptyList()
            return (0 until length()).mapNotNull { optJSONObject(it) }.map(block)
        }

        private fun JSONArray?.strings(): List<String> {
            if (this == null) return emptyList()
            return (0 until length()).mapNotNull { optString(it).ifBlank { null } }
        }

        /** A JSON array of numbers; a null or non-numeric entry drops the
         *  whole list rather than inventing a 0.0 endpoint. */
        private fun JSONArray?.doubles(): List<Double> {
            if (this == null) return emptyList()
            val out = (0 until length()).map { optDouble(it, Double.NaN) }
            return if (out.any { it.isNaN() }) emptyList() else out
        }

        /** A JSON object of numbers (e.g. the model's class probabilities). */
        private fun JSONObject?.toDoubleMap(): Map<String, Double> {
            if (this == null) return emptyMap()
            val out = LinkedHashMap<String, Double>()
            keys().forEach { k ->
                val v = optDouble(k, Double.NaN)
                if (!v.isNaN()) out[k] = v
            }
            return out
        }

        fun sampleFromAssets(context: Context): Analysis {
            val text = context.assets.open("sample_report.json").bufferedReader().use { it.readText() }
            return parseAnalysis(JSONObject(text))
        }
    }
}
