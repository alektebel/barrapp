package com.barrapp

import android.app.Application
import android.content.Intent
import android.net.Uri
import android.os.SystemClock
import android.provider.MediaStore
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.barrapp.data.ActivityLevel
import com.barrapp.data.Analysis
import com.barrapp.data.AuthStore
import com.barrapp.data.BarraApi
import com.barrapp.data.ChatTurn
import com.barrapp.data.DayEntry
import com.barrapp.data.EventLog
import com.barrapp.data.Goals
import com.barrapp.data.GoalsStore
import com.barrapp.data.Job
import com.barrapp.data.Profile
import com.barrapp.data.ProfileStore
import com.barrapp.data.Round2TimingStore
import com.barrapp.data.SessionStore
import com.barrapp.data.Work
import com.barrapp.data.WorkStore
import com.barrapp.notify.WeeklyReviewWorker
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class Screen { Privacy, Onboarding, Auth, Home, Coach, Diagnostics, Feedback, Objectives, Replay, Plan, WorkLog }

/** Which pane the compact layout is showing. Wide layouts show all three. */
enum class Pane { Calendar, Session, Progress }

data class UiState(
    val screen: Screen = Screen.Privacy,
    val pane: Pane = Pane.Session,
    val profile: Profile = Profile(),
    val days: List<DayEntry> = emptyList(),
    /** date -> fault -> reps that showed it, the ledger the coach and progress
     *  screens read to say whether a fault is getting better. */
    val faults: Map<String, Map<String, Int>> = emptyMap(),
    val jobs: List<Job> = emptyList(),
    val selectedDate: String? = null,
    val current: Job? = null,
    val analysis: Analysis? = null,
    /** Every clip on its way to being a session: the works in progress, the
     *  ones waiting, and the ones that went wrong with their reason. */
    val works: List<Work> = emptyList(),
    /** El clip que espera a que el atleta confirme (o mueva) la ventana de
     *  recorte antes de subirse. Uno como mucho: la cola es de uno. */
    val pendingTrim: Work? = null,
    val workLogId: String? = null,
    val error: String? = null,
    val chat: List<ChatTurn> = emptyList(),
    val coachThinking: Boolean = false,
    val objectives: List<ChatTurn> = emptyList(),
    val objectivesThinking: Boolean = false,
    val goals: Goals? = null,
    val weeklyNote: String? = null,
    val events: List<EventLog.Event> = emptyList(),
    /** The account screen's own little flow, and what it is doing. */
    val authStep: com.barrapp.ui.AuthStep = com.barrapp.ui.AuthStep.SignIn,
    val authBusy: Boolean = false,
    val authError: String? = null,
    val authNotice: String? = null,
    val signedInAs: String = "",
    /** The feedback screen's one-shot flow: sending, sent, or what went wrong. */
    val feedbackBusy: Boolean = false,
    val feedbackSent: Boolean = false,
    val feedbackError: String? = null,
)

private const val PENDING_TEXT_POLL_MS = 2_000L
private const val PENDING_TEXT_FOLLOW_MS = 90_000L

class BarrappViewModel(application: Application) : AndroidViewModel(application) {
    private val api = BarraApi(application)
    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state

    /** The work queue. Declared before the init block below on purpose: the
     *  collectors it launches run on Main.immediate, which is still inside
     *  this constructor. */
    private val uploads = com.barrapp.upload.UploadQueue.get(application)

    /** Quién corta el clip. Real en producción, fake en las pruebas unitarias
     *  de la decisión (la vía real del Transformer necesita un dispositivo). */
    internal var trimmer: com.barrapp.media.ClipTrimmer
        get() = uploads.trimmer
        set(value) { uploads.trimmer = value }

    internal suspend fun trimForUpload(work: Work, clip: java.io.File): java.io.File =
        uploads.trimForUpload(work, clip)

    /** Fires when a VALIDATED network appears: paused uploads resume here. */
    private val netCallback = object : android.net.ConnectivityManager.NetworkCallback() {
        override fun onCapabilitiesChanged(
            network: android.net.Network,
            capabilities: android.net.NetworkCapabilities,
        ) {
            if (capabilities.hasCapability(
                    android.net.NetworkCapabilities.NET_CAPABILITY_VALIDATED)
            ) resumeConnectingWorks()
        }
    }

