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
import com.barrapp.notify.ProcessingNotifier
import com.barrapp.notify.WeeklyReviewWorker
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job as CoroutineJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class Screen { Privacy, Onboarding, Home, Processing, Coach, Diagnostics, Objectives }

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
    /** Named stage, so the wait shows its shape instead of a fake percentage. */
    val stage: String = "",
    val busy: Boolean = false,
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
    private var poll: CoroutineJob? = null

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
                days = SessionStore.days(app),
                chat = SessionStore.chat(app),
                weeklyNote = WeeklyReviewWorker.buildReview(app)?.body,
            )
        }
        if (screen == Screen.Home) {
            WeeklyReviewWorker.schedule(app)
            refresh()
        }
    }

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
        poll?.cancel()
        _state.update { it.copy(screen = Screen.Home, error = null) }
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

    // ---- upload -----------------------------------------------------------
    fun recordIntent(): Intent = Intent(MediaStore.ACTION_VIDEO_CAPTURE)

    /**
     * One tap from picking a clip to a measured session.
     *
     * The exercise is not asked for. It is detected from the clip, which is one
     * fewer decision at the moment someone just wants to see their set.
     */
    fun upload(uri: Uri?) {
        val video = uri ?: return
        val app = getApplication<Application>()
        EventLog.info(app, "upload started")
        _state.update {
            it.copy(
                screen = Screen.Processing,
                busy = true,
                error = null,
                stage = STAGE_UPLOAD,
                analysis = null,
            )
        }
        ProcessingNotifier.stage(app, STAGE_UPLOAD)
        viewModelScope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    val created = api.createJob("auto")
                    _state.update { it.copy(current = created.job) }
                    api.uploadVideo(app, created.uploadUrl, created.uploadMethod, video)
                    _state.update { it.copy(stage = STAGE_DETECT) }
                    ProcessingNotifier.stage(app, STAGE_DETECT)
                    api.submit(created.job.id)
                }
            }.onSuccess { job ->
                _state.update { it.copy(current = job, stage = STAGE_TRIM) }
                ProcessingNotifier.stage(app, STAGE_TRIM)
                watch(job.id)
            }.onFailure { err ->
                EventLog.error(app, "upload failed", err.message.orEmpty(),
                    jobId = _state.value.current?.id.orEmpty())
                ProcessingNotifier.fail(app, err.message ?: "That clip could not be sent.")
                _state.update {
                    it.copy(
                        busy = false,
                        screen = Screen.Home,
                        error = err.message ?: "That clip could not be sent.",
                        stage = "",
                    )
                }
            }
        }
    }

    fun cancelUpload() {
        poll?.cancel()
        ProcessingNotifier.cancel(getApplication())
        _state.update { it.copy(screen = Screen.Home, busy = false, stage = "", error = null) }
    }

    private fun watch(jobId: String) {
        val app = getApplication<Application>()
        poll?.cancel()
        poll = viewModelScope.launch {
            repeat(240) {
                val job = runCatching {
                    withContext(Dispatchers.IO) { api.getJob(jobId) }
                }.getOrElse { err ->
                    EventLog.error(app, "lost contact while measuring",
                        err.message.orEmpty(), jobId = jobId)
                    ProcessingNotifier.fail(app, err.message ?: "Lost contact with the server.")
                    _state.update {
                        it.copy(error = err.message, busy = false, screen = Screen.Home)
                    }
                    return@launch
                }
                val stage = if (_state.value.stage == STAGE_TRIM) STAGE_MEASURE else _state.value.stage
                _state.update {
                    it.copy(
                        current = job,
                        stage = stage,
                    )
                }
                ProcessingNotifier.stage(app, stage)
                if (job.status == "done") {
                    job.result?.let { SessionStore.record(app, job.id, it) }
                    // The trace id is the whole point of logging a success:
                    // it is what turns "that session looks wrong" into
                    // `barra explain --replay <id>`.
                    EventLog.info(
                        app,
                        "measured ${job.result?.repCount ?: 0} rep(s) of " +
                            (job.result?.exercise ?: "unknown"),
                        "score ${job.result?.sessionScore ?: "—"}",
                        traceId = job.result?.traceId.orEmpty(), jobId = job.id,
                    )
                    ProcessingNotifier.done(
                        app,
                        "Measured ${job.result?.repCount ?: 0} rep${if (job.result?.repCount == 1) "" else "s"}",
                        "Your ${job.result?.detected?.label ?: job.result?.exercise?.replace('_', ' ') ?: "clip"} is ready.",
                    )
                    _state.update {
                        it.copy(
                            screen = Screen.Home,
                            pane = Pane.Session,
                            busy = false,
                            stage = "",
                            analysis = job.result,
                            selectedDate = job.result?.sessionDate ?: SessionStore.today(),
                            days = SessionStore.days(app),
                            weeklyNote = WeeklyReviewWorker.buildReview(app)?.body,
                        )
                    }
                    return@launch
                }
                if (job.status == "failed") {
                    EventLog.error(app, "the server could not use that clip",
                        job.error.orEmpty(),
                        traceId = job.result?.traceId.orEmpty(), jobId = job.id)
                    ProcessingNotifier.fail(app, job.error ?: "The server could not use that clip.")
                    _state.update {
                        it.copy(
                            screen = Screen.Home,
                            busy = false,
                            stage = "",
                            error = job.error ?: "The server could not use that clip.",
                        )
                    }
                    return@launch
                }
                delay(1000)
            }
            EventLog.warn(app, "measuring timed out on the phone",
                "the job may still finish on the server", jobId = jobId)
            ProcessingNotifier.fail(app, "Still measuring. It will appear in your calendar when it finishes.")
            _state.update {
                it.copy(
                    busy = false,
                    screen = Screen.Home,
                    stage = "",
                    error = "The server is taking longer than usual. It will appear in your " +
                        "calendar when it finishes.",
                )
            }
        }
    }

    fun deleteCurrent() {
        val job = _state.value.current ?: return
        val app = getApplication<Application>()
        viewModelScope.launch {
            runCatching { withContext(Dispatchers.IO) { api.deleteJob(job.id) } }
                .onSuccess {
                    SessionStore.forget(app, job.id)
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

    companion object {
        const val STAGE_UPLOAD = "Uploading the clip"
        const val STAGE_DETECT = "Finding the exercise"
        const val STAGE_TRIM = "Trimming to the working set"
        const val STAGE_MEASURE = "Counting and measuring the reps"
    }
}
