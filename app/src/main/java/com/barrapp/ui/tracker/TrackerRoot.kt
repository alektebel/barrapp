package com.barrapp.ui.tracker

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.barrapp.BarrappViewModel
import com.barrapp.Drill
import com.barrapp.FaultTrend
import com.barrapp.Gamification
import com.barrapp.Progression
import com.barrapp.UiState
import com.barrapp.cueEs
import com.barrapp.data.Analysis
import com.barrapp.data.DayEntry
import com.barrapp.data.WorkStore
import com.barrapp.drillEs
import com.barrapp.faultEs
import com.barrapp.movementEs
import com.barrapp.phaseEs
import com.barrapp.repFaultsEs
import com.barrapp.ui.CalDay
import com.barrapp.ui.CalKind
import com.barrapp.ui.CalRow
import com.barrapp.ui.CalendarScreen
import com.barrapp.ui.CheckLine
import com.barrapp.ui.CoachScreen
import com.barrapp.ui.CoachTurn
import com.barrapp.ui.LadderChipKind
import com.barrapp.ui.LadderDot
import com.barrapp.ui.LadderLine
import com.barrapp.ui.LadderScreen
import com.barrapp.ui.LadderStep
import com.barrapp.ui.RepCardData
import com.barrapp.ui.RepComponent
import com.barrapp.ui.SessionScreen
import com.barrapp.ui.VisionLine
import com.barrapp.ui.WorksSection
import com.barrapp.ui.parts.bandColor
import com.barrapp.ui.repChecks
import com.barrapp.ui.theme.Nocturne
import com.barrapp.ui.theme.Tk
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Locale

/** A page opened on top of a tab, not one of the four tabs itself. */
private enum class Sheet { NONE, SESSION, DAY, CALENDAR, LADDER, CHAT, SKILLS, HELP }

/**
 * The redesigned app, wired to the real view model.
 *
 * Four tabs, exactly the mockup's. The screens that survived the redesign —
 * the session detail, the month calendar, the ladder and the coach chat —
 * open on top of the tab that links to them and close back to it, so nothing
 * that was reachable before became unreachable.
 */
/** Cuántos vídeos caben en una selección. El sistema exige un tope; 10 sobra
 *  para una sesión y la cola los procesa de uno en uno. */
private const val MAX_CLIPS_PER_PICK = 10