    init {
        val app = getApplication<Application>()
        val profile = ProfileStore.load(app)
        val screen = when {
            !DeviceId.privacyAccepted(app) -> Screen.Privacy
            !profile.complete -> Screen.Onboarding
            else -> Screen.Home
        }
        _state.update {
            it.copy(
                screen = screen,
                profile = profile,
                goals = GoalsStore.load(app),
                days = SessionStore.days(app),
                faults = SessionStore.faults(app),
                chat = SessionStore.chat(app),
                works = WorkStore.all(app),
                weeklyNote = WeeklyReviewWorker.buildReview(app)?.body,
                signedInAs = AuthStore.email(app),
            )
        }
        // The queue runs in WorkManager, not here: a clip keeps going when
        // the app is closed. The screen only follows it.
        viewModelScope.launch {
            uploads.works.collect { works ->
                _state.update { it.copy(works = works,
                    pendingTrim = works.firstOrNull { w -> w.status == WorkStore.STATUS_PENDING }) }
            }
        }
        viewModelScope.launch { uploads.finished.collect { j -> showFinished(j) } }
        // Opening the app is one more chance for a clip left mid-way to go on.
        if (WorkStore.all(app).any { it.active }) uploads.kick()
        // The resume-on-connection watcher: a work paused mid-upload does not
        // need a human to notice the wifi came back.
        runCatching {
            (getApplication<Application>().getSystemService(
                android.content.Context.CONNECTIVITY_SERVICE)
                as android.net.ConnectivityManager)
                .registerDefaultNetworkCallback(netCallback)
        }
        if (screen == Screen.Home) {
            WeeklyReviewWorker.schedule(app)
            refresh()
            syncHistory()
        }
    }

    /** Pull the device's history from the server and fold in whatever the
     *  phone has never seen, so the calendar survives a cleared app. The
     *  measurements travel; the clips never do - those stay wherever they
     *  were filmed. A failed sync is quiet: the phone still shows what it
     *  holds, and the next launch tries again. */
    private fun syncHistory() {
        val app = getApplication<Application>()
        viewModelScope.launch {
            runCatching { withContext(Dispatchers.IO) { api.history() } }
                .onSuccess { jobs ->
                    val known = SessionStore.knownJobIds(app)
                    val fresh = jobs.filter { it.id !in known && it.result != null }
                    fresh.forEach { SessionStore.record(app, it.id, it.result!!) }
                    if (fresh.isNotEmpty()) {
                        _state.update { it.copy(days = SessionStore.days(app),
                            faults = SessionStore.faults(app)) }
                    }
                }
        }
    }

    /** A copy of the clip on this phone, keyed by job id. The server's copy
     *  expires; this one is what the replay screen plays, and it never leaves
     *  the device. */
    private fun keepClip(app: Application, jobId: String, uri: Uri) {
        runCatching {
            clipFile(app, jobId).parentFile?.mkdirs()
            app.contentResolver.openInputStream(uri)?.use { input ->
                clipFile(app, jobId).outputStream().use { output -> input.copyTo(output) }
            } ?: error("could not open the clip")
        }.onFailure {
            EventLog.warn(app, "the clip was not kept for replay", it.message.orEmpty())
        }
    }

    private fun clipFile(app: Application, jobId: String): java.io.File =
        java.io.File(java.io.File(app.filesDir, "clips"), "$jobId.mp4")

    /** The locally kept copy of the current session's clip, when this phone
     *  still has it. Drives whether the replay entry point is offered. */
    fun replayClip(): java.io.File? {
        val current = _state.value.current ?: return null
        // The clip must be the one the analysis on screen measured: a session
        // opened from the calendar is not the job that was uploaded last.
        val shown = _state.value.analysis?.traceId
        val measured = current.result?.traceId
        if (!shown.isNullOrBlank() && !measured.isNullOrBlank() && shown != measured) return null
        val id = current.id
        val app = getApplication<Application>()
        clipFile(app, id).takeIf { it.exists() && it.length() > 0 }?.let { return it }
        // A work's clip keeps its local name until the work finishes, so a
        // session measured moments ago is replayed from the queue's copy.
        return WorkStore.all(app).firstOrNull { it.jobId == id }
            ?.clipPath?.takeIf { it.isNotBlank() }
            ?.let { java.io.File(it) }?.takeIf { it.exists() && it.length() > 0 }
    }

    // ---- replay ------------------------------------------------------------
    fun openReplay() {
        if (replayClip() != null) _state.update { it.copy(screen = Screen.Replay) }
    }

    fun openPlan() = _state.update { it.copy(screen = Screen.Plan) }

    // ---- onboarding -------------------------------------------------------
    fun acceptPrivacy() {
        val app = getApplication<Application>()
        DeviceId.acceptPrivacy(app)
        val profile = ProfileStore.load(app)
        _state.update {
            it.copy(screen = if (profile.complete) Screen.Home else Screen.Onboarding)
        }
        if (profile.complete) refresh()
    }

    /**
     * The redesigned intake, saved in one go.
     *
     * The four answers land in the two places that already own them — the name
     * and the training frequency on the profile, the goal and the focus
     * movement in the goals store — so nothing else in the app has to learn a
     * new shape to read them.
     */
    fun saveIntake(name: String, activity: ActivityLevel, goal: String, focusExercise: String) {
        val app = getApplication<Application>()
        val profile = _state.value.profile.copy(name = name, activity = activity)
        ProfileStore.save(app, profile)
        val goals = Goals(goal = goal, focusExercise = focusExercise)
        GoalsStore.save(app, goals)
        WeeklyReviewWorker.schedule(app)
        _state.update { it.copy(profile = profile, goals = goals, screen = Screen.Home) }
        refresh()
    }

