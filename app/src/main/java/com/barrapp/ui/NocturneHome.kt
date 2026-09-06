package com.barrapp.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.lifecycle.viewmodel.compose.viewModel
import com.barrapp.BarrappViewModel
import com.barrapp.Pane
import com.barrapp.data.WorkStore
import com.barrapp.Progression
import androidx.compose.ui.unit.dp
import com.barrapp.ui.theme.Nocturne
import com.barrapp.ui.theme.N
import com.barrapp.ui.parts.bandColor
import com.barrapp.improvementLines
import java.util.Calendar
import java.util.Locale

/**
 * The Nocturne prototype, wired to the app's real data. Where the design
 * states a literal, that literal is the fallback; where the app has a
 * measurement, the measurement speaks through the design's own layout.
 */
@Composable
fun NocturneHome(vm: BarrappViewModel = viewModel()) {
    val state by vm.state.collectAsState()
    val nstate = remember { NocturneState() }
    val monthOffset = remember { mutableStateOf(0) }

    val pickVideo = rememberLauncherForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri -> nstate.goUpload(); vm.upload(uri) }

    val weekNumber = remember { Calendar.getInstance().get(Calendar.WEEK_OF_YEAR) }

    // The shell navigates by `nstate`, but a finished measurement only lands
    // in the view model's own state - so the upload screen used to sit on
    // "Measuring your set" after the result had already arrived, and the only
    // way to it was the "Skip ahead" button. Carry the completion across:
    // once nothing is in flight and a measurement exists, show it.
    val measuring = state.works.any { it.active }
    androidx.compose.runtime.LaunchedEffect(measuring, state.analysis) {
        if (nstate.effective == NScreen.UPLOAD && !measuring && state.analysis != null) {
            nstate.goSession()
        }
    }

    BarrappShell(
        state = nstate,
        subtitle = "Week $weekNumber · ${state.profile.firstName}",
        onPlus = { nstate.goUpload(); pickVideo.launch("video/*") },
        onAccount = vm::openPrivacy,
        week = {
            val tally = weekTally(state.days)
            val focus = state.goals?.focusExercise
            val verdicts = Progression.verdicts(state.days, focus)
            val next = verdicts.firstOrNull {
                it.step != null && it.qualifyingDays.size < it.step.days
            }
            val bars = designBars(tally)
            WeekScreen(
                reps = tally.reps,
                measuredDays = tally.days,
                delta = when {
                    tally.delta == null -> "first week"
                    tally.delta > 0 -> "+${tally.delta} vs last"
                    tally.delta == 0 -> "level with last"
                    else -> "${tally.delta} vs last"
                },
                bars = bars,
                unlockTitle = next?.movement?.replace('_', ' ')
                    ?.replaceFirstChar { it.uppercase() } ?: "Muscle-up",
                unlockCount = next?.let { "${it.qualifyingDays.size} / ${it.step?.days ?: 0}" }
                    ?: "5 / 8",
                unlockNote = next?.let { v ->
                    val left = (v.step?.days ?: 0) - v.qualifyingDays.size
                    "${v.step?.reps ?: 0} verified reps and $left " +
                        "qualifying ${if (left == 1) "day" else "days"} to go."
                } ?: "3 verified reps and 2 qualifying days to go.",
                unlockProgress = next?.let { v ->
                    if (v.step != null && v.step.days > 0)
                        v.qualifyingDays.size.toFloat() / v.step.days else 0.62f
                } ?: 0.62f,
                onOpenLadder = nstate::goTree,
                lastSession = state.days.maxByOrNull { it.date }?.let { day ->
                    LastSessionCard(
                        title = "${day.exerciseLabel.replaceFirstChar { it.uppercase() }} · " +
                            "${day.reps} reps",
                        note = when (day.band) {
                            "strong" -> "Strong. The set held its shape throughout."
                            "solid" -> "Solid. The technique carried every rep."
                            "shaky" -> "Shaky. The standards slipped on parts of the set."
                            else -> "Broken down. The reps did not hold together."
                        },
                        meta = "${formatShortDate(day.date)} · working set",
                        score = day.score ?: 0,
                        ringFraction = (day.score ?: 0) / 100f,
                        ringColor = bandColor(day.band),
                    )
                } ?: LastSessionCard(
                    // Nothing measured yet. The design's literal here was a
                    // full fake record - "Muscle-up · 2 reps, Thu 14 Aug,
                    // score 78" - which a new user read as their own training
                    // (feedback B1). An empty state says less and lies none.
                    title = "No session yet",
                    note = "Film a set and barra will measure it. Your last " +
                        "session shows up here.",
                    meta = "",
                    score = null,
                    ringFraction = 0f,
                    ringColor = bandColor("unmeasured"),
                ),
                onOpenSession = {
                    state.days.maxByOrNull { it.date }?.let { vm.selectDate(it.date) }
                    nstate.goSession()
                },
                onOpenCoach = nstate::goCoach,
            )
        },
        calendar = {
            // monthOffset lets the ‹ › arrows walk the calendar; it starts at
            // the current month. Only the current month marks a "today" cell.
            val cal = Calendar.getInstance().apply {
                add(Calendar.MONTH, monthOffset.value)
            }
            val month = cal.getDisplayName(
                Calendar.MONTH, Calendar.LONG, Locale.UK) ?: "August"
            val year = "${cal.get(Calendar.YEAR)}"
            val byDate = state.days.associateBy { it.date }
            val daysInMonth = cal.getActualMaximum(Calendar.DAY_OF_MONTH)
            val today = if (monthOffset.value == 0) cal.get(Calendar.DAY_OF_MONTH) else -1
            // The leading blanks belong to the FIRST day of the displayed month.
            val firstOfMonth = (cal.clone() as Calendar).apply {
                set(Calendar.DAY_OF_MONTH, 1)
            }
            val firstDow = (firstOfMonth.get(Calendar.DAY_OF_WEEK) + 5) % 7 // Monday first
            val cells = (1..daysInMonth).map { d ->
                val key = "%04d-%02d-%02d".format(
                    cal.get(Calendar.YEAR), cal.get(Calendar.MONTH) + 1, d)
                val day = byDate[key]
                when {
                    day != null && day.reps > 0 -> CalDay(d, if (d == today)
                        CalKind.TODAY else CalKind.MEASURED, bandColor(day.band),
                        leadingBlanks = if (d == 1) firstDow else 0, bold = d == 26)
                    day != null -> CalDay(d, CalKind.DASHED,
                        leadingBlanks = if (d == 1) firstDow else 0)
                    else -> CalDay(d, CalKind.PLAIN,
                        leadingBlanks = if (d == 1) firstDow else 0)
                }
            }
            val measured = state.days.count { it.reps > 0 }
            val totalReps = state.days.sumOf { it.reps }
            val rows = state.days.sortedByDescending { it.date }.take(3).map { day ->
                CalRow(
                    title = day.exerciseLabel.replaceFirstChar { it.uppercase() },
                    subtitle = if (day.reps > 0)
                        "${day.reps} reps · ${formatShortDate(day.date)}"
                    else "filmed · ${formatShortDate(day.date)}",
                    score = day.score?.toString() ?: "—",
                    color = bandColor(day.band),
                    scoreColor = if (day.score != null) bandColor(day.band)
                        else Nocturne.fgA(0.4f),
                    clickable = day.reps > 0,
                    day = day.date.takeLast(2).toIntOrNull() ?: 1,
                )
            }
            CalendarScreen(
                month = month, year = year,
                days = cells,
                summaryMeasured = "$measured measured days",
                summaryReps = "$totalReps reps in $month",
                rows = rows,
                onPrevMonth = { monthOffset.value-- },
                onNextMonth = { monthOffset.value++ },
                onOpenDay = { n ->
                    val key = "%04d-%02d-%02d".format(
                        cal.get(Calendar.YEAR), cal.get(Calendar.MONTH) + 1, n)
                    byDate[key]?.let { vm.selectDate(it.date) }
                    nstate.goSession()
                },
            )
        },
        tree = {
            val verdicts = Progression.verdicts(state.days, state.goals?.focusExercise)
            val steps = buildList {
                if (verdicts.isEmpty()) {
                    add(LadderStep("Push-up", LadderChipKind.EARNED,
                        lines = listOf(LadderLine("", "19 verified at 94 · 3 qualifying days")),
                        dot = LadderDot.EARNED))
                    add(LadderStep("Diamond push-up", LadderChipKind.READY,
                        lines = listOf(LadderLine("", "Standard cleared. Film a set and " +
                            "it starts counting.")),
                        dot = LadderDot.EARNED, borderColor = Nocturne.accentDeep))
                    add(LadderStep("Pull-up", LadderChipKind.EARNED,
                        lines = listOf(LadderLine("", "8 verified at 81 · 2 qualifying days")),
                        dot = LadderDot.EARNED))
                }
                verdicts.forEach { v ->
                    val step = v.step ?: return@forEach
                    val earned = v.qualifyingDays.size >= step.days
                    val ready = v.ready && !earned
                    when {
                        earned -> add(LadderStep(
                            v.movement.replace('_', ' ').replaceFirstChar { it.uppercase() },
                            LadderChipKind.EARNED,
                            lines = listOf(LadderLine("", v.evidence)),
                            dot = LadderDot.EARNED))
                        ready -> add(LadderStep(
                            v.movement.replace('_', ' ').replaceFirstChar { it.uppercase() },
                            LadderChipKind.READY,
                            lines = listOf(LadderLine("", "Standard cleared. Film a set " +
                                "and it starts counting.")),
                            dot = LadderDot.EARNED, borderColor = Nocturne.accentDeep))
                        else -> add(LadderStep(
                            v.movement.replace('_', ' ').replaceFirstChar { it.uppercase() },
                            null,
                            count = "${v.qualifyingDays.size} / ${step.days}",
                            progress = if (step.days > 0)
                                v.qualifyingDays.size.toFloat() / step.days else 0f,
                            lines = listOf(
                                LadderLine("The standard", v.standard),
                                LadderLine("Your evidence", v.evidence),
                                // v.missing already begins with "Still needed: " -
                                // prepending it again produced "Still needed: Still needed:".
                                LadderLine("", v.missing, accent = true),
                            ),
                            dot = LadderDot.CURRENT, big = true,
                            borderColor = Nocturne.accentDeep))
                    }
                }
                add(LadderStep("Weighted pull-up", LadderChipKind.NOT_MEASURABLE,
                    lines = listOf(LadderLine("",
                        "Barra can't verify added load. The refereeing ends here.")),
                    dot = LadderDot.LOCKED, ghost = true))
            }
            LadderScreen(steps)
        },
        session = {
            val a = state.analysis
            if (a != null) {
                val band = a.sessionBand
                val (l1, l2) = when (band) {
                    "strong" -> "Strong set." to "Keep the standard."
                    "shaky" -> "Shaky set." to "The basics slipped."
                    "broken" -> "Broken down." to "Start smaller."
                    "unmeasured" -> "Not measured." to "Barra couldn't score this set."
                    else -> "Solid set." to "Fix the stall."
                }
                val bandC = bandColor(band)
                // Humanise the header: "5 Sept · Muscle-up", never the raw enum
                // and ISO date ("2026-09-05 · PUSH_UP").
                val exLabel = (a.exercise ?: "set")
                    .replace("_", " ")
                    .lowercase()
                    .split(" ")
                    .joinToString(" ") { it.replaceFirstChar(Char::uppercase) }
                val dateLabel = a.sessionDate?.takeIf { it.isNotBlank() }
                    ?.let { formatShortDate(it) } ?: "today"
                SessionScreen(
                    eyebrow = "$dateLabel · $exLabel",
                    verdict = "$l1\n$l2",
                    subtitle = "${a.repCount ?: 0} reps over a " +
                        "%.0f-second working set.".format(
                            (a.trim?.endS ?: 0.0) - (a.trim?.startS ?: 0.0)) +
                        if ((a.repCount ?: 0) < 3)
                            " Under the 3-rep floor, so treat it as one observation." else "",
                    score = a.sessionScore,
                    scoreBand = band,
                    bandColor = bandC,
                    cues = improvementLines(a),
                    onWatchReplay = state.current?.let { { vm.openReplay() } },
                    reps = a.reps.map { rep ->
                        RepCardData(
                            title = rep.label.replace("_", " ")
                                .replaceFirstChar { it.uppercase() },
                            chip = rep.band,
                            chipColor = bandColor(rep.band),
                            score = rep.score?.toString(),
                            scoreColor = bandColor(rep.band),
                            measured = rep.score != null,
                            times = "%.1fs – %.1fs".format(rep.startS, rep.endS),
                            trace = rep.trace,
                            traceColor = bandColor(rep.band),
                            components = rep.components.map { c ->
                                RepComponent(c.name,
                                    (c.weight * 100).toInt(),
                                    c.value?.toInt() ?: 0)
                            },
                            asides = rep.asides.map { a2 ->
                                a2.name.replaceFirstChar { it.uppercase() } to
                                    "%.2f torso".format(a2.value)
                            },
                            note = rep.scoreNote.ifBlank {
                                "Wrists left the frame. Not a bad rep — an unmeasured " +
                                    "one, and it counts neither way."
                            },
                        )
                    },
                    runLine = "run ${a.traceId} · build ${a.provenance?.commit ?: "?"} · " +
                        "${a.provenance?.poseModel ?: "pose"}",
                    onBackToWeek = nstate::goWeek,
                    repsOpen = nstate.repsOpen,
                    onToggleReps = nstate::toggleReps,
                )
            } else {
                // No measured session is selected. Show an honest empty state
                // rather than a hardcoded example - the example is what made
                // every session entry point appear to open the same stale
                // "14 Aug muscle-up" record (see feedback B1).
                Column(Modifier.fillMaxWidth()) {
                    androidx.compose.material3.Text("No session", style = N.pageTitle)
                    androidx.compose.material3.Text(
                        "Pick a measured day from the calendar, or film a set.",
                        style = N.bodyNote, modifier = Modifier.padding(top = 6.dp),
                    )
                }
            }
        },
        upload = {
            val active = state.works.firstOrNull { it.active }
            val (stages, activeIndex) = uploadStages(active)
            Column {
                UploadScreen(
                    stages = stages,
                    activeIndex = activeIndex,
                    done = active == null && state.analysis != null,
                    onSkip = {
                        if (state.analysis != null) nstate.goSession() else nstate.goWeek()
                    },
                    onBackToWeek = nstate::goWeek,
                )
                if (state.works.isNotEmpty()) {
                    WorksSection(
                        works = state.works,
                        onOpenLog = vm::openWorkLog,
                        onRetry = vm::retryWork,
                        onDismiss = vm::dismissWork,
                        modifier = Modifier,
                    )
                }
            }
        },
        coach = {
            CoachScreen(
                turns = state.chat.map { t ->
                    CoachTurn(t.fromUser, t.text, "")
                },
                thinking = state.coachThinking,
                suggestions = vm.suggestions().take(3),
                onSend = vm::ask,
                // Coach is a root tab, not a detail - no back link.
                onBackToWeek = null,
            )
        },
    )
}