@Composable
fun TrackerRoot(
    vm: BarrappViewModel = viewModel(),
    initialTab: TrackerTab = TrackerTab.HOME,
) {
    val state by vm.state.collectAsState()
    var tab by remember { mutableStateOf(initialTab) }
    var sheet by remember { mutableStateOf(Sheet.NONE) }
    // A session opened from a day's list goes back to that day, not Home.
    var sessionFromDay by remember { mutableStateOf(false) }
    val closeSheet = {
        if (sheet == Sheet.SESSION && sessionFromDay) sheet = Sheet.DAY else sheet = Sheet.NONE
        sessionFromDay = false
    }
    var repsOpen by remember { mutableStateOf(false) }
    val context = androidx.compose.ui.platform.LocalContext.current
    val declared = remember { com.barrapp.data.ProfileStore.declaration(context) }
    var standard by remember { mutableStateOf(declared.first) }
    var camera by remember { mutableStateOf(declared.second) }
    // Per clip, deliberately not saved like standard and camera: see IdlePhase.
    var exercise by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf("") }
    // The trace the record tab was looking at when the clip was sent. The
    // results phase waits for a DIFFERENT one, so a failed upload falls back
    // to the idle screen instead of re-presenting the previous session under
    // the heading "análisis".
    var sentFrom by remember { mutableStateOf<String?>(null) }
    var showResults by remember { mutableStateOf(false) }
    // The full-screen replay opens over whatever was showing and closes back
    // to it - the results, or the session sheet - rather than to Home.
    var replayOpen by remember { mutableStateOf(false) }
    // The fault viewer (Tiza 3b) opened from the results, at this fault.
    var faultAt by remember { mutableStateOf<Int?>(null) }
    // The rep correction (Tiza 2c), opened from the viewer's "ver la rep".
    var correctionAt by remember { mutableStateOf<Int?>(null) }

    // El selector del sistema, con varios vídeos: una sesión suele ser más
    // de un clip y todos entran a la vez en la cola. No pide permisos (el
    // usuario le da al sistema solo lo que elige) y ofrece la cámara.
    val pickVideo = rememberLauncherForActivityResult(
        ActivityResultContracts.PickMultipleVisualMedia(MAX_CLIPS_PER_PICK)
    ) { uris ->
        if (uris.isNotEmpty()) {
            sentFrom = state.analysis?.traceId.orEmpty()
            showResults = false
            tab = TrackerTab.RECORD
            vm.uploadMany(uris, standard, camera, exercise)
            exercise = ""
        }
    }
    val launchPicker = {
        pickVideo.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.VideoOnly))
    }
    // The mockup's record button and its "subir vídeo" both land here.
    // `CaptureVideo` needs an output uri this app does not manage yet, so the
    // system picker — which offers the camera itself — serves both paths, and
    // the button is honest about what it opens rather than promising an
    // in-app recorder that does not exist.
    val measuring = state.works.any { it.active }

    androidx.activity.compose.BackHandler(enabled = sheet != Sheet.NONE) { closeSheet() }
    androidx.activity.compose.BackHandler(
        enabled = sheet == Sheet.NONE && tab != TrackerTab.HOME
    ) { tab = TrackerTab.HOME }

    // A measurement that lands while the record tab is open should show its
    // result there rather than sit on "analizando" forever - but only if it is
    // this clip's measurement and not the one that was already on screen.
    LaunchedEffect(measuring, state.analysis) {
        val trace = state.analysis?.traceId
        if (!measuring && trace != null && sentFrom != null && trace != sentFrom) {
            showResults = true
        }
    }

    androidx.activity.compose.BackHandler(enabled = faultAt != null) { faultAt = null }
    androidx.activity.compose.BackHandler(enabled = correctionAt != null) { correctionAt = null }
    val analysis = state.analysis
    if (correctionAt != null && analysis != null) {
        val corrections = remember(analysis.traceId) { repCorrections(analysis) }
        val i = correctionAt!!
        val data = corrections.getOrNull(i)
        if (data != null) {
            RepCorrection(
                data = data,
                clip = remember(analysis.traceId, state.current?.id) { vm.replayClip() },
                onBack = { correctionAt = null },
                onNext = if (i + 1 < corrections.size) ({ correctionAt = i + 1 }) else null,
            )
            return
        }
        correctionAt = null
    }
    if (faultAt != null && analysis != null) {
        val slides = remember(analysis.traceId) {
            slidesInFixOrder(faultSlides(analysis), fixItems(analysis))
        }
        FaultViewer(
            faults = slides,
            startIndex = faultAt!!.coerceIn(0, (slides.size - 1).coerceAtLeast(0)),
            clip = remember(analysis.traceId, state.current?.id) { vm.replayClip() },
            onClose = { faultAt = null },
            // "Ver la rep": the correction for that rep, beside the best one.
            onPlayRep = { slide ->
                // The same fault first: two faults in one rep must not open
                // each other's correction.
                val all = repCorrections(analysis)
                val i = all.indexOfFirst { it.title.equals(slide.title, ignoreCase = true) }
                    .takeIf { it >= 0 } ?: all.indexOfFirst { it.rep == slide.rep }
                faultAt = null
                correctionAt = i.takeIf { it >= 0 } ?: 0
            },
            exercise = analysis.exercise,
        )
        return
    }

    if (replayOpen) {
        com.barrapp.ui.ReplayScreen(
            analysis = state.analysis,
            clip = remember(state.analysis?.traceId, state.current?.id) { vm.replayClip() },
            onBack = { replayOpen = false },
        )
        return
    }

    if (sheet != Sheet.NONE) {
        SheetHost(vm, state, sheet, repsOpen, { repsOpen = !repsOpen },
            onOpenSession = { sheet = Sheet.SESSION },
            onOpenDay = { sheet = Sheet.DAY },
            onOpenJob = { jobId ->
                vm.selectDate(state.selectedDate.orEmpty(), jobId)
                sessionFromDay = true
                sheet = Sheet.SESSION
            },
            onReplay = { replayOpen = true },
            backLabel = if (sessionFromDay) "← Día" else "← Semana") { closeSheet() }
        return
    }

    TrackerShell(tab, onHelp = { sheet = Sheet.HELP }, onTab = { target ->
        // The result of a finished clip stays on GRABAR until "Guardar
        // sesión". The session is already stored when the job finishes, so
        // tapping GRABAR means "another clip": back to the idle screen.
        if (target == TrackerTab.RECORD && showResults && !measuring) {
            showResults = false
            sentFrom = null
        }
        tab = target
    }) {
        Column(Modifier.fillMaxSize()) {
            // The queue stays visible under every tab: a failed upload's Retry
            // must never be behind a tab the athlete has no reason to open.
            if (state.works.isNotEmpty()) {
                WorksSection(
                    works = state.works,
                    onOpenLog = vm::openWorkLog,
                    onRetry = vm::retryWork,
                    onDismiss = vm::dismissWork,
                    modifier = Modifier.padding(horizontal = 16.dp),
                )
            }
            Box(Modifier.weight(1f)) {
                when (tab) {
                    TrackerTab.HOME -> TrackerHome(
                        data = homeData(state, state.jobs),
                        onOpenSession = {
                            state.days.firstOrNull { it.reps > 0 }?.let { vm.selectDate(it.date) }
                            sheet = Sheet.SESSION
                        },
                        onOpenCoach = { tab = TrackerTab.COACH },
                        onOpenCalendar = { sheet = Sheet.CALENDAR },
                        onOpenLadder = { sheet = Sheet.LADDER },
                        onRecord = { tab = TrackerTab.RECORD },
                        onOpenNew = {
                            state.days.firstOrNull { d -> d.jobIds.any { it in state.unseen } }
                                ?.let { vm.selectDay(it.date); sheet = Sheet.DAY }
                        },
                    )

                    TrackerTab.RECORD -> {
                        val (stages, active) = stagesFor(state)
                        TrackerRecord(
                            phase = when {
                                measuring -> RecordPhase.ANALYZING
                                showResults && state.analysis != null -> RecordPhase.RESULTS
                                else -> RecordPhase.IDLE
                            },
                            stages = stages,
                            activeStage = active,
                            results = state.analysis?.let {
                                resultsData(it, state.days, state.current?.id, state.current?.createdAt)
                            },
                            lastAnalyzed = lastAnalyzed(state.days),
                            standard = standard,
                            camera = camera,
                            exercise = exercise,
                            onExercise = { exercise = it },
                            onStandard = {
                                standard = it
                                com.barrapp.data.ProfileStore.saveDeclaration(context, standard, camera)
                            },
                            onCamera = {
                                camera = it
                                com.barrapp.data.ProfileStore.saveDeclaration(context, standard, camera)
                            },
                            onRecord = { launchPicker() },
                            onPick = { launchPicker() },
                            onDone = {
                                showResults = false
                                sentFrom = null
                                tab = TrackerTab.HOME
                            },
                            resultJobId = state.current?.takeIf {
                                it.result?.traceId == state.analysis?.traceId
                            }?.id,
                            resultTraceId = state.analysis?.traceId.orEmpty(),
                            currentResultTraceId = state.current?.result?.traceId,
                            onResultRendered = vm::markResultRendered,
                            replayAnalysis = state.analysis,
                            replayClip = remember(state.analysis?.traceId, state.current?.id) {
                                vm.replayClip()
                            },
                            onExpandReplay = { replayOpen = true },
                            onOpenFault = { faultAt = it },
                            onShare = state.analysis?.let { a -> { shareSet(context, a) } },
                            onBack = {
                                showResults = false
                                sentFrom = null
                            },
                        )
                    }

                    TrackerTab.PROGRESS -> TrackerProgress(
                        data = progressData(state, state.jobs).copy(path = skillPath(state)),
                        onOpenDay = { date -> vm.selectDate(date); sheet = Sheet.SESSION },
                        onOpenLadder = { sheet = Sheet.LADDER },
                        onOpenSkills = { sheet = Sheet.SKILLS },
                        onRecord = { tab = TrackerTab.RECORD },
                    )

                    TrackerTab.COACH -> TrackerCoach(
                        data = coachData(state).copy(
                            conversation = state.chat.map { CoachMessage(it.fromUser, it.text) },
                            thinking = state.coachThinking,
                            suggestions = vm.suggestions().take(3),
                        ),
                        onAskCoach = { sheet = Sheet.CHAT },
                        onSend = vm::ask,
                        onOpenProof = { proof ->
                            vm.selectDate(proof.sessionDate)
                            sheet = Sheet.SESSION
                        },
                        onRecord = { tab = TrackerTab.RECORD },
                    )
                }
            }
        }
    }
}