    fun saveProfile(profile: Profile) {
        val app = getApplication<Application>()
        ProfileStore.save(app, profile)
        WeeklyReviewWorker.schedule(app)
        _state.update { it.copy(profile = profile, screen = Screen.Home) }
        refresh()
    }

    // ---- accounts ---------------------------------------------------------

    fun openAuth(step: com.barrapp.ui.AuthStep = com.barrapp.ui.AuthStep.SignIn) =
        _state.update {
            it.copy(screen = Screen.Auth, authStep = step, authError = null,
                authNotice = null)
        }

    fun setAuthStep(step: com.barrapp.ui.AuthStep) =
        _state.update { it.copy(authStep = step, authError = null, authNotice = null) }

    /** One shape for every account call: busy while it runs, the server's own
     *  sentence when it fails. The API's error messages are already written
     *  for a person, so they are shown rather than replaced. */
    private fun authAction(onOk: suspend (Application) -> Unit) {
        val app = getApplication<Application>()
        _state.update { it.copy(authBusy = true, authError = null, authNotice = null) }
        viewModelScope.launch {
            runCatching { withContext(Dispatchers.IO) { onOk(app) } }
                .onFailure { err ->
                    _state.update {
                        it.copy(authBusy = false,
                            authError = err.message ?: "That did not work. Try again.")
                    }
                }
                .onSuccess { _state.update { it.copy(authBusy = false) } }
        }
    }

    fun signUp(email: String, password: String) = authAction { app ->
        api.signUp(email, password)
        _state.update {
            it.copy(authStep = com.barrapp.ui.AuthStep.Confirm,
                authNotice = "Account created. Enter the code we emailed you.")
        }
    }

    fun confirmAccount(email: String, code: String) = authAction { app ->
        api.confirm(email, code)
        _state.update {
            it.copy(authStep = com.barrapp.ui.AuthStep.SignIn,
                authNotice = "Confirmed. Sign in to finish.")
        }
    }

    fun resendCode(email: String) = authAction { _ ->
        api.resendCode(email)
        _state.update { it.copy(authNotice = "Sent. Check your email again.") }
    }

    fun forgotPassword(email: String) = authAction { _ ->
        api.forgotPassword(email)
        _state.update {
            it.copy(authStep = com.barrapp.ui.AuthStep.Reset,
                authNotice = "We emailed you a code.")
        }
    }

    fun resetPassword(email: String, code: String, password: String) = authAction { _ ->
        api.resetPassword(email, code, password)
        _state.update {
            it.copy(authStep = com.barrapp.ui.AuthStep.SignIn,
                authNotice = "Password changed. Sign in with it.")
        }
    }

    fun signIn(email: String, password: String) = authAction { app ->
        api.signIn(email, password)
        // The sessions measured before signing in belong to this person, not
        // to a device id they will never type again - move them across, once.
        val device = api.deviceId()
        if (!AuthStore.alreadyClaimed(app, device)) {
            runCatching { api.claimDevice() }
                .onSuccess { AuthStore.markClaimed(app, device) }
        }
        _state.update { it.copy(screen = Screen.Home, signedInAs = AuthStore.email(app)) }
        refresh()
    }

    fun signOut() {
        val app = getApplication<Application>()
        AuthStore.clear(app)
        SessionStore.forgetAll(app)
        _state.update {
            it.copy(screen = Screen.Home, signedInAs = "", days = emptyList(),
                analysis = null, current = null, selectedDate = null)
        }
        refresh()
    }

    fun openPrivacy() = _state.update { it.copy(screen = Screen.Privacy) }
    fun openOnboarding() = _state.update { it.copy(screen = Screen.Onboarding) }

    // ---- navigation -------------------------------------------------------
    fun showPane(pane: Pane) = _state.update { it.copy(pane = pane) }

    fun openHome() {
        _state.update { it.copy(screen = Screen.Home, error = null, workLogId = null) }
        refresh()
    }

    fun openCoach() = _state.update { it.copy(screen = Screen.Coach) }

    fun openDiagnostics() = _state.update {
        it.copy(screen = Screen.Diagnostics, events = EventLog.all(getApplication()))
    }

    // ---- feedback ----------------------------------------------------------

    fun openFeedback() = _state.update {
        it.copy(screen = Screen.Feedback, feedbackBusy = false,
            feedbackSent = false, feedbackError = null)
    }

    fun resetFeedback() = _state.update {
        it.copy(feedbackBusy = false, feedbackSent = false, feedbackError = null)
    }

