package com.barrapp.upload

import android.app.Application
import android.content.Context
import android.os.SystemClock
import com.barrapp.BuildConfig
import com.barrapp.Progression
import com.barrapp.data.BarraApi
import com.barrapp.data.EventLog
import com.barrapp.data.Job
import com.barrapp.data.MULTIPART_UPLOAD_CONCURRENCY
import com.barrapp.data.PartMark
import com.barrapp.data.Round2TimingStore
import com.barrapp.data.SessionStore
import com.barrapp.data.Stage
import com.barrapp.data.Work
import com.barrapp.data.WorkStore
import com.barrapp.data.chooseUploadMode
import com.barrapp.data.uploadPartsBatched
import com.barrapp.notify.ProcessingNotifier
import com.barrapp.resultPollDelayMs
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext

/**
 * The clips on their way, from the phone to a measured result.
 *
 * Lives in the process, not on a screen: [UploadWorker] runs [drain] under
 * WorkManager, which keeps it going with the app closed and starts it again
 * when the system kills the process or the network comes back. A screen that
 * is open follows [works] and [finished]; none needs to be.
 */
class UploadQueue private constructor(private val app: Application) {
    private val api = BarraApi(app)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val drainLock = Mutex()
    /** Sólo un clip a la vez se recorta y se sube (comparten el ancho de banda
     *  del móvil); en cuanto está en el servidor suelta la puerta y el
     *  siguiente empieza mientras el primero se mide. */
    private val uploadGate = Mutex()
    private val retryLogMutex = Mutex()

    /** Quién corta el clip. Real en producción, fake en las pruebas unitarias
     *  de la decisión (la vía real del Transformer necesita un dispositivo). */
    internal var trimmer: com.barrapp.media.ClipTrimmer =
        com.barrapp.media.DefaultClipTrimmer(app)

    private val _works = MutableStateFlow(WorkStore.all(app))
    val works: StateFlow<List<Work>> = _works

    private val _finished = MutableSharedFlow<Job>(extraBufferCapacity = 8)
    /** A clip measured while this process was alive. */
    val finished: SharedFlow<Job> = _finished

    fun publish() {
        _works.value = WorkStore.all(app)
    }

    /** Make sure the worker will run: after a new clip, a retry, a
     *  confirmed trim, the network coming back, or the app opening. */
    fun kick() = UploadWorker.enqueue(app)

    /**
     * Run every waiting clip, oldest first, one at a time. Returns true when
     * something is left waiting for the network, so the worker asks to be run
     * again rather than calling it done.
     */
    suspend fun drain(): Boolean = drainLock.withLock {
        recoverInterrupted()
        // Paused for the network: the worker only runs with one, so go on.
        WorkStore.all(app).filter { it.status == WorkStore.STATUS_CONNECTING }.forEach { w ->
            WorkStore.put(app, w.copy(status = WorkStore.STATUS_WAITING,
                stage = Stage.WAITING.text, stageCode = Stage.WAITING.code,
                log = w.log + WorkStore.Entry(System.currentTimeMillis(),
                    WorkStore.Level.INFO, "vuelve la conexión: se reanuda la subida")))
        }
        publish()
        val tried = mutableSetOf<String>()
        // Varios clips a la vez en el servidor, no más de MAX_IN_FLIGHT (los
        // modelos de visión tienen cuota); la subida sigue siendo de una en
        // una. Los clips que lleguen mientras tanto se recogen en la vuelta.
        val inFlight = java.util.concurrent.atomic.AtomicInteger(0)
        val slots = kotlinx.coroutines.sync.Semaphore(MAX_IN_FLIGHT)
        kotlinx.coroutines.coroutineScope {
            while (true) {
                val next = WorkStore.all(app)
                    .filter { it.status == WorkStore.STATUS_WAITING && it.id !in tried }
                    .minByOrNull { it.createdAt }
                if (next != null) {
                    tried += next.id
                    inFlight.incrementAndGet()
                    // UNDISPATCHED: cada clip llega a la puerta de subida en
                    // el orden en que se eligió, el más antiguo primero.
                    launch(start = kotlinx.coroutines.CoroutineStart.UNDISPATCHED) {
                        try {
                            slots.withPermit { runWork(next) }
                        } finally {
                            inFlight.decrementAndGet()
                        }
                    }
                    continue
                }
                if (inFlight.get() == 0) break
                delay(500)
            }
        }
        val waiting = WorkStore.all(app).any { it.status == WorkStore.STATUS_CONNECTING }
        if (WorkStore.all(app).none { it.active }) ProcessingNotifier.cancel(app)
        waiting
    }