// ---- the sub-pages the tabs open ------------------------------------------

@Composable
private fun SheetHost(
    vm: BarrappViewModel,
    state: UiState,
    sheet: Sheet,
    repsOpen: Boolean,
    onToggleReps: () -> Unit,
    onOpenSession: () -> Unit,
    onOpenDay: () -> Unit,
    onOpenJob: (String) -> Unit,
    onReplay: () -> Unit,
    backLabel: String,
    onClose: () -> Unit,
) {
    Box(Modifier.fillMaxSize().background(Tk.bg)) {
        when (sheet) {
            Sheet.CHAT -> Box(Modifier.fillMaxSize().padding(16.dp)) {
                CoachScreen(
                    turns = state.chat.map { CoachTurn(it.fromUser, it.text, "") },
                    thinking = state.coachThinking,
                    suggestions = vm.suggestions().take(3),
                    onSend = vm::ask,
                    onBackToWeek = onClose,
                )
            }

            else -> Column(
                Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 16.dp, vertical = 12.dp),
            ) {
                when (sheet) {
                    Sheet.SESSION -> SessionSheet(vm, state, repsOpen, onToggleReps, onReplay, backLabel, onClose)
                    Sheet.CALENDAR -> CalendarSheet(vm, state, onOpenDay)
                    Sheet.DAY -> state.days.firstOrNull { it.date == state.selectedDate }?.let {
                        DaySheet(it, state.unseen, onOpenSession = onOpenJob, onClose = onClose)
                    }
                    Sheet.LADDER -> LadderSheet(state, onClose)
                    Sheet.SKILLS -> SkillsSheet(state, onClose)
                    Sheet.HELP -> HelpSheet(onClose)
                    else -> Unit
                }
            }
        }
    }
}

