package com.barrapp

import android.app.Application
import android.content.Intent
import android.net.Uri
import android.provider.MediaStore
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.barrapp.data.ActivityLevel
import com.barrapp.data.Analysis
import com.barrapp.data.BarraApi
import com.barrapp.data.ChatTurn
import com.barrapp.data.DayEntry
import com.barrapp.data.EventLog
import com.barrapp.data.Goals
import com.barrapp.data.GoalsStore
import com.barrapp.data.Job
import com.barrapp.data.Profile
import com.barrapp.data.ProfileStore
import com.barrapp.data.SessionStore
import com.barrapp.data.Work
import com.barrapp.data.WorkStore
import com.barrapp.notify.ProcessingNotifier
import com.barrapp.notify.WeeklyReviewWorker
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class Screen { Privacy, Onboarding, Home, Coach, Diagnostics, Objectives, Replay, Plan, WorkLog }

/** Which pane the compact layout is showing. Wide layouts show all three. */
enum class Pane { Calendar, Session, Progress }

data class UiState(
    val screen: Screen = Screen.Privacy,
    val pane: Pane = Pane.Session,
    val profile: Profile = Profile(),
    val days: List<DayEntry> = emptyList(),
    val jobs: List<Job> = emptyList(),
    val selectedDate: String? = null,
    val current: Job? = null,
    val analysis: Analysis? = null,
    /** Every clip on its way to being a session: the works in progress, the
     *  ones waiting, and the ones that went wrong with their reason. */
    val works: List<Work> = emptyList(),
    val workLogId: String? = null,
    val error: String? = null,
    val chat: List<ChatTurn> = emptyList(),
    val coachThinking: Boolean = false,
    val objectives: List<ChatTurn> = emptyList(),
    val objectivesThinking: Boolean = false,
    val goals: Goals? = null,
    val weeklyNote: String? = null,
    val events: List<EventLog.Event> = emptyList(),
)

class BarrappViewModel(application: Application) : AndroidViewModel(application) {
    private val api = BarraApi(application)
    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state

    /** The work queue. Declared before the init block below on purpose: the
     *  consumer it launches runs on Main.immediate, which is still inside
     *  this constructor, and a property read before its own initialiser is
     *  the kind of crash that takes the app down on open. */
    private val queue = Channel<String>(Channel.UNLIMITED)