    private fun recoverInterrupted() {
    // A work still marked active is not running: drain holds the lock, so
    // it was mid-flight when the worker stopped or the process died -
    // swiped away, killed by the system, reinstalled. Closing the app
    // must not decide whether a clip gets measured, so every one of
    // them picks up where it was: a send resumes, a clip the server
    // already holds is waited for, not sent again. Only a clip that is
    // no longer on the phone becomes a failed work.
    WorkStore.all(app).filter { it.active && it.status != WorkStore.STATUS_WAITING }.forEach { w ->
        val clipKept = java.io.File(w.clipPath).let { it.exists() && it.length() > 0L }
        if (clipKept && WorkStore.waitsOnServerAfterRestart(w)) {
            WorkStore.put(app, w.copy(
                status = WorkStore.STATUS_WAITING, uploadComplete = true,
                stage = Stage.RESUMING.text, stageCode = Stage.RESUMING.code,
            ).let { it.copy(log = it.log + WorkStore.Entry(
                System.currentTimeMillis(), WorkStore.Level.INFO,
                "la app se cerró mientras el trabajo ${w.jobId} estaba en el servidor: " +
                    "se espera su resultado, no se reenvía")) })
        } else if (clipKept && !WorkStore.resumesUploadAfterRestart(w)) {
            // Nothing of it reached the server in a form worth keeping:
            // send it from the start, as Retry would, without asking.
            WorkStore.put(app, w.copy(
                status = WorkStore.STATUS_WAITING, error = null,
                stage = Stage.RESUMING.text, stageCode = Stage.RESUMING.code,
                traceId = "", jobId = "", uploadId = "", partSize = 0,
                uploadedParts = emptyList(), uploadMode = "", uploadComplete = false,
            ).let { it.copy(log = it.log + WorkStore.Entry(
                System.currentTimeMillis(), WorkStore.Level.INFO,
                "la app se cerró antes de enviar el clip: se envía de nuevo")) })
        } else if (WorkStore.resumesUploadAfterRestart(w)) {
            // Multipart parts already sent remain on the server. A single
            // PUT can safely replace the fixed object using a fresh URL.
            WorkStore.put(app, w.copy(
                status = WorkStore.STATUS_WAITING,
                stage = Stage.RESUMING.text, stageCode = Stage.RESUMING.code,
            ).let { it.copy(log = it.log + WorkStore.Entry(
                System.currentTimeMillis(), WorkStore.Level.INFO,
                "la app se cerró durante la subida: ${w.uploadedParts.size} " +
                    "parte${if (w.uploadedParts.size == 1) "" else "s"} a salvo; se reanuda desde ahí")) })
        } else {
            WorkStore.put(app, w.copy(
                status = WorkStore.STATUS_FAILED,
                stage = "",
                error = "La app se cerró mientras este vídeo estaba en la cola.",
            ).let { it.copy(log = it.log + WorkStore.Entry(
                System.currentTimeMillis(), WorkStore.Level.WARN,
                "interrumpido: la app se cerró; pulsa Reintentar para enviarlo de nuevo")) })
        }
    }
    }

    private fun clipFile(app: Application, jobId: String): java.io.File =
        java.io.File(java.io.File(app.filesDir, "clips"), "$jobId.mp4")

    /** Transient network failures - an unresolvable host on weak wifi above
     *  all - are not a dead clip, they are a moment. Tried again here, with a
     *  growing pause, before the work is allowed to fail; every attempt is in
     *  the work's log, so a later "why did this take a while" has an answer. */
    private suspend fun <T> withRetry(
        what: String,
        workId: String,
        attempts: Int = 5,
        block: suspend () -> T,
    ): T {
        var last: Exception? = null
        repeat(attempts) { i ->
            try {
                return block()
            } catch (err: kotlinx.coroutines.CancellationException) {
                throw err
            } catch (err: Exception) {
                last = err
                val transient = err.message?.contains("resolve host", ignoreCase = true) == true ||
                    err.message?.contains("Failed to connect", ignoreCase = true) == true ||
                    err.message?.contains("timeout", ignoreCase = true) == true ||
                    err.message?.contains("unknown job", ignoreCase = true) == true ||
                    err.message?.contains("500", ignoreCase = true) == true ||
                    err.message?.contains("502", ignoreCase = true) == true ||
                    err.message?.contains("503", ignoreCase = true) == true ||
                    err is java.io.IOException
                retryLogMutex.withLock {
                    WorkStore.append(app, workId, WorkStore.Level.WARN,
                        "$what falló (intento ${i + 1} de $attempts): ${err.message.orEmpty()}")
                }
                if (!transient || i == attempts - 1) throw err
                delay(2500L * (i + 1))
            }
        }
        throw last ?: IllegalStateException("unreachable")
    }