@Composable
private fun SessionSheet(
    vm: BarrappViewModel,
    state: UiState,
    repsOpen: Boolean,
    onToggleReps: () -> Unit,
    onReplay: () -> Unit,
    backLabel: String,
    onClose: () -> Unit,
) {
    val a = state.analysis
    if (a == null) {
        androidx.compose.material3.Text("Sin sesión seleccionada", style = com.barrapp.ui.theme.T.sectionTitle)
        androidx.compose.material3.Text(
            "Elige un día medido en el calendario, o filma una serie.",
            style = com.barrapp.ui.theme.T.bodyS,
            modifier = Modifier.padding(top = 6.dp),
        )
        TkSecondaryButton("Volver", onClose, modifier = Modifier.padding(top = 20.dp))
        return
    }
    val band = a.sessionBand
    val (l1, l2) = when (band) {
        "strong" -> "Serie fuerte." to "Mantén el estándar."
        "shaky" -> "Serie inestable." to "Se soltaron los básicos."
        "broken" -> "Se rompió." to "Empieza más pequeño."
        "unmeasured" -> "Sin medir." to "Barra no pudo puntuar esta serie."
        else -> "Serie sólida." to "Corrige el estancamiento."
    }
    SessionScreen(
        eyebrow = "${shortDate(a.sessionDate)} · ${movementEs(a.exercise)}",
        verdict = "$l1\n$l2",
        subtitle = "${a.repCount} reps en una serie de %.0f segundos.".format(
            (a.trim?.endS ?: 0.0) - (a.trim?.startS ?: 0.0)
        ) + if (a.repCount < 3) " Por debajo del mínimo de 3 reps: trátalo como una sola observación." else "",
        score = a.sessionScore,
        scoreBand = band,
        bandColor = bandColor(band),
        // Built from the measured fault counts, not from the English cue
        // sentences: those are prose, and looking them up in a table keyed on
        // fault names would silently leave the sheet in English.
        cues = com.barrapp.faultCounts(a).mapNotNull { (fault, _) -> cueEs(fault) }.take(3)
            .ifEmpty { listOf("Nada que señalar en las comprobaciones que se pudieron hacer.") },
        onWatchReplay = if (vm.replayClip() != null) onReplay else null,
        reps = a.reps.map { rep ->
            RepCardData(
                title = movementEs(rep.label, rep.label),
                chip = rep.band,
                chipColor = bandColor(rep.band),
                score = rep.score?.toString(),
                scoreColor = bandColor(rep.band),
                measured = rep.score != null,
                times = "%.1fs – %.1fs".format(rep.startS, rep.endS),
                trace = rep.trace,
                traceColor = bandColor(rep.band),
                components = rep.components.map {
                    RepComponent(it.label.ifBlank { it.name }, (it.weight * 100).toInt(), it.value?.toInt() ?: 0)
                },
                asides = rep.asides.map {
                    it.label.ifBlank { it.name }.replaceFirstChar { c -> c.uppercase() } to "%.2f torsos".format(it.value)
                },
                note = rep.scoreNote,
                checks = repChecks(rep),
                blocked = rep.assessmentBlocked,
            )
        },
        runLine = "run ${a.traceId} · build ${a.provenance?.commit ?: "?"}",
        onBackToWeek = onClose,
        backLabel = backLabel,
        repsOpen = repsOpen,
        onToggleReps = onToggleReps,
        standard = "",
        checks = a.checks.map {
            // A set nobody scored has no judged reps behind its tallies: all of
            // them are "no comprobable", never "limpio".
            if (a.unmeasuredSet)
                CheckLine(faultEs(it.name), 0, 0, it.observed + it.notObserved + it.unobservable)
            else CheckLine(faultEs(it.name), it.observed, it.notObserved, it.unobservable)
        },
        vision = a.visionObservations.map {
            VisionLine(it.rep, it.name.ifBlank { it.errorId }, it.status, it.description)
        },
        visionDisagrees = a.visionDisagreesOnMovement,
        renderedJobId = state.current?.takeIf { it.result?.traceId == a.traceId }?.id,
        renderedTraceId = a.traceId,
        onResultRendered = vm::markResultRendered,
    )
    // What to fix first, then the server's own account - which, on a clip
    // with nothing counted, is the only place the athlete learns why.
    val summary = resultsData(a, state.days, state.current?.id)
    androidx.compose.foundation.layout.Spacer(Modifier.padding(top = 16.dp))
    if (a.repCount > 0) {
        com.barrapp.ui.tracker.FixesCard(summary.fixes, unjudged = summary.unjudged)
        androidx.compose.foundation.layout.Spacer(Modifier.padding(top = 12.dp))
    }
    if (a.headline.isNotBlank() || a.narrative.isNotBlank() || a.blockers.isNotEmpty()) {
        com.barrapp.ui.tracker.WhatHappened(summary)
    }
}

@Composable
private fun CalendarSheet(vm: BarrappViewModel, state: UiState, onOpenDay: () -> Unit) {
    var offset by remember { mutableStateOf(0) }
    val cal = Calendar.getInstance().apply { add(Calendar.MONTH, offset) }
    val month = cal.getDisplayName(Calendar.MONTH, Calendar.LONG, Locale.forLanguageTag("es")) ?: ""
    val byDate = state.days.associateBy { it.date }
    val daysInMonth = cal.getActualMaximum(Calendar.DAY_OF_MONTH)
    val today = if (offset == 0) cal.get(Calendar.DAY_OF_MONTH) else -1
    // Rows and totals belong to the month on screen: a row's day number is
    // resolved against this month, so a row from another month would open
    // the wrong day.
    val prefix = "%04d-%02d-".format(cal.get(Calendar.YEAR), cal.get(Calendar.MONTH) + 1)
    val inMonth = state.days.filter { it.date.startsWith(prefix) }
    val firstDow = ((cal.clone() as Calendar)
        .apply { set(Calendar.DAY_OF_MONTH, 1) }
        .get(Calendar.DAY_OF_WEEK) + 5) % 7
    val cells = (1..daysInMonth).map { d ->
        val key = "%04d-%02d-%02d".format(cal.get(Calendar.YEAR), cal.get(Calendar.MONTH) + 1, d)
        val day = byDate[key]
        val blanks = if (d == 1) firstDow else 0
        when {
            day != null && day.verifiedReps > 0 ->
                CalDay(d, if (d == today) CalKind.TODAY else CalKind.MEASURED,
                    bandColor(day.band), leadingBlanks = blanks)
            day != null -> CalDay(d, CalKind.DASHED, leadingBlanks = blanks)
            else -> CalDay(d, CalKind.PLAIN, leadingBlanks = blanks)
        }
    }
    CalendarScreen(
        month = month.replaceFirstChar { it.uppercase() },
        year = "${cal.get(Calendar.YEAR)}",
        days = cells,
        summaryMeasured = "${inMonth.count { it.verifiedReps > 0 }} días medidos",
        summaryReps = "${inMonth.sumOf { it.verifiedReps }} reps medidas en $month",
        rows = inMonth.sortedByDescending { it.date }.map { day ->
            CalRow(
                title = movementEs(day.exercise, day.exerciseLabel),
                subtitle = "${day.reps} reps · ${shortDate(day.date)}",
                score = day.score?.toString() ?: "—",
                color = bandColor(day.band),
                scoreColor = if (day.score != null) bandColor(day.band) else Nocturne.fgA(0.4f),
                clickable = true,
                day = day.date.takeLast(2).toIntOrNull() ?: 1,
            )
        },
        onPrevMonth = { offset-- },
        onNextMonth = { offset++ },
        onOpenDay = { n ->
            val key = "%04d-%02d-%02d".format(
                cal.get(Calendar.YEAR), cal.get(Calendar.MONTH) + 1, n)
            byDate[key]?.let { vm.selectDay(it.date); onOpenDay() }
        },
    )
}