    /** Send what the user wrote, and - when they attached a clip - stream it
     *  through the presigned PUT the server answered with. Marked in the
     *  event log like every other network hop, so a feedback that never
     *  arrives can still be seen trying. */
    fun sendFeedback(message: String, video: Uri?) {
        val app = getApplication<Application>()
        val text = message.trim()
        if (text.isEmpty()) {
            _state.update { it.copy(feedbackError = "Write something first") }
            return
        }
        if (_state.value.feedbackBusy) return
        _state.update { it.copy(feedbackBusy = true, feedbackError = null) }
        viewModelScope.launch {
            try {
                val latest = _state.value
                val created = withContext(Dispatchers.IO) {
                    api.sendFeedback(
                        message = text,
                        video = video != null,
                        traceId = latest.analysis?.traceId,
                        jobId = latest.current?.id,
                    )
                }
                EventLog.info(app, "feedback accepted", created.id,
                    traceId = latest.analysis?.traceId ?: "",
                    jobId = latest.current?.id ?: "")
                if (video != null) {
                    withContext(Dispatchers.IO) {
                        api.uploadVideo(app, created.uploadUrl, created.uploadMethod, video)
                    }
                    EventLog.info(app, "feedback clip uploaded", created.id)
                }
                _state.update { it.copy(feedbackBusy = false, feedbackSent = true) }
            } catch (err: Exception) {
                EventLog.error(app, "feedback failed", err.message ?: "")
                _state.update {
                    it.copy(feedbackBusy = false,
                        feedbackError = err.message ?: "Could not send feedback")
                }
            }
        }
    }

    fun clearEvents() {
        EventLog.forget(getApplication())
        _state.update { it.copy(events = emptyList()) }
    }

    fun diagnosticsReport(): String =
        EventLog.report(getApplication(), DeviceId.get(getApplication()), BuildConfig.API_BASE_URL)

    /** The bundled example session, so the first screen is not a blank wall.
     *  Marked by having no job behind it, so it cannot be deleted or recorded
     *  into the calendar as if it were the user's own training. */
    fun openExample() {
        val analysis = runCatching { BarraApi.sampleFromAssets(getApplication()) }.getOrNull()
        if (analysis != null) {
            _state.update { it.copy(analysis = analysis, current = null, pane = Pane.Session) }
        }
    }

    fun selectDate(date: String) {
        val day = _state.value.days.firstOrNull { it.date == date }
        _state.update { it.copy(selectedDate = date, pane = Pane.Session) }
        val jobId = day?.jobIds?.lastOrNull() ?: run {
            _state.update { it.copy(analysis = null, current = null) }
            return
        }
        val known = _state.value.jobs.firstOrNull { it.id == jobId }
        // A cached result whose vision note or model prose was still on its
        // way is fetched again, so both appear once the server has added them.
        if (known?.result != null && !known.result.visionPending && !known.result.prosePending) {
            _state.update { it.copy(analysis = known.result, current = known) }
            return
        }
        // Clear first: until the fetch lands (or if it fails) the sheet must not
        // present the previously opened session under this day's heading.
        _state.update { it.copy(analysis = null, current = null) }
        viewModelScope.launch {
            runCatching { withContext(Dispatchers.IO) { api.getJob(jobId) } }
                .onSuccess { job ->
                    // A slower fetch for an earlier tap must not overwrite this one.
                    _state.update {
                        if (it.selectedDate != date) it
                        else it.copy(current = job, analysis = job.result)
                    }
                }
        }
    }

    /**
     * The result is on screen with the deterministic Spanish text; the model's
     * prose and the vision note follow (proseStatus / visionStatus "pending").
     * Ask again for a bounded while and swap them in when they land - only if
     * that session is still the one on screen.
     */
    private fun followPendingText(jobId: String) {
        val app = getApplication<Application>()
        viewModelScope.launch {
            val deadline = SystemClock.elapsedRealtime() + PENDING_TEXT_FOLLOW_MS
            while (SystemClock.elapsedRealtime() < deadline) {
                delay(PENDING_TEXT_POLL_MS)
                val job = runCatching { withContext(Dispatchers.IO) { api.getJob(jobId) } }
                    .getOrNull() ?: continue
                val result = job.result ?: continue
                if (result.prosePending || result.visionPending) continue
                SessionStore.record(app, job.id, result)
                _state.update {
                    if (it.current?.id != jobId) it
                    else it.copy(current = job, analysis = result)
                }
                return@launch
            }
        }
    }

