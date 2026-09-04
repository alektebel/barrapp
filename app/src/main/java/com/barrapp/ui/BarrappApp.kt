package com.barrapp.ui

import android.app.Activity
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Info
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.VerticalDivider
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.barrapp.BarrappViewModel
import com.barrapp.BuildConfig
import com.barrapp.DeviceId
import com.barrapp.Pane
import com.barrapp.Screen
import com.barrapp.data.ActivityLevel
import com.barrapp.data.Goals
import com.barrapp.data.Profile
import com.barrapp.ui.parts.Eyebrow
import com.barrapp.ui.parts.Panel
import com.barrapp.ui.parts.Pill

/**
 * The shell.
 *
 * One layout rule: below 840dp the three panes are one at a time with a bottom
 * bar; at or above it they sit side by side. There is no tablet build and no
 * phone build - the panes are the same composables either way, so a fix lands
 * in both. The breakpoint is measured from the window, not the device, so a
 * split-screen phone gets the compact layout it deserves.
 */
private val WIDE = 840.dp
private val CALENDAR_WIDTH = 300.dp
private val INSIGHT_WIDTH = 340.dp

@Composable
fun BarrappApp(vm: BarrappViewModel = viewModel()) {
    val state by vm.state.collectAsStateWithLifecycle()
    val context = LocalContext.current

    // Android 13+ asks before it may post anything. Requested on the way into
    // Home rather than on first launch, so the ask lands after the app has
    // shown what it is for.
    val notificationPermission = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { }
    LaunchedEffect(state.screen) {
        if (state.screen == Screen.Home && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            notificationPermission.launch(android.Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    val pickVideo = rememberLauncherForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri -> vm.upload(uri) }

    val recordVideo = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK) vm.upload(result.data?.data)
    }

    Box(
        Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .safeDrawingPadding()
    ) {
        when (state.screen) {
            Screen.Privacy -> PrivacyScreen(
                onAccept = vm::acceptPrivacy,
                showBack = DeviceId.privacyAccepted(context),
                onBack = vm::openHome,
                onDiagnostics = vm::openDiagnostics,
            )

            Screen.Onboarding -> Onboarding(
                initial = state.profile,
                onDone = vm::saveProfile,
                onObjectives = vm::openObjectives,
            )

            Screen.Objectives -> ObjectivesChatScreen(
                turns = state.objectives,
                thinking = state.objectivesThinking,
                goals = state.goals,
                onSend = vm::sendObjectives,
                onDone = vm::closeObjectives,
                onBack = vm::closeObjectives,
            )

            Screen.Processing -> ProcessingState(
                stage = state.stage,
                exerciseGuess = state.current?.result?.detected?.label,
                error = state.error,
                onCancel = vm::cancelUpload,
            )

            Screen.Diagnostics -> DiagnosticsScreen(
                events = state.events,
                latest = state.analysis,
                deviceId = DeviceId.get(context),
                apiBase = BuildConfig.API_BASE_URL,
                report = vm::diagnosticsReport,
                onClear = vm::clearEvents,
                onBack = vm::openHome,
            )

            Screen.Coach -> CoachScreen(
                turns = state.chat,
                thinking = state.coachThinking,
                suggestions = vm.suggestions(),
                onSend = vm::ask,
                onBack = vm::openHome,
            )

            Screen.Replay -> ReplayScreen(
                analysis = state.analysis,
                clip = remember(state.current?.id) { vm.replayClip() },
                onBack = vm::openHome,
            )

            Screen.Plan -> PlanScreen(
                days = state.days,
                goals = state.goals,
                onBack = vm::openHome,
            )

            Screen.Home -> HomeShell(
                vm = vm,
                onPick = { pickVideo.launch("video/*") },
                onRecord = { recordVideo.launch(vm.recordIntent()) },
            )
        }
    }
}