/** The path to the athlete's goal skill (docs/UX-PLAN.md B3). */
@Composable
private fun SkillsSheet(state: UiState, onClose: () -> Unit) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val graph = remember { com.barrapp.data.SkillGraph.load(context) }
    val goal = state.goals?.focusExercise?.takeIf { graph[it] != null }
    var target by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf(goal ?: "muscle_up") }
    val verified = remember(state.days) { graph.verifiedFrom(state.days) }
    val data = remember(target, verified) { skillPathData(graph, target, verified, goal) }
    if (data != null) SkillPathScreen(data, onTarget = { target = it }, onClose = onClose)
}

@Composable
private fun LadderSheet(state: UiState, onClose: () -> Unit) {
    val verdicts = Progression.verdicts(state.days, state.goals?.focusExercise)
    val steps = verdicts.mapNotNull { v ->
        val step = v.step ?: return@mapNotNull null
        val earned = v.qualifyingDays.size >= step.days
        val label = movementEs(v.movement, v.label)
        when {
            earned -> LadderStep(label, LadderChipKind.EARNED,
                lines = listOf(LadderLine("", v.evidence)), dot = LadderDot.EARNED)
            v.ready -> LadderStep(label, LadderChipKind.READY,
                lines = listOf(LadderLine("", "Estándar superado. Filma una serie y empieza a contar.")),
                dot = LadderDot.EARNED, borderColor = Nocturne.accentDeep)
            else -> LadderStep(label, null,
                count = "${v.qualifyingDays.size} / ${step.days}",
                progress = if (step.days > 0) v.qualifyingDays.size.toFloat() / step.days else 0f,
                lines = listOf(
                    LadderLine("El estándar", v.standard),
                    LadderLine("Tu evidencia", v.evidence),
                    LadderLine("", v.missing, accent = true),
                ),
                dot = LadderDot.CURRENT, big = true, borderColor = Nocturne.accentDeep)
        }
    }
    LadderScreen(steps)
    TkSecondaryButton("Volver", onClose, modifier = Modifier.padding(top = 20.dp))
}

// ---- the derivations the tabs read ----------------------------------------

private fun homeData(state: UiState, jobs: List<com.barrapp.data.Job>): HomeData {
    val days = state.days
    val standing = Gamification.standing(days)
    val focus = state.goals?.focusExercise
    val focusCue = state.analysis
        ?.let { a -> com.barrapp.faultCounts(a).firstOrNull()?.first }
        ?.let { cueEs(it) }
        ?: "mantener el estándar en cada repetición"
    val last = days.firstOrNull { it.reps > 0 }
    return HomeData(
        name = state.profile.firstName,
        standing = standing,
        week = Gamification.week(days),
        mission = Gamification.mission(days, state.profile, focus, focusCue)
            .let { m -> m.copy(movement = movementEs(m.movementKey, m.movement)) },
        lastSession = last?.let { day ->
            // The last clip, not the day: a day can hold several movements
            // and unscored sets, and their sum describes none of them.
            val job = day.last
            val reps = job?.reps ?: day.reps
            val score = if (job != null) job.score else day.score
            val judged = job?.verified ?: day.verifiedReps
            val movement = movementEs(job?.exercise ?: day.exercise, job?.label ?: day.exerciseLabel)
            LastSessionData(
                movement = movement,
                date = shortDate(day.date),
                reps = reps,
                score = score,
                judged = judged,
                rows = if (job != null) listOf(SessionRowData(movement, score, reps))
                else day.byMovement.values
                    .sortedByDescending { it.reps }
                    .map { SessionRowData(movementEs(it.exercise, it.label), it.score, it.reps) }
                    .ifEmpty { listOf(SessionRowData(movement, score, reps)) },
                // The ledger is per day: only attribute it to a day of one clip.
                topFault = state.faults[day.date]
                    ?.takeIf { job == null || day.jobIds.size <= 1 }
                    ?.maxByOrNull { it.value }
                    ?.let { faultEs(it.key) to it.value },
                // The last clip's own reps, when its measurement is on the
                // phone; otherwise the card falls back to the set's score.
                repScores = job?.let { j ->
                    (jobs.firstOrNull { it.id == j.jobId }?.result
                        ?: state.analysis?.takeIf { state.current?.id == j.jobId })
                        ?.reps?.map { it.score }
                }.orEmpty(),
                sets = day.jobIds.size.coerceAtLeast(1),
            )
        },
        badges = Gamification.badges(days, focus),
        nextGoal = Progression.verdicts(days, focus).firstNotNullOfOrNull { v ->
            val step = v.step ?: return@firstNotNullOfOrNull null
            if (v.qualifyingDays.size >= step.days) null
            else NextGoalData(
                label = movementEs(v.movement, v.label) + " · " + v.standard,
                done = v.qualifyingDays.size,
                target = step.days,
            )
        },
        newResults = state.unseen.size,
        weekTarget = when (state.profile.activity) {
            com.barrapp.data.ActivityLevel.New, com.barrapp.data.ActivityLevel.Occasional -> 2
            com.barrapp.data.ActivityLevel.Regular -> 4
            com.barrapp.data.ActivityLevel.Daily -> 5
            com.barrapp.data.ActivityLevel.Unset -> 0
        },
    )
}