    fun refresh() {
        val app = getApplication<Application>()
        viewModelScope.launch {
            runCatching { withContext(Dispatchers.IO) { api.listJobs() } }
                .onSuccess { jobs ->
                    // Fold anything finished on the server into the local
                    // calendar, so a job that completed while the app was shut
                    // shows up without the user having to open it.
                    //
                    // Only jobs the calendar has never seen. record() ADDS to
                    // its day - reps, verified count, score sum - so replaying
                    // a job already folded in counts it twice. This ran on
                    // every refresh, which is every app open and every finished
                    // upload, and it is why the week read 1875 reps against a
                    // server that had measured 74.
                    val known = SessionStore.knownJobIds(app)
                    jobs.filter { it.status == "done" && it.result != null && it.id !in known }
                        .forEach { SessionStore.record(app, it.id, it.result!!) }
                    _state.update {
                        it.copy(
                            jobs = jobs,
                            days = SessionStore.days(app),
                faults = SessionStore.faults(app),
                            weeklyNote = WeeklyReviewWorker.buildReview(app)?.body,
                            error = null,
                        )
                    }
                }
                .onFailure { err ->
                    // The calendar is local, so an unreachable server is not a
                    // blank screen - it is a note next to data that still works.
                    EventLog.warn(app, "could not refresh from the server",
                        err.message.orEmpty())
                    _state.update { it.copy(error = err.message) }
                }
        }
    }

    fun recordIntent(): Intent = Intent(MediaStore.ACTION_VIDEO_CAPTURE)

    // ---- works: a queue of clips on their way to being sessions ------------
    //
    // One worker, works in order. A queue the phone can draw is worth more
    // than parallel uploads the server cannot measure any faster, and a
    // single worker means the log of each work reads top to bottom as what
    // actually happened, when.

    /** A clip picked anywhere lands here. The clip is copied onto the phone
     *  FIRST, because a camera's content uri can expire before the upload
     *  finishes, and a work that cannot be retried is not in a queue at all. */
    fun upload(uri: Uri?, variant: String = "", view: String = "") {
        val video = uri ?: return
        val app = getApplication<Application>()
        val workId = java.util.UUID.randomUUID().toString().replace("-", "").take(12)
        val dest = clipFile(app, workId)
        val preparationStartedNs = SystemClock.elapsedRealtimeNanos()
        viewModelScope.launch {
            val kept = runCatching {
                withContext(Dispatchers.IO) {
                    dest.parentFile?.mkdirs()
                    app.contentResolver.openInputStream(video)?.use { input ->
                        dest.outputStream().use { output -> input.copyTo(output) }
                    } ?: error("could not open the clip")
                    dest.length() > 0
                }
            }.getOrElse { false }
            // La ventana que el teléfono PROPONE. Se muestrea sobre la copia
            // ya guardada, no sobre el uri (que puede caducar); si el
            // muestreo falla, el clip se sube entero y nadie se entera.
            val suggestion = if (kept) runCatching {
                withContext(Dispatchers.IO) {
                    com.barrapp.media.MediaMetadataSampler().suggest(app,
                        android.net.Uri.fromFile(dest))
                }
            }.getOrElse { null } else null
            val doTrim = com.barrapp.data.TrimPlan.shouldTrim(
                suggestion?.second, suggestion?.first?.durationS ?: 0.0)
            val win = suggestion?.second
            withContext(Dispatchers.IO) {
                Round2TimingStore.preparationDuration(app, workId,
                    ((SystemClock.elapsedRealtimeNanos() - preparationStartedNs) / 1_000_000L).coerceAtLeast(0))
            }
            val work = Work(
                id = workId,
                createdAt = System.currentTimeMillis(),
                status = when {
                    !kept -> WorkStore.STATUS_FAILED
                    win != null && doTrim -> WorkStore.STATUS_PENDING
                    else -> WorkStore.STATUS_WAITING
                },
                clipPath = dest.absolutePath,
                error = if (kept) null else "The clip could not be kept on the phone.",
                // The server's vocabularies: variants are lower_snake
                // (strict, kipping, full, tuck, straddle); viewpoint bins are
                // upper (SAGITTAL, FRONTAL, OBLIQUE). Anything else comes back
                // as unspecified / UNKNOWN with the word kept beside it.
                variant = variant.trim().lowercase(),
                view = view.trim().uppercase(),
                trimStartS = if (win != null && doTrim) win.startS else 0.0,
                trimEndS = if (win != null && doTrim) win.endS else 0.0,
                trimmed = false,   // only true once the athlete confirms
                timingAttemptId = workId,
                clipDurationS = suggestion?.first?.durationS ?: 0.0,
                log = buildList {
                    val declared = listOfNotNull(
                        variant.takeIf { it.isNotBlank() }?.let { "$it standard declared" },
                        view.takeIf { it.isNotBlank() }?.let { "camera $it" },
                    )
                    add(WorkStore.Entry(System.currentTimeMillis(), WorkStore.Level.INFO,
                        (listOf("clip added to the queue") + declared).joinToString(" · ")))
                    if (win != null) {
                        add(WorkStore.Entry(System.currentTimeMillis(), WorkStore.Level.INFO,
                            "serie sugerida: %.1f s–%.1f s".format(win.startS, win.endS)))
                    }
                    if (!kept) add(WorkStore.Entry(System.currentTimeMillis(),
                        WorkStore.Level.ERROR, "the clip could not be read or kept"))
                },
            )
            WorkStore.put(app, work)
            EventLog.info(app, "clip added to the queue", workId)
            publishWorks()
            // Un clip PENDIENTE espera al atleta: la cola no lo recoge hasta
            // que confirma (o descarta) la ventana de recorte.
            if (kept && work.status != WorkStore.STATUS_PENDING) uploads.kick()
        }
    }

