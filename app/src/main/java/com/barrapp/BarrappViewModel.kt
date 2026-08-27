package com.barrapp

import android.app.Application
import android.content.Intent
import android.net.Uri
import android.provider.MediaStore
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.barrapp.data.Analysis
import com.barrapp.data.BarraApi
import com.barrapp.data.Job
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job as CoroutineJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class Screen { Privacy, Home, Capture, Report }

data class UiState(
    val screen: Screen = Screen.Privacy,
    val exercise: String = "muscle_up",
    val video: Uri? = null,
    val status: String = "",
    val busy: Boolean = false,
    val error: String? = null,
    val jobs: List<Job> = emptyList(),
    val current: Job? = null,
    val demo: Analysis? = null,
)

class BarrappViewModel(application: Application) : AndroidViewModel(application) {
    private val api = BarraApi(application)
    private val _state = MutableStateFlow(
        UiState(screen = if (DeviceId.privacyAccepted(application)) Screen.Home else Screen.Privacy)
    )
    val state: StateFlow<UiState> = _state
    private var poll: CoroutineJob? = null

    init {
        if (DeviceId.privacyAccepted(getApplication())) {
            refresh()
        }
    }

    fun acceptPrivacy() {
        DeviceId.acceptPrivacy(getApplication())
        _state.update { it.copy(screen = Screen.Home) }
        refresh()
    }

    fun openPrivacy() {
        _state.update { it.copy(screen = Screen.Privacy) }
    }

    fun refresh() {
        viewModelScope.launch {
            runCatching {
                withContext(Dispatchers.IO) { api.listJobs() }
            }.onSuccess { jobs ->
                _state.update { it.copy(jobs = jobs, error = null) }
            }
        }
    }

    fun openCapture() {
        _state.update {
            it.copy(screen = Screen.Capture, error = null, current = null, demo = null, video = null, status = "")
        }
    }

    fun openHome() {
        poll?.cancel()
        _state.update { it.copy(screen = Screen.Home, error = null) }
        refresh()
    }

    fun setExercise(value: String) {
        _state.update { it.copy(exercise = value) }
    }

    fun setVideo(uri: Uri?) {
        _state.update { it.copy(video = uri, error = null) }
    }

    fun recordIntent(): Intent = Intent(MediaStore.ACTION_VIDEO_CAPTURE)

    fun openJob(job: Job) {
        poll?.cancel()
        _state.update { it.copy(screen = Screen.Report, current = job, demo = null, error = null) }
        if (job.status != "done" && job.status != "failed") {
            watch(job.id)
        }
    }

    fun openDemo() {
        val analysis = BarraApi.sampleFromAssets(getApplication())
        _state.update {
            it.copy(
                screen = Screen.Report,
                demo = analysis,
                current = null,
                error = null,
            )
        }
    }

    fun send() {
        val video = _state.value.video ?: return
        val exercise = _state.value.exercise
        viewModelScope.launch {
            _state.update { it.copy(busy = true, error = null, status = "Creating job…") }
            runCatching {
                withContext(Dispatchers.IO) {
                    val created = api.createJob(exercise)
                    _state.update { it.copy(status = "Uploading clip…", current = created.job) }
                    api.uploadVideo(
                        getApplication(),
                        created.uploadUrl,
                        created.uploadMethod,
                        video,
                    )
                    _state.update { it.copy(status = "Measuring on the server…") }
                    api.submit(created.job.id)
                }
            }.onSuccess { job ->
                _state.update {
                    it.copy(
                        busy = false,
                        screen = Screen.Report,
                        current = job,
                        status = job.status,
                    )
                }
                watch(job.id)
            }.onFailure { err ->
                _state.update {
                    it.copy(busy = false, error = err.message ?: "Upload failed", status = "")
                }
            }
        }
    }

    fun deleteCurrent() {
        val id = _state.value.current?.id ?: return
        viewModelScope.launch {
            runCatching {
                withContext(Dispatchers.IO) { api.deleteJob(id) }
            }.onSuccess {
                _state.update { it.copy(current = null, demo = null, screen = Screen.Home) }
                refresh()
            }.onFailure { err ->
                _state.update { it.copy(error = err.message) }
            }
        }
    }

    private fun watch(jobId: String) {
        poll?.cancel()
        poll = viewModelScope.launch {
            repeat(120) {
                val job = runCatching {
                    withContext(Dispatchers.IO) { api.getJob(jobId) }
                }.getOrElse { err ->
                    _state.update { it.copy(error = err.message, busy = false) }
                    return@launch
                }
                _state.update { it.copy(current = job, status = job.status, busy = job.status == "processing" || job.status == "queued") }
                if (job.status == "done" || job.status == "failed") return@launch
                delay(3000)
            }
        }
    }
}
