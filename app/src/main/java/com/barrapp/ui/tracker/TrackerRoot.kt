package com.barrapp.ui.tracker

import androidx.activity.compose.rememberLauncherForActivityResult
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
private enum class Sheet { NONE, SESSION, CALENDAR, LADDER, CHAT }

/**
 * The redesigned app, wired to the real view model.
 *
 * Four tabs, exactly the mockup's. The screens that survived the redesign —
 * the session detail, the month calendar, the ladder and the coach chat —
 * open on top of the tab that links to them and close back to it, so nothing
 * that was reachable before became unreachable.
 */
@Composable
fun TrackerRoot(
    vm: BarrappViewModel = viewModel(),
    initialTab: TrackerTab = TrackerTab.HOME,
) {
    val state by vm.state.collectAsState()
    var tab by remember { mutableStateOf(initialTab) }
    var sheet by remember { mutableStateOf(Sheet.NONE) }
    var repsOpen by remember { mutableStateOf(false) }
    var standard by remember { mutableStateOf("") }
    var camera by remember { mutableStateOf("") }
    // The trace the record tab was looking at when the clip was sent. The
    // results phase waits for a DIFFERENT one, so a failed upload falls back
    // to the idle screen instead of re-presenting the previous session under
    // the heading "análisis".
    var sentFrom by remember { mutableStateOf<String?>(null) }
    var showResults by remember { mutableStateOf(false) }

    val pickVideo = rememberLauncherForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri ->
        if (uri != null) {
            sentFrom = state.analysis?.traceId.orEmpty()
            showResults = false
            tab = TrackerTab.RECORD
            vm.upload(uri, standard, camera)
        }
    }
    // The mockup's record button and its "subir vídeo" both land here.
    // `CaptureVideo` needs an output uri this app does not manage yet, so the
    // system picker — which offers the camera itself — serves both paths, and
    // the button is honest about what it opens rather than promising an
    // in-app recorder that does not exist.
    val measuring = state.works.any { it.active }

    androidx.activity.compose.BackHandler(enabled = sheet != Sheet.NONE) { sheet = Sheet.NONE }
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

    if (sheet != Sheet.NONE) {
        SheetHost(vm, state, sheet, repsOpen, { repsOpen = !repsOpen }) { sheet = Sheet.NONE }
        return
    }

    TrackerShell(tab, { tab = it }) {
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
                        data = homeData(state),
                        onOpenSession = {
                            state.days.firstOrNull { it.reps > 0 }?.let { vm.selectDate(it.date) }
                            sheet = Sheet.SESSION
                        },
                        onOpenCoach = { tab = TrackerTab.COACH },
                        onOpenCalendar = { sheet = Sheet.CALENDAR },
                        onOpenLadder = { sheet = Sheet.LADDER },
                        onRecord = { tab = TrackerTab.RECORD },
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
                            results = state.analysis?.let { resultsData(it, state.days) },
                            lastAnalyzed = lastAnalyzed(state.days),
                            standard = standard,
                            camera = camera,
                            onStandard = { standard = it },
                            onCamera = { camera = it },
                            onRecord = { pickVideo.launch("video/*") },
                            onPick = { pickVideo.launch("video/*") },
                            onDone = {
                                showResults = false
                                sentFrom = null
                                tab = TrackerTab.HOME
                            },
                        )
                    }

                    TrackerTab.PROGRESS -> TrackerProgress(
                        data = progressData(state),
                        onOpenDay = { date -> vm.selectDate(date); sheet = Sheet.SESSION },
                        onOpenLadder = { sheet = Sheet.LADDER },
                        onRecord = { tab = TrackerTab.RECORD },
                    )

                    TrackerTab.COACH -> TrackerCoach(
                        data = coachData(state),
                        onAskCoach = { sheet = Sheet.CHAT },
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
                    Sheet.SESSION -> SessionSheet(vm, state, repsOpen, onToggleReps, onClose)
                    Sheet.CALENDAR -> CalendarSheet(vm, state, onClose)
                    Sheet.LADDER -> LadderSheet(state, onClose)
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
        onWatchReplay = state.current?.let { { vm.openReplay() } },
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
                    RepComponent(it.name, (it.weight * 100).toInt(), it.value?.toInt() ?: 0)
                },
                asides = rep.asides.map {
                    it.name.replaceFirstChar { c -> c.uppercase() } to "%.2f torso".format(it.value)
                },
                note = rep.scoreNote,
                checks = repChecks(rep),
                blocked = rep.assessmentBlocked,
            )
        },
        runLine = "run ${a.traceId} · build ${a.provenance?.commit ?: "?"}",
        onBackToWeek = onClose,
        repsOpen = repsOpen,
        onToggleReps = onToggleReps,
        standard = "",
        checks = a.checks.map {
            CheckLine(faultEs(it.name), it.observed, it.notObserved, it.unobservable)
        },
        vision = a.visionObservations.map {
            VisionLine(it.rep, it.name.ifBlank { it.errorId }, it.status, it.description)
        },
        visionDisagrees = a.visionDisagreesOnMovement,
    )
}