@Composable
private fun PickHook(onPickVideo: () -> Unit) {
    androidx.compose.runtime.LaunchedEffect(Unit) { }
}

private fun uploadStages(active: com.barrapp.data.Work?): Pair<List<UploadStage>, Int> {
    // Every subtitle here is either something this work actually reported or
    // a description of the step. Never an example measurement: the old
    // fallbacks ("22.0s clip · 41 MB", "Muscle-up · 91% confident") rendered
    // whenever no work was active - which is exactly when a job had just
    // finished - so the screen showed a clip size and a movement the server
    // never measured, in the same type as the real thing (see feedback B1).
    val stages = listOf(
        UploadStage("Sent", active?.let { w ->
            "clip on the server" + if (w.uploadedParts.isNotEmpty())
                " · ${w.uploadedParts.size} part(s) sent" else ""
        } ?: "The clip is on the server"),
        UploadStage("Movement recognised",
            active?.stage?.takeIf { it.contains("recognising", true) }
                ?: "Working out which exercise this is"),
        UploadStage("Trimming to the working set",
            "Dropping the walk-up and the drop-off"),
        UploadStage("Counting and measuring reps",
            "Range, control, smoothness, per rep"),
    )
    val idx = when (active?.status) {
        WorkStore.STATUS_SENDING, WorkStore.STATUS_CONNECTING -> 0
        WorkStore.STATUS_QUEUED -> 1
        WorkStore.STATUS_MEASURING -> when {
            active.stage.contains("recognising", true) -> 1
            active.stage.contains("pose", true) -> 1
            active.stage.contains("finding", true) || active.stage.contains("scoring", true) -> 3
            else -> 2
        }
        else -> 2
    }
    return stages to idx
}

@Composable
private fun designBars(tally: WeekTally): List<WeekBar> {
    val max = tally.perDay.maxOfOrNull { it.second?.reps ?: 0 } ?: 0
    return tally.perDay.map { (label, entry) ->
        val reps = entry?.reps ?: 0
        when {
            reps > 0 -> WeekBar(label.take(1), reps / max.coerceAtLeast(1).toFloat(),
                bandColor(entry!!.band))
            entry != null -> WeekBar(label.take(1), 0.10f, null, dashed = true)
            else -> WeekBar(label.take(1), null, null)
        }
    }
}

private fun formatShortDate(iso: String): String = runCatching {
    val inFmt = java.text.SimpleDateFormat("yyyy-MM-dd", Locale.UK)
    val outFmt = java.text.SimpleDateFormat("d MMM", Locale.UK)
    outFmt.format(inFmt.parse(iso)!!)
}.getOrDefault(iso)