@Composable
private fun HomeShell(
    vm: BarrappViewModel,
    onPick: () -> Unit,
    onRecord: () -> Unit,
) {
    val state by vm.state.collectAsStateWithLifecycle()

    BoxWithConstraints(Modifier.fillMaxSize()) {
        val wide = maxWidth >= WIDE
        val medium = maxWidth >= 600.dp && !wide

        if (wide) {
            Row(Modifier.fillMaxSize()) {
                Column(Modifier.width(CALENDAR_WIDTH).fillMaxHeight()) {
                    ShellHeader(state.profile.firstName, vm::openPrivacy, vm::openPlan)
                    CalendarPane(
                        days = state.days,
                        selected = state.selectedDate,
                        onSelect = vm::selectDate,
                    )
                }
                VerticalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f))
                Box(Modifier.weight(1f).fillMaxHeight()) {
                    MainPane(vm, onPick, onRecord)
                }
                VerticalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f))
                Box(Modifier.width(INSIGHT_WIDTH).fillMaxHeight()) {
                    InsightPane(
                        days = state.days,
                        repTarget = state.profile.repTarget,
                        weeklyNote = state.weeklyNote,
                        onOpenCoach = vm::openCoach,
                    )
                }
            }
        } else if (medium) {
            Row(Modifier.fillMaxSize()) {
                Column(Modifier.width(CALENDAR_WIDTH).fillMaxHeight()) {
                    ShellHeader(state.profile.firstName, vm::openPrivacy, vm::openPlan)
                    CalendarPane(
                        days = state.days,
                        selected = state.selectedDate,
                        onSelect = vm::selectDate,
                    )
                }
                VerticalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f))
                Column(Modifier.weight(1f).fillMaxHeight()) {
                    Box(Modifier.weight(1f)) {
                        when (state.pane) {
                            Pane.Progress -> InsightPane(
                                days = state.days,
                                repTarget = state.profile.repTarget,
                                weeklyNote = state.weeklyNote,
                                onOpenCoach = vm::openCoach,
                            )
                            else -> MainPane(vm, onPick, onRecord)
                        }
                    }
                    CompactBar(
                        pane = state.pane,
                        showCalendar = false,
                        onSelect = vm::showPane,
                        onAdd = onPick,
                    )
                }
            }
        } else {
            Column(Modifier.fillMaxSize()) {
                ShellHeader(state.profile.firstName, vm::openPrivacy, vm::openPlan)
                Box(Modifier.weight(1f)) {
                    when (state.pane) {
                        Pane.Calendar -> CalendarPane(
                            days = state.days,
                            selected = state.selectedDate,
                            onSelect = vm::selectDate,
                        )
                        Pane.Progress -> InsightPane(
                            days = state.days,
                            repTarget = state.profile.repTarget,
                            weeklyNote = state.weeklyNote,
                            onOpenCoach = vm::openCoach,
                        )
                        Pane.Session -> MainPane(vm, onPick, onRecord)
                    }
                }
                CompactBar(
                    pane = state.pane,
                    showCalendar = true,
                    onSelect = vm::showPane,
                    onAdd = onPick,
                )
            }
        }
    }
}