private fun stagesFor(state: UiState): Pair<List<String>, Int> {
    val stages = listOf(
        "Enviando el clip",
        "Reconociendo el movimiento",
        "Recortando la serie",
        "Contando y midiendo reps",
    )
    val active = state.works.firstOrNull { it.active }
    val idx = when (active?.status) {
        // Still on the phone (being prepared or waiting to go) is the first
        // stage too: showing "recortando la serie" above "esperando para
        // enviarse" contradicted the queue card on the same screen.
        WorkStore.STATUS_PENDING, WorkStore.STATUS_WAITING,
        WorkStore.STATUS_SENDING, WorkStore.STATUS_CONNECTING -> 0
        WorkStore.STATUS_QUEUED -> 1
        WorkStore.STATUS_MEASURING ->
            com.barrapp.data.Stage.progressIndex(active.stageCode, active.stage)
        else -> 2
    }
    return stages to idx
}

private fun resultsData(
    a: Analysis,
    days: List<DayEntry>,
    jobId: String? = null,
    createdAt: String? = null,
): ResultsData {
    val verifiedXp = a.reps.count { it.score != null && it.complete }
    return ResultsData(
        headline = a.headline,
        narrative = a.narrative,
        blockers = a.blockers + a.notes,
        nextSession = a.nextSession,
        fixes = fixItems(a),
        movement = movementEs(a.exercise, a.detected?.label.orEmpty()),
        setsLabel = "1 serie",
        reps = a.repCount,
        score = a.sessionScore,
        faults = com.barrapp.faultCounts(a).map { (k, n) -> faultEs(k) to n },
        repCards = a.reps.mapIndexed { i, rep ->
            RepCardItem(
                label = "Rep ${i + 1}",
                score = rep.score,
                faults = repFaultsEs(rep),
                times = "%.1f–%.1fs".format(rep.startS, rep.endS),
                blocked = rep.assessmentBlocked?.let {
                    "Sin juzgar: ${it.replaceFirstChar { c -> c.lowercase() }}"
                },
            )
        },
        // The XP this session actually earned, by the same rule the home
        // screen totals: never a round number picked to look generous.
        xp = if (verifiedXp == 0) 0 else verifiedXp * ((a.sessionScore ?: 0) / 5) + 50,
        unjudged = unjudgedNote(a),
        aboveAverage = ResultComparison.aboveAverage(a, days, jobId),
        vsAverage = ResultComparison.vsAverage(a, days, jobId),
        seriesLabel = days.firstOrNull { jobId != null && jobId in it.jobIds }
            ?.let { "Serie ${it.jobIds.indexOf(jobId) + 1}" }.orEmpty(),
        whenLabel = createdAt?.let { whenEs(it) }.orEmpty(),
    )
}

private fun lastAnalyzed(days: List<DayEntry>): LastAnalyzed? =
    days.firstOrNull { it.reps > 0 }?.let { day ->
        val job = day.last
        val reps = job?.reps ?: day.reps
        val score = if (job != null) job.score else day.score
        LastAnalyzed(
            movement = movementEs(job?.exercise ?: day.exercise, job?.label ?: day.exerciseLabel),
            meta = "${shortDate(day.date)} · $reps reps" + if (score == null) " · sin puntuar" else "",
            score = score,
        )
    }

private fun progressData(state: UiState, jobs: List<com.barrapp.data.Job>): ProgressData {
    val measured = state.days.filter { it.score != null }.sortedBy { it.date }
    val half = measured.size / 2
    val recentMean = measured.drop(half).mapNotNull { it.score }
        .takeIf { it.isNotEmpty() }?.average()?.toInt()
    val earlierMean = measured.take(half).mapNotNull { it.score }
        .takeIf { it.isNotEmpty() }?.average()?.toInt()
    val month = monthPrefix()
    val best = measured.maxByOrNull { it.score ?: 0 }

    return ProgressData(
        averageScore = recentMean,
        averageDelta = if (recentMean != null && earlierMean != null) recentMean - earlierMean
                       else null,
        repsThisMonth = state.days.filter { it.date.startsWith(month) }.sumOf { it.verifiedReps },
        bestScore = best?.score,
        bestScoreDate = best?.date?.let { shortDate(it) }.orEmpty(),
        trend = measured.takeLast(20).map { TrendPoint(shortDate(it.date), it.score ?: 0) },
        // Per movement, from scored reps only.
        bests = Progression.records(state.days).take(3).flatMap { r ->
            listOfNotNull(
                r.bestScore?.let {
                    PersonalBest(movementEs(r.movement, r.label), "Mejor día",
                        "$it", "pts", shortDate(r.bestScoreDate))
                },
                r.mostReps.takeIf { it > 0 }?.let {
                    PersonalBest(movementEs(r.movement, r.label), "Más reps en un día",
                        "$it", "reps", shortDate(r.mostRepsDate))
                },
            )
        },
        faults = FaultTrend.rows(state.faults).take(5),
        movements = movementSeries(state, jobs),
        history = state.days.sortedByDescending { it.date }.take(8).map { day ->
            HistoryRow(
                date = day.date,
                dateLabel = shortDate(day.date),
                movement = movementEs(day.exercise, day.exerciseLabel),
                reps = day.reps,
                clips = day.jobIds.size.coerceAtLeast(1),
                score = day.score,
            )
        },
    )
}

