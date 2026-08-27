package com.barrapp.ui

import android.app.Activity
import android.content.Intent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.barrapp.BarrappViewModel
import com.barrapp.DeviceId
import com.barrapp.Screen
import com.barrapp.data.Analysis
import com.barrapp.data.Job

private val exercises = listOf(
    "muscle_up" to "Muscle-up",
    "pull_up" to "Pull-up",
    "dip" to "Dip",
    "squat" to "Squat",
)

@Composable
fun BarrappApp(vm: BarrappViewModel = viewModel()) {
    val state by vm.state.collectAsStateWithLifecycle()
    Box(Modifier.fillMaxSize().safeDrawingPadding()) {
        when (state.screen) {
        Screen.Privacy -> PrivacyScreen(onAccept = vm::acceptPrivacy, showBack = DeviceId.privacyAccepted(LocalContext.current), onBack = vm::openHome)
        Screen.Home -> HomeScreen(state.jobs, vm::openCapture, vm::openDemo, vm::openJob, vm::openPrivacy)
        Screen.Capture -> CaptureScreen(vm)
        Screen.Report -> {
            val analysis = state.demo ?: state.current?.result
            ReportScreen(
                status = state.current?.status ?: if (state.demo != null) "done" else state.status,
                error = state.current?.error ?: state.error,
                analysis = analysis,
                canDelete = state.current != null,
                onBack = vm::openHome,
                onDelete = vm::deleteCurrent,
            )
        }
        }
    }
}

@Composable
private fun HomeScreen(
    jobs: List<Job>,
    onFilm: () -> Unit,
    onDemo: () -> Unit,
    onOpen: (Job) -> Unit,
    onPrivacy: () -> Unit,
) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Text("barrapp", style = MaterialTheme.typography.headlineLarge)
            Spacer(Modifier.height(8.dp))
            Text(
                "Film a set. The server measures it against your own variation. No score, no coaching.",
                style = MaterialTheme.typography.bodyLarge,
            )
            Spacer(Modifier.height(20.dp))
            Button(onClick = onFilm, modifier = Modifier.fillMaxWidth()) {
                Text("Film a set")
            }
            TextButton(onClick = onDemo) {
                Text("Open the Aug 2026 muscle-up block")
            }
            TextButton(onClick = onPrivacy) {
                Text("Privacy")
            }
            Spacer(Modifier.height(12.dp))
            Text("Recent", style = MaterialTheme.typography.titleMedium)
        }
        if (jobs.isEmpty()) {
            item { Text("Nothing uploaded yet.", color = MaterialTheme.colorScheme.onSurfaceVariant) }
        }
        items(jobs, key = { it.id }) { job ->
            Column(
                Modifier
                    .fillMaxWidth()
                    .clickable { onOpen(job) }
                    .padding(vertical = 8.dp)
            ) {
                Text("${job.exercise.replace('_', ' ')}  ·  ${job.status}")
                Text(
                    job.createdAt.ifBlank { job.id },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun CaptureScreen(vm: BarrappViewModel) {
    val state by vm.state.collectAsStateWithLifecycle()
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        vm.setVideo(uri)
    }
    val record = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            vm.setVideo(result.data?.data)
        }
    }

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp)
    ) {
        TextButton(onClick = vm::openHome) { Text("Back") }
        Text("New set", style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(16.dp))
        Text("Movement")
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            exercises.forEach { (id, label) ->
                FilterChip(
                    selected = state.exercise == id,
                    onClick = { vm.setExercise(id) },
                    label = { Text(label) },
                )
            }
        }
        Spacer(Modifier.height(20.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { record.launch(vm.recordIntent().also { it.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION) }) }) {
                Text("Record")
            }
            OutlinedButton(onClick = { pick.launch("video/*") }) {
                Text("Pick clip")
            }
        }
        Spacer(Modifier.height(8.dp))
        Text(
            if (state.video != null) "Clip attached." else "Tripod, same spot, whole lockout in frame, trim to the working set.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (state.busy) {
            Spacer(Modifier.height(16.dp))
            LinearProgressIndicator(Modifier.fillMaxWidth())
            Text(state.status)
        }
        state.error?.let {
            Spacer(Modifier.height(8.dp))
            Text(it, color = MaterialTheme.colorScheme.error)
        }
        Spacer(Modifier.height(24.dp))
        Button(
            onClick = vm::send,
            enabled = state.video != null && !state.busy,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("Send to server")
        }
    }
}