@Composable
private fun MainPane(
    vm: BarrappViewModel,
    onPick: () -> Unit,
    onRecord: () -> Unit,
) {
    val state by vm.state.collectAsStateWithLifecycle()
    val analysis = state.analysis

    Box(Modifier.fillMaxSize()) {
        when {
            analysis != null -> {
                val clip = remember(state.current?.id) { vm.replayClip() }
                SessionDetail(
                    analysis = analysis,
                    onAdd = onPick,
                    onDelete = if (state.current != null) vm::deleteCurrent else null,
                    onReplay = clip?.let { { vm.openReplay() } },
                )
            }

            state.days.isEmpty() -> Column(Modifier.fillMaxSize()) {
                ObjectivesCard(
                    profile = state.profile,
                    goals = state.goals,
                    onSetup = vm::openObjectives,
                    onEditProfile = vm::openOnboarding,
                )
                EmptyState(
                    onAdd = onPick,
                    onSeeExample = vm::openExample,
                    modifier = Modifier.weight(1f),
                )
            }

            else -> Column(Modifier.fillMaxSize()) {
                ObjectivesCard(
                    profile = state.profile,
                    goals = state.goals,
                    onSetup = vm::openObjectives,
                    onEditProfile = vm::openOnboarding,
                )
                Box(Modifier.weight(1f).fillMaxSize()) {
                    Column(
                        Modifier.fillMaxSize(),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.Center,
                    ) {
                        Text(
                            "Pick a day to see it",
                            style = MaterialTheme.typography.titleMedium,
                        )
                        Spacer(Modifier.height(6.dp))
                        Text(
                            "Or add another clip.",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Spacer(Modifier.height(22.dp))
                        AddButton(onPick, large = true)
                        Spacer(Modifier.height(10.dp))
                        TextButton(onClick = onRecord) { Text("Record now instead") }
                    }
                }
            }
        }

        state.error?.let { message ->
            Box(
                Modifier
                    .align(Alignment.BottomCenter)
                    .padding(16.dp)
            ) {
                Panel {
                    Text(
                        message,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
        }
    }
}

/**
 * Who is training, and what for. Sits at the top of the initial screen, so the
 * objectives captured in the intake chat are on the screen where training
 * starts, and a profile onboarding never finished shows as unfinished instead
 * of silently missing.
 */
@Composable
private fun ObjectivesCard(
    profile: Profile,
    goals: Goals?,
    onSetup: () -> Unit,
    onEditProfile: () -> Unit,
) {
    Panel(Modifier.padding(horizontal = 20.dp, vertical = 10.dp)) {
        Eyebrow("Objectives")
        Spacer(Modifier.height(6.dp))
        val goal = goals?.goal.orEmpty()
        if (goal.isNotBlank()) {
            Text(goal, style = MaterialTheme.typography.bodyMedium)
        } else {
            Text(
                "No goal captured yet.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        goals?.focusExercise
            ?.takeIf { it.isNotBlank() && it != "unknown" }
            ?.let { focus ->
                Spacer(Modifier.height(4.dp))
                Text(
                    "Focus: ${focus.replace('_', ' ')}",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        Spacer(Modifier.height(10.dp))
        Pill(statusLine(profile))
        if (goal.isBlank() || !profile.complete) {
            Spacer(Modifier.height(4.dp))
            Row {
                if (goal.isBlank()) {
                    TextButton(onClick = onSetup) { Text("Set your goal in a chat") }
                }
                if (!profile.complete) {
                    TextButton(onClick = onEditProfile) { Text("Finish setup") }
                }
            }
        }
    }
}

private fun statusLine(profile: Profile): String {
    if (!profile.complete) return "profile unfinished"
    return listOfNotNull(
        profile.age.takeIf { it > 0 }?.toString(),
        profile.activity.label.takeIf { profile.activity != ActivityLevel.Unset },
        "aim ${profile.repTarget} reps",
    ).joinToString(" · ")
}

@Composable
private fun ShellHeader(name: String, onPrivacy: () -> Unit, onPlan: (() -> Unit)? = null) {
    Row(
        Modifier.fillMaxWidth().padding(start = 20.dp, end = 8.dp, top = 12.dp, bottom = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text("barrapp", style = MaterialTheme.typography.titleMedium)
            Text(
                greeting(name),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (onPlan != null) {
            TextButton(onClick = onPlan) { Text("Plan") }
        }
        TextButton(onClick = onPrivacy) {
            Icon(Icons.Filled.Info, contentDescription = "Privacy", Modifier.size(18.dp))
        }
    }
}

@Composable
private fun CompactBar(
    pane: Pane,
    showCalendar: Boolean,
    onSelect: (Pane) -> Unit,
    onAdd: () -> Unit,
) {
    NavigationBar(containerColor = MaterialTheme.colorScheme.surface) {
        if (showCalendar) {
            NavigationBarItem(
                selected = pane == Pane.Calendar,
                onClick = { onSelect(Pane.Calendar) },
                icon = { Icon(Icons.Filled.DateRange, contentDescription = null) },
                label = { Text("Calendar") },
            )
        }
        NavigationBarItem(
            selected = pane == Pane.Session,
            onClick = { onSelect(Pane.Session) },
            icon = { Icon(Icons.Filled.Home, contentDescription = null) },
            label = { Text("Session") },
        )
        NavigationBarItem(
            selected = false,
            onClick = onAdd,
            icon = { Icon(Icons.Filled.Add, contentDescription = null) },
            label = { Text("Add") },
        )
        NavigationBarItem(
            selected = pane == Pane.Progress,
            onClick = { onSelect(Pane.Progress) },
            icon = { Icon(Icons.Filled.Info, contentDescription = null) },
            label = { Text("Progress") },
        )
    }
}

private fun greeting(name: String): String {
    val hour = java.util.Calendar.getInstance().get(java.util.Calendar.HOUR_OF_DAY)
    val part = when (hour) {
        in 5..11 -> "Morning"
        in 12..17 -> "Afternoon"
        else -> "Evening"
    }
    return "$part, $name"
}

@Composable
private fun PrivacyScreen(
    onAccept: () -> Unit,
    showBack: Boolean,
    onBack: () -> Unit,
    onDiagnostics: () -> Unit,
) {
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
        Spacer(Modifier.height(14.dp))
        Text(
            "barrapp measures your own reps from a clip you send. It is not coaching and not " +
                "medical advice.",
            style = MaterialTheme.typography.bodyLarge,
        )
        Spacer(Modifier.height(20.dp))
        Section(
            "What we collect",
            "The video you upload and a random device id stored on this phone. Your name, age " +
                "and how often you train stay on the phone and are never sent anywhere.",
        )
        Section(
            "What we do with it",
            "The clip goes to our server, which runs pose estimation and returns numbers — " +
                "timing, range of motion, rep count. Clips are private to this device id and " +
                "are deleted automatically after 30 days. You can delete one from its session.",
        )
        Section(
            "What we do not do",
            "We do not sell data, run ads, or share clips. We do not diagnose injury or score " +
                "'good form'. Every number compares you against your own previous reps, never " +
                "against anyone else.",
        )
        Spacer(Modifier.height(28.dp))
        if (!showBack) {
            Button(onClick = onAccept, modifier = Modifier.fillMaxWidth()) {
                Text("I understand — continue")
            }
        } else {
            // Reached from the info button, which is also where someone goes
            // when something looks wrong. Diagnostics belongs behind it rather
            // than behind a hidden gesture nobody discovers.
            TextButton(onClick = onDiagnostics, modifier = Modifier.fillMaxWidth()) {
                Text("Diagnostics")
            }
        }
    }
}

@Composable
private fun Section(title: String, body: String) {
    Column(Modifier.padding(bottom = 18.dp)) {
        Eyebrow(title)
        Spacer(Modifier.height(6.dp))
        Text(body, style = MaterialTheme.typography.bodyMedium)
        Spacer(Modifier.height(10.dp))
        HorizontalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = 0.4f))
    }
}