    /** El atleta movió los tiradores del deslizador. Grueso vale: 0,1 s. */
    fun setTrimWindow(workId: String, startS: Double, endS: Double) {
        val app = getApplication<Application>()
        val work = WorkStore.get(app, workId) ?: return
        WorkStore.put(app, work.copy(
            trimStartS = startS.coerceIn(0.0, work.clipDurationS),
            trimEndS = endS.coerceIn(startS, work.clipDurationS),
        ))
        publishWorks()
    }

    /** Confirmación: la ventana que hay en el work manda. A subir. */
    fun confirmTrim(workId: String) {
        val app = getApplication<Application>()
        val work = WorkStore.get(app, workId) ?: return
        val keepTrim = work.trimEndS > work.trimStartS
        val confirmedNs = SystemClock.elapsedRealtimeNanos()
        WorkStore.put(app, work.copy(
            status = WorkStore.STATUS_WAITING,
            trimmed = keepTrim,
            trimStartS = if (keepTrim) work.trimStartS else 0.0,
            trimEndS = if (keepTrim) work.trimEndS else 0.0,
            log = work.log + WorkStore.Entry(System.currentTimeMillis(),
                WorkStore.Level.INFO, if (keepTrim)
                    "recorte confirmado: %.1f s–%.1f s".format(
                        work.trimStartS, work.trimEndS)
                else "se sube el clip entero"),
        ))
        publishWorks()
        viewModelScope.launch {
            withContext(Dispatchers.IO) { Round2TimingStore.trimConfirmed(app, work.timingAttemptId.ifBlank { work.id }, confirmedNs) }
            uploads.kick()
        }
    }

    /** Cancelar el recorte y subir el clip entero, sin pasarlo por el
     *  transcodificador: mismo camino de siempre. */
    fun discardTrim(workId: String) {
        val app = getApplication<Application>()
        val work = WorkStore.get(app, workId) ?: return
        val confirmedNs = SystemClock.elapsedRealtimeNanos()
        WorkStore.put(app, work.copy(
            status = WorkStore.STATUS_WAITING,
            trimmed = false, trimStartS = 0.0, trimEndS = 0.0,
            log = work.log + WorkStore.Entry(System.currentTimeMillis(),
                WorkStore.Level.INFO, "se sube el clip entero"),
        ))
        publishWorks()
        viewModelScope.launch {
            withContext(Dispatchers.IO) { Round2TimingStore.trimConfirmed(app, work.timingAttemptId.ifBlank { work.id }, confirmedNs) }
            uploads.kick()
        }
    }

    private fun publishWorks() = uploads.publish()

    /** A clip finished while this screen was alive: open its session. */
    private fun showFinished(j: Job) {
        val app = getApplication<Application>()
        _state.update {
            it.copy(
                screen = Screen.Home,
                pane = Pane.Session,
                analysis = j.result,
                current = j,
                selectedDate = j.result?.sessionDate ?: SessionStore.today(),
                days = SessionStore.days(app),
                faults = SessionStore.faults(app),
                weeklyNote = WeeklyReviewWorker.buildReview(app)?.body,
                error = null,
            )
        }
        refresh()
        if (j.result?.prosePending == true || j.result?.visionPending == true) {
            followPendingText(j.id)
        }
    }


    /** Send a failed work again. Always the full pipeline: a fresh job, the
     *  kept clip re-uploaded - so a retry never depends on whatever state the
     *  server was left in. */
    fun retryWork(workId: String) {
        val app = getApplication<Application>()
        val work = WorkStore.get(app, workId) ?: return
        if (!work.clipPath.let { java.io.File(it).exists() }) {
            WorkStore.append(app, workId, WorkStore.Level.ERROR,
                "retry refused — the clip is no longer on the phone")
            publishWorks()
            return
        }
        viewModelScope.launch {
            // Fresh job means fresh upload: drop the half-finished multipart
            // session too, or the next run would resume into a job the server
            // has already given up on.
            if (work.uploadId.isNotBlank() && work.jobId.isNotBlank()) {
                runCatching { withContext(Dispatchers.IO) { api.abortUpload(work.jobId) } }
            }
            WorkStore.put(app, work.copy(status = WorkStore.STATUS_WAITING, error = null,
                stage = "waiting to be sent", traceId = "",
                jobId = "", uploadId = "", partSize = 0, uploadedParts = emptyList(),
                uploadMode = "", uploadComplete = false,
                timingAttemptId = java.util.UUID.randomUUID().toString(),
                // El recorte ya pasó: clipPath apunta al recortado y su ventana
                // de un solo uso ya quedó limpiada, así el reintento sube lo mismo.
                log = work.log + WorkStore.Entry(System.currentTimeMillis(),
                    WorkStore.Level.INFO, "retry requested")))
            publishWorks()
            uploads.kick()
        }
    }