private fun coachData(state: UiState): CoachData {
    val analyses = (listOfNotNull(state.analysis) +
        state.jobs.sortedByDescending { it.createdAt }.mapNotNull { it.result })
    val basis = CoachBasisPicker.pick(state.days, analyses)
    val unscoredNotice = basis.unscoredLast?.let {
        "Tu última sesión (${movementEs(it.exercise, it.label)}, ${it.reps} " +
            (if (it.reps == 1) "rep" else "reps") + ") no se pudo puntuar: no cuenta " +
            "como buena ni como mala."
    }
    val day = basis.scoredDay
    val key = basis.scoredKey
    if (day == null || key == null) {
        return CoachData(
            movement = "", sessions = 0, focus = null, secondary = null, rules = emptyList(),
            drills = emptyList(), totalMinutes = 0, notice = unscoredNotice,
        )
    }
    val movement = movementEs(key, day.byMovement[key]?.label.orEmpty())
    val label = "$movement · ${shortDate(day.date)}"
    // The ledger is per day, not per movement: keep only the days where this
    // movement was actually scored.
    val scoredDates = state.days.filter { (it.byMovement[key]?.verified ?: 0) > 0 }.map { it.date }.toSet()
    val rows = FaultTrend.rows(state.faults.filterKeys { it in scoredDates })
    val sessions = scoredDates.size
    fun focusOf(row: FaultTrend.Row?) = row?.let {
        CoachFocus(
            fault = faultEs(it.fault),
            cue = cueEs(it.fault) ?: "Sigue filmando: hace falta más evidencia sobre esto.",
            drill = drillEs(it.fault),
            repsAffected = it.count,
            improvementPct = it.improvementPct,
            improving = it.improving,
        )
    }
    val drills: List<Drill> = rows.take(3).mapNotNull { drillEs(it.fault) }.distinctBy { it.title }
    return CoachData(
        movement = movement,
        sessions = sessions,
        focus = focusOf(rows.firstOrNull()),
        secondary = focusOf(rows.getOrNull(1)),
        rules = basis.rulesFrom?.let { rules(it, state.faults.filterKeys { d -> d in scoredDates }) }
            ?: emptyList(),
        drills = drills,
        totalMinutes = drills.sumOf { d -> d.duration.filter { it.isDigit() }.toIntOrNull() ?: 0 },
        notice = unscoredNotice,
        basisLabel = if (unscoredNotice != null) "De tu última sesión puntuada: $label"
                     else null,
        rulesLabel = label,
    )
}

/**
 * The technique rules, taken from the checks the pipeline actually ran on the
 * given scored set. A check that could not be made says so — it is never
 * rendered as a pass.
 */
private fun rules(a: Analysis, faults: Map<String, Map<String, Int>>): List<CoachRule> {
    val ledger = FaultTrend.rows(faults).associateBy { it.fault }
    return a.checks.take(6).map { check ->
        val trend = ledger[check.name]
        val (verdict, ink) = when {
            check.observed > 0 && trend?.improving == true -> "Progresando" to Tk.teal
            check.observed > 0 -> "Corregir" to Tk.amber
            check.notObserved > 0 -> "Correcto" to Tk.primaryLight
            else -> "Sin juzgar" to Tk.muted
        }
        CoachRule(
            id = check.errorId.ifBlank { check.name },
            title = faultEs(check.name),
            phase = phaseEs(check.phase),
            verdict = verdict,
            verdictInk = ink,
            description = when {
                check.observed > 0 ->
                    "Se detectó en ${check.observed} de ${check.observed + check.notObserved} " +
                        "reps juzgadas en esa serie."
                check.notObserved > 0 ->
                    "Comprobado en ${check.notObserved} reps y limpio en todas ellas."
                else ->
                    "No se pudo comprobar en esa serie — ${check.unobservable} reps sin " +
                        "evidencia suficiente: el ángulo de cámara no lo deja ver, o depende de una " +
                        "variante del ejercicio que el vídeo no aclara."
            },
            cue = cueEs(check.name).orEmpty(),
        )
    }
}

// ---- small shared helpers -------------------------------------------------

/** The viewer's slides in the order the results list the fixes, so the
 *  thumbnail i and "REVISAR FALLOS" open the fault they name. Slides with no
 *  matching fix keep their own order after those. */
internal fun slidesInFixOrder(slides: List<FaultSlide>, fixes: List<FixItem>): List<FaultSlide> {
    val ordered = fixes.mapNotNull { fix ->
        slides.firstOrNull { it.title.equals(fix.title, ignoreCase = true) }
            ?: fix.repIndex?.let { r -> slides.firstOrNull { it.rep == r + 1 } }
    }.distinct()
    return ordered + slides.filter { it !in ordered }
}