@Composable
private fun CalendarSheet(vm: BarrappViewModel, state: UiState, onClose: () -> Unit) {
    var offset by remember { mutableStateOf(0) }
    val cal = Calendar.getInstance().apply { add(Calendar.MONTH, offset) }
    val month = cal.getDisplayName(Calendar.MONTH, Calendar.LONG, Locale.forLanguageTag("es")) ?: ""
    val byDate = state.days.associateBy { it.date }
    val daysInMonth = cal.getActualMaximum(Calendar.DAY_OF_MONTH)
    val today = if (offset == 0) cal.get(Calendar.DAY_OF_MONTH) else -1
    val firstDow = ((cal.clone() as Calendar)
        .apply { set(Calendar.DAY_OF_MONTH, 1) }
        .get(Calendar.DAY_OF_WEEK) + 5) % 7
    val cells = (1..daysInMonth).map { d ->
        val key = "%04d-%02d-%02d".format(cal.get(Calendar.YEAR), cal.get(Calendar.MONTH) + 1, d)
        val day = byDate[key]
        val blanks = if (d == 1) firstDow else 0
        when {
            day != null && day.reps > 0 ->
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
        summaryMeasured = "${state.days.count { it.reps > 0 }} días medidos",
        summaryReps = "${state.days.sumOf { it.reps }} reps en total",
        rows = state.days.sortedByDescending { it.date }.take(3).map { day ->
            CalRow(
                title = movementEs(day.exercise, day.exerciseLabel),
                subtitle = "${day.reps} reps · ${shortDate(day.date)}",
                score = day.score?.toString() ?: "—",
                color = bandColor(day.band),
                scoreColor = if (day.score != null) bandColor(day.band) else Nocturne.fgA(0.4f),
                clickable = day.reps > 0,
                day = day.date.takeLast(2).toIntOrNull() ?: 1,
            )
        },
        onPrevMonth = { offset-- },
        onNextMonth = { offset++ },
        onOpenDay = { n ->
            val key = "%04d-%02d-%02d".format(
                cal.get(Calendar.YEAR), cal.get(Calendar.MONTH) + 1, n)
            byDate[key]?.let { vm.selectDate(it.date); onClose() }
        },
    )
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

private fun homeData(state: UiState): HomeData {
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
            LastSessionData(
                movement = movementEs(day.exercise, day.exerciseLabel),
                date = shortDate(day.date),
                reps = day.reps,
                score = day.score,
                rows = day.byMovement.values
                    .sortedByDescending { it.reps }
                    .map { SessionRowData(movementEs(it.exercise, it.label), it.score, it.reps) }
                    .ifEmpty {
                        listOf(SessionRowData(
                            movementEs(day.exercise, day.exerciseLabel), day.score, day.reps))
                    },
                topFault = state.faults[day.date]
                    ?.maxByOrNull { it.value }
                    ?.let { faultEs(it.key) to it.value },
            )
        },
        badges = Gamification.badges(days, focus),
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
        WorkStore.STATUS_SENDING, WorkStore.STATUS_CONNECTING -> 0
        WorkStore.STATUS_QUEUED -> 1
        WorkStore.STATUS_MEASURING -> when {
            active.stage.contains("recognising", true) -> 1
            active.stage.contains("pose", true) -> 1
            active.stage.contains("finding", true) ||
                active.stage.contains("scoring", true) -> 3
            else -> 2
        }
        else -> 2
    }
    return stages to idx
}

private fun resultsData(a: Analysis, days: List<DayEntry>): ResultsData {
    val priorScores = days.filter { it.date != a.sessionDate }.mapNotNull { it.score }
    val priorMean = priorScores.takeIf { it.isNotEmpty() }?.average()
    val verifiedXp = a.reps.count { it.score != null && it.complete }
    return ResultsData(
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
        xp = verifiedXp * ((a.sessionScore ?: 0) / 5) + 50,
        aboveAverage = priorMean?.let { (a.sessionScore ?: 0) >= it },
    )
}