    /** Called by the result composable after the measured result has applied. */
    fun markResultRendered(jobId: String, traceId: String = "") {
        val renderedNs = SystemClock.elapsedRealtimeNanos()
        val app = getApplication<Application>()
        viewModelScope.launch {
            val attempt = withContext(Dispatchers.IO) {
                Round2TimingStore.rendered(app, jobId, traceId, renderedNs)
            } ?: return@launch
            val totalMs = attempt.durationMs(attempt.renderedNs)
            val uploadMs = attempt.durationMs(attempt.submittedNs)
            val resultMs = attempt.durationMs(attempt.resultNs)
            val renderDelayMs = attempt.intervalMs(attempt.resultNs, attempt.renderedNs)
            val confirmationMs = attempt.confirmedToRenderedMs(attempt.renderedNs)
            val transportMs = attempt.phaseMs.entries.sortedBy { it.key }
                .joinToString(", ") { "${it.key}=${it.value}ms" }
            val countDetails = "count ${attempt.countStatus ?: "unknown"} " +
                "(${attempt.repCount?.toString() ?: "unknown"} reps)"
            val details = if (totalMs == null)
                "clock changed or attempt origin missing; duration omitted, $countDetails"
            else "${totalMs}ms total, attempt-to-submit ${uploadMs ?: -1}ms, " +
                "attempt-to-result ${resultMs ?: -1}ms, result-to-frame ${renderDelayMs ?: -1}ms, " +
                "preparation ${attempt.preparationMs ?: -1}ms, trim-export ${attempt.trimExportMs ?: -1}ms, " +
                "trim-video-bitrate ${attempt.trimVideoBitrateBps?.let { "%.2fMbit/s".format(it / 1e6) } ?: "unknown"}, " +
                "confirm-to-render ${confirmationMs ?: -1}ms, $countDetails" +
                ", polls ${attempt.pollCount}" +
                (if (transportMs.isBlank()) "" else ", transport [$transportMs]")
            EventLog.info(app, "Round 2 phone timing: $details",
                "attempt ${attempt.attemptId} · job $jobId · trace ${attempt.traceId}")
        }
    }

    /** A failed work leaves the list, and its clip goes with it. */
    fun dismissAllFailed() {
        val app = getApplication<Application>()
        WorkStore.all(app).filter { it.status == WorkStore.STATUS_FAILED }.forEach {
            dismissWork(it.id)
        }
    }

    fun dismissWork(workId: String) {
        val app = getApplication<Application>()
        val work = WorkStore.get(app, workId) ?: return
        if (work.jobId.isNotBlank()) {
            viewModelScope.launch {
                runCatching { withContext(Dispatchers.IO) {
                    if (work.uploadId.isNotBlank()) api.abortUpload(work.jobId)
                    api.deleteJob(work.jobId)
                } }
            }
        }
        java.io.File(work.clipPath).delete()
        WorkStore.forget(app, workId)
        if (_state.value.workLogId == workId) _state.update { it.copy(workLogId = null) }
        publishWorks()
    }

    fun openWorkLog(workId: String) = _state.update { it.copy(screen = Screen.WorkLog, workLogId = workId) }
    fun closeWorkLog() = _state.update { it.copy(screen = Screen.Home, workLogId = null) }

    fun workLog(): Work? {
        val id = _state.value.workLogId ?: return null
        return WorkStore.get(getApplication(), id)
    }

    fun deleteCurrent() {
        val job = _state.value.current ?: return
        val app = getApplication<Application>()
        viewModelScope.launch {
            runCatching { withContext(Dispatchers.IO) { api.deleteJob(job.id) } }
                .onSuccess {
                    SessionStore.forget(app, job.id)
                    WorkStore.all(app).filter { it.jobId == job.id }
                        .forEach { WorkStore.forget(app, it.id) }
                    // The phone's copy of the clip goes with the session.
                    clipFile(app, job.id).delete()
                    _state.update {
                        it.copy(
                            current = null,
                            analysis = null,
                            days = SessionStore.days(app),
                faults = SessionStore.faults(app),
                            selectedDate = null,
                        )
                    }
                    refresh()
                }
                .onFailure { err ->
                    EventLog.error(app, "could not delete a clip", err.message.orEmpty(),
                        jobId = job.id)
                    _state.update { it.copy(error = err.message) }
                }
        }
    }

    override fun onCleared() {
        runCatching {
            (getApplication<Application>().getSystemService(
                android.content.Context.CONNECTIVITY_SERVICE)
                as android.net.ConnectivityManager)
                .unregisterNetworkCallback(netCallback)
        }
        super.onCleared()
    }