    /** Raised when the network died mid-upload; handled locally, never shown
     *  as a failure. */
    private class PauseUpload : Exception("paused for network")

    private suspend fun <T> timedRound2Phase(
        attemptId: String,
        phase: String,
        block: suspend () -> T,
    ): T {
        val startedNs = SystemClock.elapsedRealtimeNanos()
        try {
            return block()
        } finally {
            val elapsedMs = ((SystemClock.elapsedRealtimeNanos() - startedNs) / 1_000_000L).coerceAtLeast(0L)
            withContext(Dispatchers.IO) {
                Round2TimingStore.phaseDuration(app, attemptId, phase, elapsedMs)
            }
        }
    }

    /** The upload, part by part, resumable from exactly where it stopped.
     *
     * Every finished part is persisted with its etag the moment the server
     * acknowledges it, so a tunnel, a lift, or the app being killed costs one
     * part - never the clip.
     *
     * Two ids, and they are not interchangeable: [workId] names the row in
     * the local queue, [jobId] is what the server calls this clip. Every
     * upload endpoint is addressed by the job id - passing the local one
     * gets "unknown job" back on the very first part. */
    private suspend fun uploadResumable(
        workId: String,
        jobId: String,
        clip: java.io.File,
        onProgress: (Int, Int) -> Unit,
    ) {
                val current = WorkStore.get(app, workId)
        val timingAttemptId = current?.timingAttemptId?.ifBlank { workId } ?: workId
        var uploadId = current?.uploadId.orEmpty()
        var partSize = current?.partSize ?: 0L
        val done = LinkedHashMap<Int, String?>()
        current?.uploadedParts?.forEach { done[it.partNumber] = it.etag }

        if (uploadId.isBlank() || partSize <= 0L) {
            val (id, ps) = timedRound2Phase(timingAttemptId, "multipartStart") {
                withRetry("iniciar la subida", workId) {
                    withContext(Dispatchers.IO) { api.startUpload(jobId) }
                }
            }
            uploadId = id
            partSize = ps
            WorkStore.put(app, WorkStore.get(app, workId)!!.copy(uploadId = id, partSize = ps))
        }

        val total = (((clip.length() + partSize - 1) / partSize).toInt()).coerceAtLeast(1)
        var sent = done.size
        val missing = (1..total).filterNot { done.containsKey(it) }
        for (batch in missing.chunked(MULTIPART_UPLOAD_CONCURRENCY)) {
            // Prepare URLs and stream bytes in bounded parallel batches.
            // Successful sibling parts are persisted before an error pauses
            // the upload; a resume only resends missing part numbers.
            val urls = mutableMapOf<Int, String>()
            try {
                timedRound2Phase(timingAttemptId, "presign") {
                    uploadPartsBatched(batch, MULTIPART_UPLOAD_CONCURRENCY, uploadPart = { n ->
                        withRetry("preparar la parte $n de $total", workId) {
                            withContext(Dispatchers.IO) { api.presignPart(jobId, uploadId, n) }
                        }
                    }) { n, url ->
                        urls[n] = requireNotNull(url)
                    }
                }
                timedRound2Phase(timingAttemptId, "partTransfer") {
                    uploadPartsBatched(batch, MULTIPART_UPLOAD_CONCURRENCY, uploadPart = { n ->
                        val offset = (n - 1L) * partSize
                        val length = minOf(partSize, clip.length() - offset)
                        withContext(Dispatchers.IO) {
                            api.putPart(urls.getValue(n), clip, offset, length)
                        }
                    }) { n, etag ->
                        done[n] = etag
                        sent++
                        onProgress(sent.coerceAtMost(total), total)
                        WorkStore.put(app, WorkStore.get(app, workId)!!.copy(
                            uploadedParts = done.map { PartMark(it.key, it.value) },
                            stage = Stage.sending(sent.coerceAtMost(total), total),
                            stageCode = Stage.SENDING.code))
                        publish()
                    }
                }
            } catch (err: kotlinx.coroutines.CancellationException) {
                throw err
            } catch (err: Exception) {
                val transient = err.message?.contains("resolve host", ignoreCase = true) == true ||
                    err.message?.contains("Failed to connect", ignoreCase = true) == true ||
                    err.message?.contains("timeout", ignoreCase = true) == true ||
                    err is java.io.IOException
                if (!transient) throw err
                WorkStore.put(app, WorkStore.get(app, workId)!!.copy(
                    status = WorkStore.STATUS_CONNECTING,
                    stage = Stage.connecting(done.size, total), stageCode = Stage.CONNECTING.code,
                    uploadedParts = done.map { PartMark(it.key, it.value) },
                        log = (WorkStore.get(app, workId)?.log ?: emptyList()) +
                        WorkStore.Entry(System.currentTimeMillis(), WorkStore.Level.WARN,
                            "se perdió la conexión durante las partes ${batch.joinToString()} de $total: " +
                                "${done.size} ya están en el servidor")))
                publish()
                throw PauseUpload()
            }
        }
        timedRound2Phase(timingAttemptId, "multipartComplete") {
            withRetry("terminar la subida", workId) {
                withContext(Dispatchers.IO) {
                    api.completeUpload(jobId,
                        done.map { BarraApi.PartSlot(it.key, it.value) })
                }
            }
        }
        WorkStore.put(app, WorkStore.get(app, workId)!!.copy(
            uploadId = "", partSize = 0, uploadedParts = emptyList(),
            uploadMode = "multipart", uploadComplete = true,
            stage = Stage.QUEUED.text, stageCode = Stage.QUEUED.code))
    }