/** One chart per trained movement (Tiza 2d), from the days the phone holds. */
private fun movementSeries(state: UiState, jobs: List<com.barrapp.data.Job>): List<MovementSeries> {
    val keys = state.days.flatMap { it.byMovement.keys }.distinct()
    return keys.mapNotNull { key ->
        val days = state.days.filter { (it.byMovement[key]?.reps ?: 0) > 0 }.sortedBy { it.date }
        if (days.isEmpty()) return@mapNotNull null
        val sessions = days.map { d ->
            val m = d.byMovement.getValue(key)
            SessionPoint(
                date = d.date, dateLabel = shortDate(d.date), score = m.score, reps = m.verified,
                note = state.faults[d.date]?.maxByOrNull { it.value }?.key?.let { faultEs(it) }.orEmpty(),
            )
        }
        val scores = sessions.mapNotNull { it.score }
        val half = scores.size / 2
        val label = days.last().byMovement.getValue(key).label
        MovementSeries(
            id = key,
            label = movementEs(key, label),
            sessions = sessions,
            average = scores.takeIf { it.isNotEmpty() }?.average()?.toInt(),
            delta = if (scores.size >= 2)
                scores.drop(half).average().toInt() - scores.take(half.coerceAtLeast(1)).average().toInt()
            else null,
            maxCleanReps = days.maxOf { it.byMovement.getValue(key).verified }.takeIf { it > 0 },
            bestRep = jobs.filter { it.exercise == key || it.result?.exercise == key }
                .flatMap { it.result?.reps.orEmpty() }
                .mapNotNull { it.score }.maxOrNull(),
        )
    }
}

/** The skill path as the vertical steps the progress page draws. */
@Composable
private fun skillPath(state: UiState): List<PathStep> {
    val context = androidx.compose.ui.platform.LocalContext.current
    val graph = remember { com.barrapp.data.SkillGraph.load(context) }
    val goal = state.goals?.focusExercise?.takeIf { graph[it] != null }
    return remember(state.days, goal) {
        val verified = graph.verifiedFrom(state.days)
        skillPathData(graph, goal ?: "muscle_up", verified, goal)
            ?.let { pathSteps(it, missingForNext(graph, it.next, state.days)) }
            .orEmpty()
    }
}

/** "Hoy 18:42", "Ayer 18:42" or "8 sept 18:42" from an ISO timestamp. */
internal fun whenEs(iso: String, today: java.time.LocalDate = java.time.LocalDate.now()): String {
    val t = runCatching {
        java.time.OffsetDateTime.parse(iso).atZoneSameInstant(java.time.ZoneId.systemDefault())
            .toLocalDateTime()
    }.recoverCatching { java.time.LocalDateTime.parse(iso.take(19)) }.getOrNull() ?: return ""
    val hm = "%02d:%02d".format(t.hour, t.minute)
    return when (t.toLocalDate()) {
        today -> "Hoy $hm"
        today.minusDays(1) -> "Ayer $hm"
        else -> "${shortDate(t.toLocalDate().toString())} $hm"
    }
}

/** Share the set as plain text: movement, reps, score and what to fix. */
private fun shareSet(context: android.content.Context, a: Analysis) {
    val score = a.sessionScore?.let { "nota $it (${com.barrapp.ui.theme.scoreLabel(it).lowercase()})" } ?: "sin nota"
    val fixes = fixItems(a).take(3).joinToString("\n") { "· " + it.title }
    val text = "${movementEs(a.exercise, a.detected?.label.orEmpty())} · ${a.repCount} reps · $score" +
        (if (fixes.isNotBlank()) "\nLo que mejorar:\n$fixes" else "") + "\n— medido con BarrApp"
    val send = android.content.Intent(android.content.Intent.ACTION_SEND)
        .setType("text/plain")
        .putExtra(android.content.Intent.EXTRA_TEXT, text)
    context.startActivity(android.content.Intent.createChooser(send, "Compartir serie"))
}

/** "?" in the tab bar: how to film a set the app can measure. Each line is a
 *  reason the pipeline refuses or cannot score a clip. */
@Composable
private fun HelpSheet(onClose: () -> Unit) {
    androidx.compose.material3.Text("CÓMO FILMAR", style = com.barrapp.ui.theme.T.pageTitle)
    androidx.compose.material3.Text(
        "Así la app puede contar y medir cada repetición.",
        style = com.barrapp.ui.theme.T.lead,
        modifier = Modifier.padding(top = 6.dp, bottom = 12.dp),
    )
    listOf(
        "De lado" to "Pon el teléfono a la altura de la cadera, perpendicular a ti. De frente no se ve la profundidad ni el bloqueo.",
        "Todo el cuerpo y la barra" to "Desde las manos hasta los pies, y el aparato, dentro del plano durante toda la serie.",
        "Teléfono quieto" to "Apóyalo o usa un trípode. Si se mueve, la medida se pierde.",
        "Una sola persona" to "Si entra alguien más en el plano, la app puede seguir a la persona equivocada.",
        "Sólo la serie" to "Empieza a grabar justo antes y para al acabar. Un vídeo de varios minutos se rechaza.",
        "Buena luz" to "A contraluz o de noche el cuerpo no se distingue del fondo.",
    ).forEach { (title, body) ->
        TkCard(modifier = Modifier.padding(bottom = 10.dp)) {
            androidx.compose.material3.Text(title.uppercase(), style = com.barrapp.ui.theme.T.rowTitle)
            androidx.compose.material3.Text(body, style = com.barrapp.ui.theme.T.bodyInk,
                modifier = Modifier.padding(top = 4.dp))
        }
    }
    TkSecondaryButton("Volver", onClose, modifier = Modifier.padding(top = 10.dp))
}

private fun monthPrefix(): String {
    val c = Calendar.getInstance()
    return "%04d-%02d".format(c.get(Calendar.YEAR), c.get(Calendar.MONTH) + 1)
}

private fun shortDate(iso: String): String = com.barrapp.shortDateEs(iso)