    /** A validated network is back: whatever paused for it carries on. */
    private fun resumeConnectingWorks() {
        if (WorkStore.all(getApplication()).any { it.status == WorkStore.STATUS_CONNECTING }) uploads.kick()
    }

    // ---- coach ------------------------------------------------------------
    fun suggestions(): List<String> {
        val days = _state.value.days
        return buildList {
            add("What did my last session actually show?")
            if (days.size >= 2) add("Am I getting better, or is that just noise?")
            add("Why do some of my reps not get a score?")
            add("How should I film the next one?")
        }
    }

    fun ask(question: String) {
        val app = getApplication<Application>()
        SessionStore.appendChat(app, ChatTurn(fromUser = true, text = question))
        _state.update { it.copy(chat = SessionStore.chat(app), coachThinking = true) }
        viewModelScope.launch {
            try {
                val snapshot = _state.value
                val answer = withContext(Dispatchers.Default) {
                    Coach.answer(question, snapshot.days, snapshot.profile)
                }
                delay(250)
                SessionStore.appendChat(app, ChatTurn(fromUser = false, text = answer))
            } catch (t: Throwable) {
                // A crash must never leave the chat stuck thinking with no
                // answer - say the coach fell over, and let the user retry.
                SessionStore.appendChat(app, ChatTurn(fromUser = false,
                    text = "I could not answer that just now. Ask again, or rephrase it."))
            } finally {
                _state.update { it.copy(chat = SessionStore.chat(app), coachThinking = false) }
            }
        }
    }

    fun clearChat() {
        val app = getApplication<Application>()
        SessionStore.clearChat(app)
        _state.update { it.copy(chat = emptyList()) }
    }

    // ---- objectives intake -------------------------------------------------
    fun openObjectives() {
        _state.update { it.copy(screen = Screen.Objectives) }
        if (_state.value.objectives.isEmpty()) objectivesStart()
    }

    fun closeObjectives() {
        val complete = _state.value.profile.complete
        _state.update { it.copy(screen = if (complete) Screen.Home else Screen.Onboarding) }
        if (complete) refresh()
    }

    private fun objectivesStart() {
        val app = getApplication<Application>()
        _state.update { it.copy(objectivesThinking = true) }
        viewModelScope.launch {
            runCatching { withContext(Dispatchers.IO) { api.chat(emptyList()) } }
                .onSuccess { res ->
                    applyGoals(app, res.goals)
                    _state.update {
                        it.copy(
                            objectives = listOf(ChatTurn(fromUser = false, text = res.reply)),
                            objectivesThinking = false,
                            goals = it.goals ?: res.goals,
                        )
                    }
                }
                .onFailure { err ->
                    EventLog.error(app, "objectives intake failed", err.message.orEmpty())
                    _state.update {
                        it.copy(
                            objectivesThinking = false,
                            objectives = listOf(
                                ChatTurn(fromUser = false, text = "I could not reach the " +
                                    "objectives service. Check your connection and try again.")
                            ),
                        )
                    }
                }
        }
    }

    fun sendObjectives(text: String) {
        val app = getApplication<Application>()
        val userTurn = ChatTurn(fromUser = true, text = text)
        val turns = _state.value.objectives + userTurn
        _state.update { it.copy(objectives = turns, objectivesThinking = true) }
        viewModelScope.launch {
            val messages = turns.map { (if (it.fromUser) "user" else "assistant") to it.text }
            runCatching { withContext(Dispatchers.IO) { api.chat(messages) } }
                .onSuccess { res ->
                    applyGoals(app, res.goals)
                    _state.update {
                        it.copy(
                            objectives = turns + ChatTurn(fromUser = false, text = res.reply),
                            objectivesThinking = false,
                            goals = it.goals ?: res.goals,
                        )
                    }
                }
                .onFailure { err ->
                    EventLog.error(app, "objectives intake failed", err.message.orEmpty())
                    _state.update { it.copy(objectivesThinking = false, error = err.message) }
                }
        }
    }

    /** Fold the model's goals into the profile and the goals store. Blank parts
     *  of the profile are left alone, so a partial answer never wipes a field
     *  the user filled in during onboarding. */
    private fun applyGoals(app: Application, goals: Goals?) {
        if (goals == null) return
        val profile = _state.value.profile
        val activity = ActivityLevel.entries
            .firstOrNull { it.name.equals(goals.activity, ignoreCase = true) }
            ?: profile.activity
        val updated = profile.copy(
            name = goals.name.ifBlank { profile.name },
            age = if (goals.age > 0) goals.age else profile.age,
            activity = activity,
        )
        ProfileStore.save(app, updated)
        GoalsStore.save(app, Goals(
            goal = goals.goal.ifBlank { GoalsStore.load(app).goal },
            focusExercise = goals.focusExercise.ifBlank { GoalsStore.load(app).focusExercise },
        ))
        _state.update { it.copy(profile = updated, goals = goals) }
    }
}