    /**
     * El clip que se sube: el recorte a 720p cuando hay ventana que valga la
     * pena, el original cuando no, y TAMBIÉN el original cuando el
     * transcodificador falla por cualquier motivo (códec ausente, sin
     * espacio, excepción, más de tres minutos). El recorte es una mejora, no
     * una condición: jamás bloquea ni hace fallar una subida.
     *
     * Devuelve el fichero a subir y deja el work con la ventana final y la
     * marca de recortado. La ventana es la que el atleta dejó ajustada en la
     * UI (trimStartS/trimEndS del work), no la sugerencia cruda.
     */
    suspend fun trimForUpload(
        work: Work,
        clip: java.io.File,
        update: ((Work) -> Work) -> Unit = { t -> WorkStore.put(app, t(WorkStore.get(app, work.id) ?: work)) },
    ): java.io.File {
        if (!work.trimmed || work.trimEndS <= work.trimStartS) return clip
        update { it.copy(stage = "Recortando la serie",
            stageCode = Stage.WAITING.code) }
        val exportStartedNs = SystemClock.elapsedRealtimeNanos()
        val cut = java.io.File(clip.parent, clip.nameWithoutExtension + "-trim.mp4")
        return try {
            val actualVideoBitrateBps = trimmer.export(clip, cut, work.trimStartS, work.trimEndS)
            withContext(Dispatchers.IO) {
                Round2TimingStore.trimVideoBitrate(app,
                    work.timingAttemptId.ifBlank { work.id }, actualVideoBitrateBps)
            }
            if (!cut.exists() || cut.length() == 0L) {
                cut.delete()
                WorkStore.append(app, work.id, WorkStore.Level.WARN,
                    "el recorte no produjo fichero — se sube el clip entero")
                update { it.copy(trimmed = false,
                    trimStartS = 0.0, trimEndS = 0.0) }
                clip
            } else {
                // El fichero que viaja es el recortado: el work pasa a
                // apuntar a él, así un reintento o una reanudación suben lo
                // mismo que la primera vez.
                // Persist the exported file as the upload source and clear
                // the one-shot window. If Android kills the process before
                // multipart upload finishes, the resumed work must not trim
                // this already-trimmed file a second time.
                update { it.copy(clipPath = cut.absolutePath,
                    trimmed = false, trimStartS = 0.0, trimEndS = 0.0) }
                WorkStore.append(app, work.id, WorkStore.Level.INFO,
                    "recortado a %.1f s–%.1f s (%.1f MB%s)".format(
                        work.trimStartS, work.trimEndS, cut.length() / 1e6,
                        actualVideoBitrateBps?.let { ", %.2f Mbit/s vídeo".format(it / 1e6) }.orEmpty()))
                cut
            }
        } catch (err: Exception) {
            cut.delete()
            WorkStore.append(app, work.id, WorkStore.Level.WARN,
                "el recorte falló (${err.message.orEmpty()}) — se sube el clip entero")
            update { it.copy(trimmed = false,
                trimStartS = 0.0, trimEndS = 0.0) }
            clip
        } finally {
            val elapsedMs = ((SystemClock.elapsedRealtimeNanos() - exportStartedNs) / 1_000_000L).coerceAtLeast(0L)
            withContext(Dispatchers.IO) {
                Round2TimingStore.trimExportDuration(app,
                    work.timingAttemptId.ifBlank { work.id }, elapsedMs)
            }
        }
    }