private fun lastAnalyzed(days: List<DayEntry>): LastAnalyzed? =
    days.firstOrNull { it.reps > 0 }?.let { day ->
        LastAnalyzed(
            movement = movementEs(day.exercise, day.exerciseLabel),
            meta = "${shortDate(day.date)} · ${day.reps} reps",
            score = day.score,
        )
    }

private fun progressData(state: UiState): ProgressData {
    val measured = state.days.filter { it.score != null }.sortedBy { it.date }
    val half = measured.size / 2
    val recentMean = measured.drop(half).mapNotNull { it.score }
        .takeIf { it.isNotEmpty() }?.average()?.toInt()
    val earlierMean = measured.take(half).mapNotNull { it.score }
        .takeIf { it.isNotEmpty() }?.average()?.toInt()
    val month = monthPrefix()
    val best = measured.maxByOrNull { it.score ?: 0 }
    val mostReps = state.days.maxByOrNull { it.reps }
    val bestMovement = state.days
        .flatMap { d -> d.byMovement.values.map { d to it } }
        .filter { it.second.score != null }
        .maxByOrNull { it.second.score ?: 0 }

    return ProgressData(
        averageScore = recentMean,
        averageDelta = if (recentMean != null && earlierMean != null) recentMean - earlierMean
                       else null,
        repsThisMonth = state.days.filter { it.date.startsWith(month) }.sumOf { it.reps },
        bestScore = best?.score,
        bestScoreDate = best?.date?.let { shortDate(it) }.orEmpty(),
        trend = measured.takeLast(20).map { TrendPoint(shortDate(it.date), it.score ?: 0) },
        bests = listOfNotNull(
            best?.let {
                PersonalBest(movementEs(it.exercise, it.exerciseLabel), "Mejor día",
                    "${it.score}", "pts", shortDate(it.date))
            },
            mostReps?.takeIf { it.reps > 0 }?.let {
                PersonalBest(movementEs(it.exercise, it.exerciseLabel), "Más reps en un día",
                    "${it.reps}", "reps", shortDate(it.date))
            },
            bestMovement?.let { (day, mv) ->
                PersonalBest(movementEs(mv.exercise, mv.label), "Mejor movimiento",
                    "${mv.score}", "pts", shortDate(day.date))
            },
        ).distinctBy { it.metric },
        faults = FaultTrend.rows(state.faults).take(5),
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
    val rows = FaultTrend.rows(state.faults)
    val focusMovement = movementEs(
        state.goals?.focusExercise
            ?: state.days.firstOrNull { it.reps > 0 }?.exercise.orEmpty()
    )
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
        movement = focusMovement,
        sessions = state.days.count { it.reps > 0 }.coerceAtMost(4),
        focus = focusOf(rows.firstOrNull()),
        secondary = focusOf(rows.getOrNull(1)),
        rules = rules(state),
        drills = drills,
        totalMinutes = drills.sumOf { d -> d.duration.filter { it.isDigit() }.toIntOrNull() ?: 0 },
    )
}

/**
 * The technique rules, taken from the checks the pipeline actually ran on the
 * most recent measured set. A check that could not be made says so — it is
 * never rendered as a pass.
 */
private fun rules(state: UiState): List<CoachRule> {
    val a = state.analysis ?: return emptyList()
    val ledger = FaultTrend.rows(state.faults).associateBy { it.fault }
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
                        "reps juzgadas en la última serie."
                check.notObserved > 0 ->
                    "Comprobado en ${check.notObserved} reps y limpio en todas ellas."
                else ->
                    "No se pudo comprobar en esta serie — ${check.unobservable} reps sin " +
                        "evidencia suficiente. Cambia el ángulo de cámara y vuelve a filmar."
            },
            cue = cueEs(check.name).orEmpty(),
        )
    }
}

// ---- small shared helpers -------------------------------------------------

private fun monthPrefix(): String {
    val c = Calendar.getInstance()
    return "%04d-%02d".format(c.get(Calendar.YEAR), c.get(Calendar.MONTH) + 1)
}

private fun shortDate(iso: String): String = runCatching {
    val inFmt = SimpleDateFormat("yyyy-MM-dd", Locale.UK)
    val outFmt = SimpleDateFormat("d MMM", Locale.forLanguageTag("es"))
    outFmt.format(inFmt.parse(iso)!!)
}.getOrDefault(iso)
