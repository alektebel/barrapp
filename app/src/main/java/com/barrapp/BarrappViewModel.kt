package com.barrapp

import android.app.Application
import android.content.Intent
import android.net.Uri
import android.provider.MediaStore
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.barrapp.data.Analysis
import com.barrapp.data.BarraApi
import com.barrapp.data.ChatTurn
import com.barrapp.data.DayEntry
import com.barrapp.data.Job
import com.barrapp.data.Profile
import com.barrapp.data.ProfileStore
import com.barrapp.data.SessionStore
import com.barrapp.notify.WeeklyReviewWorker
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job as CoroutineJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class Screen { Privacy, Onboarding, Home, Processing, Coach }

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
    val weeklyNote: String? = null,
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
        _state.update {
            it.copy(
                screen = Screen.Processing,
                busy = true,
                error = null,
                stage = STAGE_UPLOAD,
                analysis = null,
            )
        }
        viewModelScope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    val created = api.createJob("auto")
                    _state.update { it.copy(current = created.job) }
                    api.uploadVideo(app, created.uploadUrl, created.uploadMethod, video)
                    _state.update { it.copy(stage = STAGE_DETECT) }
                    api.submit(created.job.id)
                }
            }.onSuccess { job ->
                _state.update { it.copy(current = job, stage = STAGE_TRIM) }
                watch(job.id)
            }.onFailure { err ->
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
        _state.update { it.copy(screen = Screen.Home, busy = false, stage = "", error = null) }
    }

    private fun watch(jobId: String) {
        val app = getApplication<Application>()
        poll?.cancel()
        poll = viewModelScope.launch {
            repeat(120) {
                val job = runCatching {
                    withContext(Dispatchers.IO) { api.getJob(jobId) }
                }.getOrElse { err ->
                    _state.update {
                        it.copy(error = err.message, busy = false, screen = Screen.Home)
                    }
                    return@launch
                }
                _state.update {
                    it.copy(
                        current = job,
                        stage = if (it.stage == STAGE_TRIM) STAGE_MEASURE else it.stage,
                    )
                }
                if (job.status == "done") {
                    job.result?.let { SessionStore.record(app, job.id, it) }
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
                delay(2500)
            }
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
                .onFailure { err -> _state.update { it.copy(error = err.message) } }
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
            val answer = withContext(Dispatchers.Default) {
                Coach.answer(question, _state.value)
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

    companion object {
        const val STAGE_UPLOAD = "Uploading the clip"
        const val STAGE_DETECT = "Finding the exercise"
        const val STAGE_TRIM = "Trimming to the working set"
        const val STAGE_MEASURE = "Counting and measuring the reps"
    }
}