    private suspend fun runWork(work: Work) {
        
        fun update(transform: (Work) -> Work) {
            val current = WorkStore.get(app, work.id) ?: return
            WorkStore.put(app, transform(current))
            publish()
        }

        fun log(level: WorkStore.Level, message: String) {
            WorkStore.append(app, work.id, level, message)
        }

        fun fail(raw: String, traceId: String = "") {
            val message = when {
                raw.contains("resolve host", ignoreCase = true) ->
                    "No se encontró el servidor (falló la resolución del nombre). " +
                        "El vídeo se guarda: pulsa Reintentar."
                raw.contains("Failed to connect", ignoreCase = true) ->
                    "Sin conexión a internet. El vídeo se guarda: pulsa Reintentar cuando vuelvas a tener red."
                raw.contains("unknown job", ignoreCase = true) ->
                    "El servidor perdió este análisis. Pulsa Reintentar y se enviará de nuevo."
                raw.contains("timed out", ignoreCase = true) ||
                    raw.contains("timeout", ignoreCase = true) ->
                    "El servidor tardó demasiado en responder. Pulsa Reintentar: el vídeo se guarda."
                else -> raw
            }
            log(WorkStore.Level.ERROR, message)
            update {
                it.copy(status = WorkStore.STATUS_FAILED, stage = "", error = message,
                    traceId = traceId.ifBlank { it.traceId })
            }
            EventLog.error(app, "a work failed", message,
                jobId = WorkStore.get(app, work.id)?.jobId.orEmpty())
            val w = WorkStore.get(app, work.id)
            if (w?.jobId?.isNotBlank() == true && w.uploadId.isNotBlank()) {
                scope.launch {
                    runCatching { withContext(Dispatchers.IO) { api.abortUpload(w.jobId) } }
                }
            }
            ProcessingNotifier.fail(app, message)
        }

        val clip = java.io.File(work.clipPath)
        update { it.copy(status = WorkStore.STATUS_WAITING, stage = Stage.WAITING.text, stageCode = Stage.WAITING.code,
            error = null) }
        var gateHeld = false
        try {
            uploadGate.lock()
            gateHeld = true
            if (!clip.exists() || clip.length() == 0L) {
                fail("El clip ya no está en el teléfono.")
                return
            }
            // EL RECORTE, antes de crear el trabajo. work.trimmed dice si la
            // ventana sugerida merecía la pena (la UI la preselecciona y el
            // atleta puede ajustarla; los valores finales quedan en el work).
            // Cualquier fallo del transcodificador deja `clip` intacto: el
            // original es lo que se sube, como siempre. El recorte nunca
            // bloquea ni hace fallar una subida.
            withContext(Dispatchers.IO) {
                Round2TimingStore.clipBytes(app,
                    work.timingAttemptId.ifBlank { work.id }, clip.length(), 0L)
            }
            val clipToUpload = trimForUpload(work, clip, ::update)
            val resuming = work.jobId.isNotBlank() &&
                (work.uploadMode.isNotBlank() || work.uploadId.isNotBlank() || work.uploadComplete)

            // Start before the first network request that creates or sends
            // this upload. The attempt survives process/network resume; an
            // explicit retry receives a new ID below.
            val timingAttemptId = work.timingAttemptId.ifBlank { work.id }
            WorkStore.put(app, (WorkStore.get(app, work.id) ?: work).copy(
                timingAttemptId = timingAttemptId))
            val phoneAttemptStartedAtMs = SystemClock.elapsedRealtime()
            withContext(Dispatchers.IO) {
                Round2TimingStore.clipBytes(app, timingAttemptId,
                    clip.length(), clipToUpload.length())
                Round2TimingStore.begin(app, timingAttemptId, completeOrigin = !resuming)
            }

            // A work that stopped mid-upload keeps its job: the parts already
            // on the server belong to that job's multipart session, and a new
            // job would strand them under a key nothing points at. Only a
            // work with nothing in flight asks for a fresh job.
            val created = if (!resuming) timedRound2Phase(timingAttemptId, "jobCreate") {
                withRetry("crear el trabajo", work.id) {
                    withContext(Dispatchers.IO) { api.createJob(work.declaredExercise.ifBlank { "auto" }, work.variant, work.view) }
                }
            } else null
            val jobId = if (resuming) work.jobId else requireNotNull(created).job.id
            val uploadMode = if (resuming) {
                work.uploadMode.ifBlank { "multipart" }
            } else chooseUploadMode(
                clipToUpload.length(), BuildConfig.SINGLE_PUT_MAX_BYTES,
                created?.uploadUrl, created?.uploadMethod)
            withContext(Dispatchers.IO) { Round2TimingStore.bindJob(app, timingAttemptId, jobId) }
            update { it.copy(jobId = jobId, uploadMode = uploadMode,
                uploadComplete = if (resuming) it.uploadComplete else false,
                status = WorkStore.STATUS_SENDING,
                stage = Stage.SENDING.text, stageCode = Stage.SENDING.code) }
            log(WorkStore.Level.INFO,
                if (resuming) "se reanuda el trabajo $jobId: ${work.uploadedParts.size} parte(s) ya enviadas"
                else "trabajo $jobId creado: se envía el clip " +
                    "(%.1f MB)".format(clipToUpload.length() / 1e6))
            ProcessingNotifier.stage(app, Stage.SENDING.text, 0)
            try {
                val current = WorkStore.get(app, work.id)!!
                if (!current.uploadComplete) {
                    if (uploadMode == "single") {
                        val uploadUrl = if (!resuming && created?.uploadUrl?.isNotBlank() == true) {
                            created.uploadUrl to created.uploadMethod
                        } else timedRound2Phase(timingAttemptId, "singlePutUrlRefresh") {
                            withRetry("preparar la subida", work.id) {
                                withContext(Dispatchers.IO) { api.refreshSingleUploadUrl(jobId) }
                            }
                        }
                        try {
                            timedRound2Phase(timingAttemptId, "singlePut") {
                                // Whole-file retries are expensive and can
                                // silently consume the upload budget. Persist
                                // this job and resume on the next validated
                                // network with a newly minted URL.
                                withRetry("enviar el clip", work.id, attempts = 1) {
                                    withContext(Dispatchers.IO) {
                                    api.uploadClip(clipToUpload, uploadUrl.first, uploadUrl.second)
                                    }
                                }
                            }
                            update { it.copy(uploadComplete = true) }
                        } catch (err: Exception) {
                            if (err is kotlinx.coroutines.CancellationException) throw err
                            if (err is java.io.IOException || err.message?.contains("timeout", true) == true ||
                                err.message?.contains("Failed to connect", true) == true ||
                                err.message?.contains("resolve host", true) == true) {
                                update { it.copy(status = WorkStore.STATUS_CONNECTING,
                                    stage = Stage.connecting(0, 1), stageCode = Stage.CONNECTING.code) }
                                publish()
                                throw PauseUpload()
                            }
                            throw err
                        }
                    } else {
                        uploadResumable(work.id, jobId, clipToUpload) { sent, total ->
                            update {
                                it.copy(status = WorkStore.STATUS_SENDING,
                                    stage = Stage.sending(sent, total), stageCode = Stage.SENDING.code)
                            }
                        }
                    }
                }
            } catch (_: PauseUpload) {
                // The network went away mid-send. Not a failure: the work sits
                // in "connecting" and the connectivity watcher resumes it the
                // moment a validated network appears - parts already sent stay
                // sent, on the server, by part number.
                return
            }
            update { it.copy(status = WorkStore.STATUS_QUEUED, stage = Stage.QUEUED.text, stageCode = Stage.QUEUED.code) }
            log(WorkStore.Level.INFO, "subido: en cola en el servidor")
            ProcessingNotifier.stage(app, Stage.QUEUED.text, 1)
            // Submit starts the worker again, so a job picked back up after a
            // restart is only submitted if the server never got that far.
            val serverStatus = if (resuming) withContext(Dispatchers.IO) {
                runCatching { api.getJob(jobId).status }.getOrNull()
            } else null
            if (serverStatus !in WorkStore.SUBMITTED_ON_SERVER) {
                timedRound2Phase(timingAttemptId, "submit") {
                    withRetry("poner en cola en el servidor", work.id) {
                        withContext(Dispatchers.IO) { api.submit(jobId) }
                    }
                }
            } else {
                log(WorkStore.Level.INFO, "el trabajo $jobId ya está «$serverStatus» en el servidor")
            }
            withContext(Dispatchers.IO) { Round2TimingStore.submitted(app, timingAttemptId) }
            // En el servidor: el siguiente clip puede empezar a subirse.
            if (gateHeld) { uploadGate.unlock(); gateHeld = false }

            // The wait. The server says where it is; the log keeps what it
            // said, so a wrong number later has a trail to be explained by.
            var contactLost = 0
            var pollCount = 0
            var pollGetNs = 0L
            var pollSleepNs = 0L
            var pollHandleNs = 0L
            repeat(240) {
                val pollStartedNs = SystemClock.elapsedRealtimeNanos()
                val job = withContext(Dispatchers.IO) { runCatching { api.getJob(jobId) } }
                pollCount++
                pollGetNs += (SystemClock.elapsedRealtimeNanos() - pollStartedNs).coerceAtLeast(0L)
                val pollHandleStartedNs = SystemClock.elapsedRealtimeNanos()
                job.fold(onSuccess = { j ->
                    contactLost = 0
                    when (j.status) {
                        "done" -> {
                            withContext(Dispatchers.IO) {
                                Round2TimingStore.resultReceived(app, timingAttemptId,
                                    j.result?.traceId.orEmpty(),
                                    countStatus = j.result?.countStatus,
                                    repCount = j.result?.repCount,
                                    pollCount = pollCount,
                                    pollGetMs = pollGetNs / 1_000_000L,
                                    pollSleepMs = pollSleepNs / 1_000_000L,
                                    pollHandleMs = pollHandleNs / 1_000_000L)
                            }
                            j.result?.let { SessionStore.record(app, j.id, it, j.createdAt) }
                            val countStatus = j.result?.countStatus ?: "unmeasured"
                            val repCount = j.result?.repCount ?: 0
                            val countDescription = when (countStatus) {
                                "unmeasured" -> "recuento de repeticiones no disponible"
                                "vision" -> "$repCount repetici${if (repCount == 1) "ón estimada" else "ones estimadas"} a partir de fotogramas"
                                "hold" -> "$repCount intento${if (repCount == 1) "" else "s"} de mantenimiento medido${if (repCount == 1) "" else "s"}"
                                else -> "$repCount repetici${if (repCount == 1) "ón medida" else "ones medidas"}"
                            }
                            log(WorkStore.Level.INFO, "$countDescription de " +
                                (j.result?.exercise?.let { com.barrapp.movementEs(it) } ?: "movimiento desconocido") +
                                " — traza ${j.result?.traceId.orEmpty()}")
                            // The clip answers to its job id from here on, so
                            // replay and delete keep working the way they did.
                            // The one renamed is the one UPLOADED - the 720p
                            // cut when the trim held, the original otherwise -
                            // so the replay screen plays exactly what the
                            // server measured, timestamps included.
                            withContext(Dispatchers.IO) {
                                clipToUpload.renameTo(clipFile(app, j.id))
                                if (clipToUpload != clip) clip.delete()
                            }
                            EventLog.info(app,
                                "$countDescription of ${j.result?.exercise ?: "unknown"}",
                                "score ${j.result?.sessionScore ?: "—"}",
                                traceId = j.result?.traceId.orEmpty(), jobId = j.id)
                            val movement = j.result?.exercise.orEmpty()
                            val verdict = if (movement.isNotBlank())
                                Progression.assess(movement, SessionStore.days(app)) else null
                            if (verdict?.step != null &&
                                verdict.qualifyingDays.size == verdict.step.days
                            ) {
                                ProcessingNotifier.done(
                                    app,
                                    "Estándar superado: ${verdict.step.towardsLabel} desbloqueado",
                                    "Has cumplido el estándar de ${verdict.label} en " +
                                        "${verdict.step.days} días distintos. Mira el Plan.",
                                    jobId = j.id,
                                )
                            } else {
                                ProcessingNotifier.done(
                                    app,
                                    when (countStatus) {
                                        "unmeasured" -> "Recuento de repeticiones sin medir"
                                        "vision" -> "$repCount rep${if (repCount == 1) "" else "s"} estimadas a partir de fotogramas"
                                        "hold" -> "$repCount mantenimientos medidos"
                                        else -> "$repCount " +
                                            (if (repCount == 1) "repetición medida" else "repeticiones medidas")
                                    },
                                    "Tu análisis de " + com.barrapp.movementEs(
                                        j.result?.exercise.orEmpty(), j.result?.detected?.label.orEmpty(),
                                    ).lowercase() + " está listo.",
                                    jobId = j.id,
                                )
                            }
                            WorkStore.forget(app, work.id)
                            SessionStore.addUnseen(app, j.id)
                            publish()
                            // The screen, if one is open, takes it from here.
                            _finished.tryEmit(j)
                            return
                        }
                        "failed" -> {
                            fail(j.error ?: "El servidor no pudo usar este vídeo.",
                                j.result?.traceId.orEmpty())
                            return
                        }
                        else -> {
                            val stage = Stage.display(j)
                            update {
                                it.copy(
                                    status = if (j.status == "processing")
                                        WorkStore.STATUS_MEASURING else WorkStore.STATUS_QUEUED,
                                    stage = stage,
                                    stageCode = Stage.code(j),
                                )
                            }
                            ProcessingNotifier.stage(app, stage.replaceFirstChar { c -> c.uppercaseChar() },
                                Stage.progressIndex(Stage.code(j), j.stage))
                        }
                    }
                }, onFailure = { err ->
                    val msg = err.message.orEmpty()
                    // A job the server no longer knows about (reaped as stale,
                    // or created under a different device) will never come back
                    // by polling. Say so plainly and let Retry re-send it fresh.
                    if (msg.contains("unknown job", ignoreCase = true)) {
                        log(WorkStore.Level.WARN, "el trabajo se perdió en el servidor")
                        fail("El servidor perdió el trabajo de este clip. Pulsa Reintentar para enviarlo de nuevo.")
                        return
                    }
                    contactLost++
                    log(WorkStore.Level.WARN,
                        "se perdió el contacto con el servidor (${contactLost}) — $msg")
                    if (contactLost >= 5) {
                        fail("Se perdió el contacto con el servidor mientras se medía.")
                        return
                    }
                })
                val sleepStartedNs = SystemClock.elapsedRealtimeNanos()
                // Response handling for a nonterminal poll is client work
                // too: status persistence, stage updates and notifications.
                pollHandleNs += (sleepStartedNs - pollHandleStartedNs).coerceAtLeast(0L)
                delay(resultPollDelayMs(
                    SystemClock.elapsedRealtime() - phoneAttemptStartedAtMs))
                pollSleepNs += (SystemClock.elapsedRealtimeNanos() - sleepStartedNs).coerceAtLeast(0L)
            }
            fail("Sigue midiéndose tras cuatro minutos. Puede que aún termine en el servidor: " +
                "pulsa Reintentar para comprobarlo de nuevo.")
        } catch (err: kotlinx.coroutines.CancellationException) {
            // The system stopped the worker. Not a failure: the work keeps
            // its state and the next run picks it back up.
            throw err
        } catch (err: Exception) {
            fail(err.message ?: "No se pudo enviar ese clip.")
        } finally {
            if (gateHeld) uploadGate.unlock()
        }
    }


    companion object {
        /** Clips midiéndose a la vez en el servidor. */
        const val MAX_IN_FLIGHT = 3

        @Volatile private var instance: UploadQueue? = null

        fun get(context: Context): UploadQueue =
            instance?.takeIf { it.app === context.applicationContext }
                ?: synchronized(this) {
                    instance?.takeIf { it.app === context.applicationContext }
                        ?: UploadQueue(context.applicationContext as Application)
                            .also { instance = it }
                }
    }
}