    init {
        val app = getApplication<Application>()
        val profile = ProfileStore.load(app)
        val screen = when {
            !DeviceId.privacyAccepted(app) -> Screen.Privacy
            !profile.complete -> Screen.Onboarding
            else -> Screen.Home
        }
        // A work still marked active was mid-flight when the process died.
        // It is not lost - the clip is on the phone - but it is not going
        // anywhere on its own either, so it becomes a failed work with a
        // reason and a Retry, rather than a lie that says "measuring".
        val stale = WorkStore.all(app).filter { it.active }
        stale.forEach { w ->
            WorkStore.put(app, w.copy(
                status = WorkStore.STATUS_FAILED,
                stage = "",
                error = "The app closed while this clip was in the queue.",
            ).let { it.copy(log = it.log + WorkStore.Entry(
                System.currentTimeMillis(), WorkStore.Level.WARN,
                "interrupted — the app closed; retry to send it again")) })
        }
        _state.update {
            it.copy(
                screen = screen,
                profile = profile,
                goals = GoalsStore.load(app),
                days = SessionStore.days(app),
                chat = SessionStore.chat(app),
                works = WorkStore.all(app),
                weeklyNote = WeeklyReviewWorker.buildReview(app)?.body,
            )
        }
        viewModelScope.launch { consumeQueue() }
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
                        _state.update { it.copy(days = SessionStore.days(app)) }
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
        val id = _state.value.current?.id ?: return null
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

    fun saveProfile(profile: Profile) {
        val app = getApplication<Application>()
        ProfileStore.save(app, profile)
        WeeklyReviewWorker.schedule(app)
        _state.update { it.copy(profile = profile, screen = Screen.Home) }
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
        if (known?.result != null) {
            _state.update { it.copy(analysis = known.result, current = known) }
            return
        }
        viewModelScope.launch {
            runCatching { withContext(Dispatchers.IO) { api.getJob(jobId) } }
                .onSuccess { job ->
                    _state.update { it.copy(current = job, analysis = job.result) }
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
                    jobs.filter { it.status == "done" && it.result != null }
                        .forEach { SessionStore.record(app, it.id, it.result!!) }
                    _state.update {
                        it.copy(
                            jobs = jobs,
                            days = SessionStore.days(app),
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
    fun upload(uri: Uri?) {
        val video = uri ?: return
        val app = getApplication<Application>()
        val workId = java.util.UUID.randomUUID().toString().replace("-", "").take(12)
        val dest = clipFile(app, workId)
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
            val work = Work(
                id = workId,
                createdAt = System.currentTimeMillis(),
                status = if (kept) WorkStore.STATUS_WAITING else WorkStore.STATUS_FAILED,
                clipPath = dest.absolutePath,
                error = if (kept) null else "The clip could not be kept on the phone.",
                log = buildList {
                    add(WorkStore.Entry(System.currentTimeMillis(), WorkStore.Level.INFO,
                        "clip added to the queue"))
                    if (!kept) add(WorkStore.Entry(System.currentTimeMillis(),
                        WorkStore.Level.ERROR, "the clip could not be read or kept"))
                },
            )
            WorkStore.put(app, work)
            EventLog.info(app, "clip added to the queue", workId)
            publishWorks()
            if (kept) queue.send(workId)
        }
    }

    private fun publishWorks() {
        _state.update { it.copy(works = WorkStore.all(getApplication())) }
    }

    private suspend fun consumeQueue() {
        for (workId in queue) {
            val app = getApplication<Application>()
            val work = WorkStore.get(app, workId) ?: continue
            runWork(work.copy(status = WorkStore.STATUS_WAITING))
        }
    }

    private suspend fun runWork(work: Work) {
        val app = getApplication<Application>()

        fun update(transform: (Work) -> Work) {
            val current = WorkStore.get(app, work.id) ?: return
            WorkStore.put(app, transform(current))
            publishWorks()
        }

        fun log(level: WorkStore.Level, message: String) {
            WorkStore.append(app, work.id, level, message)
        }

        fun fail(message: String, traceId: String = "") {
            log(WorkStore.Level.ERROR, message)
            update {
                it.copy(status = WorkStore.STATUS_FAILED, stage = "", error = message,
                    traceId = traceId.ifBlank { it.traceId })
            }
            EventLog.error(app, "a work failed", message,
                jobId = WorkStore.get(app, work.id)?.jobId.orEmpty())
            ProcessingNotifier.fail(app, message)
        }

        val clip = java.io.File(work.clipPath)
        update { it.copy(status = WorkStore.STATUS_WAITING, stage = "waiting to be sent",
            error = null) }
        try {
            if (!clip.exists() || clip.length() == 0L) {
                fail("The clip is no longer on the phone.")
                return
            }
            val created = withContext(Dispatchers.IO) { api.createJob("auto") }
            val jobId = created.job.id
            update { it.copy(jobId = jobId, status = WorkStore.STATUS_SENDING,
                stage = "sending the clip") }
            log(WorkStore.Level.INFO, "job $jobId created — sending the clip " +
                "(%.1f MB)".format(clip.length() / 1e6))
            ProcessingNotifier.stage(app, "Sending the clip")
            withContext(Dispatchers.IO) { api.uploadClip(clip, created.uploadUrl, created.uploadMethod) }
            update { it.copy(status = WorkStore.STATUS_QUEUED, stage = "queued on the server") }
            log(WorkStore.Level.INFO, "uploaded — queued on the server")
            ProcessingNotifier.stage(app, "Queued on the server")
            withContext(Dispatchers.IO) { api.submit(jobId) }

            // The wait. The server says where it is; the log keeps what it
            // said, so a wrong number later has a trail to be explained by.
            var contactLost = 0
            repeat(240) {
                val job = withContext(Dispatchers.IO) { runCatching { api.getJob(jobId) } }
                job.fold(onSuccess = { j ->
                    contactLost = 0
                    when (j.status) {
                        "done" -> {
                            j.result?.let { SessionStore.record(app, j.id, it) }
                            log(WorkStore.Level.INFO, "measured " +
                                "${j.result?.repCount ?: 0} rep(s) of " +
                                (j.result?.exercise ?: "unknown") +
                                " — trace ${j.result?.traceId.orEmpty()}")
                            // The clip answers to its job id from here on, so
                            // replay and delete keep working the way they did.
                            withContext(Dispatchers.IO) {
                                clip.renameTo(clipFile(app, j.id))
                            }
                            EventLog.info(app,
                                "measured ${j.result?.repCount ?: 0} rep(s) of " +
                                    (j.result?.exercise ?: "unknown"),
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
                                    "Standard cleared — ${verdict.step.towardsLabel} unlocked",
                                    "You have now met the ${verdict.label} standard on " +
                                        "${verdict.step.days} separate days. The Plan page has the call.",
                                )
                            } else {
                                ProcessingNotifier.done(
                                    app,
                                    "Measured ${j.result?.repCount ?: 0} rep${if (j.result?.repCount == 1) "" else "s"}",
                                    "Your ${j.result?.detected?.label ?: j.result?.exercise?.replace('_', ' ') ?: "clip"} is ready.",
                                )
                            }
                            WorkStore.forget(app, work.id)
                            publishWorks()
                            _state.update {
                                it.copy(
                                    screen = Screen.Home,
                                    pane = Pane.Session,
                                    analysis = j.result,
                                    current = j,
                                    selectedDate = j.result?.sessionDate
                                        ?: SessionStore.today(),
                                    days = SessionStore.days(app),
                                    weeklyNote = WeeklyReviewWorker.buildReview(app)?.body,
                                    error = null,
                                )
                            }
                            refresh()
                            return
                        }
                        "failed" -> {
                            fail(j.error ?: "The server could not use that clip.",
                                j.result?.traceId.orEmpty())
                            return
                        }
                        else -> {
                            val stage = j.stage.ifBlank {
                                if (j.status == "queued") "queued on the server" else "measuring"
                            }
                            update {
                                it.copy(
                                    status = if (j.status == "processing")
                                        WorkStore.STATUS_MEASURING else WorkStore.STATUS_QUEUED,
                                    stage = stage,
                                )
                            }
                            ProcessingNotifier.stage(app, stage.replaceFirstChar { c -> c.uppercaseChar() })
                        }
                    }
                }, onFailure = { err ->
                    contactLost++
                    log(WorkStore.Level.WARN,
                        "lost contact with the server (${contactLost}) — ${err.message.orEmpty()}")
                    if (contactLost >= 5) {
                        fail("Lost contact with the server while measuring.")
                        return
                    }
                })
                delay(1000)
            }
            fail("Still measuring after four minutes. It may yet finish on the server — " +
                "retry to check again.")
        } catch (err: Exception) {
            fail(err.message ?: "That clip could not be sent.")
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
            WorkStore.put(app, work.copy(status = WorkStore.STATUS_WAITING, error = null,
                stage = "waiting to be sent", traceId = "",
                log = work.log + WorkStore.Entry(System.currentTimeMillis(),
                    WorkStore.Level.INFO, "retry requested")))
            publishWorks()
            queue.send(workId)
        }
    }

    /** A failed work leaves the list, and its clip goes with it. */
    fun dismissWork(workId: String) {
        val app = getApplication<Application>()
        val work = WorkStore.get(app, workId) ?: return
        if (work.jobId.isNotBlank()) {
            viewModelScope.launch {
                runCatching { withContext(Dispatchers.IO) { api.deleteJob(work.jobId) } }
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
        val turn = ChatTurn(fromUser = true, text = question)
        SessionStore.appendChat(app, turn)
        _state.update { it.copy(chat = SessionStore.chat(app), coachThinking = true) }
        viewModelScope.launch {
            val snapshot = _state.value
            val answer = withContext(Dispatchers.Default) {
                Coach.answer(question, snapshot.days, snapshot.profile)
            }
            delay(250)
            SessionStore.appendChat(app, ChatTurn(fromUser = false, text = answer))
            _state.update { it.copy(chat = SessionStore.chat(app), coachThinking = false) }
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