@Composable
private fun ReportScreen(
    status: String,
    error: String?,
    analysis: Analysis?,
    canDelete: Boolean,
    onBack: () -> Unit,
    onDelete: () -> Unit,
) {
    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp)
    ) {
        TextButton(onClick = onBack) { Text("Back") }
        when {
            analysis != null -> {
                AnalysisBody(analysis)
                if (canDelete) {
                    Spacer(Modifier.height(24.dp))
                    OutlinedButton(onClick = onDelete, modifier = Modifier.fillMaxWidth()) {
                        Text("Delete this clip")
                    }
                }
            }
            status == "failed" -> Text(error ?: "The server could not use this clip.", color = MaterialTheme.colorScheme.error)
            else -> {
                Text("Measuring…", style = MaterialTheme.typography.headlineMedium)
                Spacer(Modifier.height(12.dp))
                LinearProgressIndicator(Modifier.fillMaxWidth())
                Spacer(Modifier.height(8.dp))
                Text("This is not a score. The server is counting reps and checking whether the clip is even usable.")
                error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            }
        }
    }
}

@Composable
private fun AnalysisBody(analysis: Analysis) {
    Text(analysis.headline, style = MaterialTheme.typography.headlineMedium)
    Spacer(Modifier.height(16.dp))
    Text(analysis.narrative, style = MaterialTheme.typography.bodyLarge)
    if (analysis.sessions.isNotEmpty()) {
        Spacer(Modifier.height(20.dp))
        Text("Sessions", style = MaterialTheme.typography.titleMedium)
        analysis.sessions.forEach { row ->
            Text("${row.date}   ${row.reps} rep${if (row.reps == 1) "" else "s"}")
            if (row.note.isNotBlank()) {
                Text(row.note, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
    if (analysis.reps.isNotEmpty()) {
        Spacer(Modifier.height(20.dp))
        Text("Reps", style = MaterialTheme.typography.titleMedium)
        analysis.reps.forEach { row ->
            Spacer(Modifier.height(8.dp))
            Text(
                if (row.plausible) row.label else "${row.label} (rejected)",
                style = MaterialTheme.typography.titleSmall,
            )
            if (row.metrics.isNotEmpty()) {
                row.metrics.forEach { line ->
                    Text("${line.name}:  ${line.value}  ${line.cls}")
                }
            } else {
                Text(
                    "transition ${row.transitionS}s  total ${row.totalS}s  ${row.cls}",
                    fontFamily = FontFamily.Monospace,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            row.problems.forEach { Text(it, color = MaterialTheme.colorScheme.error) }
        }
    }
    if (analysis.blockers.isNotEmpty()) {
        Spacer(Modifier.height(20.dp))
        Text("Blockers", style = MaterialTheme.typography.titleMedium)
        analysis.blockers.forEach { Text("· $it") }
    }
    if (analysis.nextSession.isNotBlank()) {
        Spacer(Modifier.height(20.dp))
        Text("Next session", style = MaterialTheme.typography.titleMedium)
        Text(analysis.nextSession)
    }
}

@Composable
private fun PrivacyScreen(onAccept: () -> Unit, showBack: Boolean, onBack: () -> Unit) {
    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp)
    ) {
        if (showBack) {
            TextButton(onClick = onBack) { Text("Back") }
        }
        Text("Privacy", style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(12.dp))
        Text(
            "barrapp measures your own reps from a clip you send. It is not coaching and not medical advice.",
            style = MaterialTheme.typography.bodyLarge,
        )
        Spacer(Modifier.height(12.dp))
        Text("What we collect")
        Text("The video you upload, the exercise you pick, and a random device id stored on this phone. We do not ask for your name, email, or Google account.")
        Spacer(Modifier.height(12.dp))
        Text("What we do with it")
        Text("The clip is sent to our AWS server, which runs pose estimation and returns numbers (timing, range of motion). Clips are private to this device id, not public, and are deleted automatically after 30 days. You can delete a clip from its report.")
        Spacer(Modifier.height(12.dp))
        Text("What we do not do")
        Text("We do not sell data, run ads, or share clips. We do not diagnose injury or score 'good form'.")
        Spacer(Modifier.height(12.dp))
        Text("The full policy is also in docs/privacy.md in the project, which you must host at a public URL before Play Store review.")
        Spacer(Modifier.height(24.dp))
        if (!showBack) {
            Button(onClick = onAccept, modifier = Modifier.fillMaxWidth()) {
                Text("I understand — continue")
            }
        }
    }
}

