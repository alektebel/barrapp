package com.barrapp.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.foundation.layout.Column
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.lifecycle.viewmodel.compose.viewModel
import com.barrapp.BarrappViewModel
import com.barrapp.Pane
import com.barrapp.data.WorkStore
import com.barrapp.Progression
import com.barrapp.ui.theme.Nocturne
import com.barrapp.ui.parts.bandColor
import com.barrapp.improvementCues
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

    val pickVideo = rememberLauncherForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri -> nstate.goUpload(); vm.upload(uri) }

    val weekNumber = remember { Calendar.getInstance().get(Calendar.WEEK_OF_YEAR) }

    BarrappShell(
        state = nstate,
        subtitle = "Week $weekNumber · ${state.profile.firstName}",
        onPlus = { nstate.goUpload(); pickVideo.launch("video/*") },
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
                    title = "Muscle-up · 2 reps",
                    note = "Solid. Weakest part was smoothness — 31% of the ascent " +
                        "went nowhere.",
                    meta = "Thu 14 Aug · 13s working set",
                    score = 78,
                    ringFraction = 0.78f,
                    ringColor = Nocturne.solid,
                ),
                onOpenSession = {
                    state.days.maxByOrNull { it.date }?.let { vm.selectDate(it.date) }
                    nstate.goSession()
                },
                onOpenCoach = nstate::goCoach,
            )
        },
        calendar = {
            val cal = Calendar.getInstance()
            val month = cal.getDisplayName(
                Calendar.MONTH, Calendar.LONG, Locale.UK) ?: "August"
            val year = "${cal.get(Calendar.YEAR)}"
            val byDate = state.days.associateBy { it.date }
            val daysInMonth = cal.getActualMaximum(Calendar.DAY_OF_MONTH)
            val today = cal.get(Calendar.DAY_OF_MONTH)
            val firstDow = (cal.get(Calendar.DAY_OF_WEEK) + 5) % 7 // Monday first
            val cells = (1..daysInMonth).map { d ->
                val key = "%04d-%02d-%02d".format(
                    cal.get(Calendar.YEAR), cal.get(Calendar.MONTH) + 1, d)
                val day = byDate[key]
                when {
                    day != null && day.reps > 0 -> CalDay(d, if (d == today)
                        CalKind.TODAY else CalKind.MEASURED, bandColor(day.band),
                        leadingBlanks = 0, bold = d == 26)
                    day != null -> CalDay(d, CalKind.DASHED, leadingBlanks = 0)
                    else -> CalDay(d, CalKind.PLAIN, leadingBlanks = 0)
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
                                LadderLine("", "Still needed: " + v.missing, accent = true),
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
                    else -> "Solid set." to "Fix the stall."
                }
                val bandC = bandColor(band)
                SessionScreen(
                    eyebrow = "${a.sessionDate ?: "today"} · ${a.exercise ?: "set"}",
                    verdict = "$l1\n$l2",
                    subtitle = "${a.repCount ?: 0} reps over a " +
                        "%.0f-second working set.".format(
                            (a.trim?.endS ?: 0.0) - (a.trim?.startS ?: 0.0)) +
                        if ((a.repCount ?: 0) < 3)
                            " Under the 3-rep floor, so treat it as one observation." else "",
                    score = a.sessionScore,
                    scoreBand = band,
                    bandColor = bandC,
                    cues = improvementCues(a).ifEmpty {
                        listOf("Nothing flagged — the set measured clean.")
                    },
                    onWatchReplay = { vm.openReplay() },
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
                SessionScreen(
                    eyebrow = "Thu 14 Aug · muscle-up",
                    verdict = "Solid set.\nFix the stall.",
                    subtitle = "2 reps over a 13-second working set. Under the 3-rep " +
                        "floor, so treat it as one observation, not a session.",
                    score = 78, scoreBand = "solid", bandColor = Nocturne.solid,
                    cues = listOf(
                        "Smoothness, 67% — 31% of the ascent made no upward progress. " +
                            "Drive through the sticking point instead of resetting.",
                        "Film 3+ reps. Below that nothing here can be compared to anything.",
                    ),
                    onWatchReplay = null,
                    reps = listOf(
                        RepCardData(
                            title = "Rep 1", chip = "solid", chipColor = Nocturne.solid,
                            score = "78", scoreColor = Nocturne.solid, measured = true,
                            times = "4.2s – 10.1s",
                            trace = listOf(0.02f, 0.08f, 0.22f, 0.4f, 0.58f, 0.62f, 0.65f,
                                0.85f, 0.95f, 0.92f, 0.35f),
                            components = listOf(
                                RepComponent("Range", 40, 86),
                                RepComponent("Control", 25, 87),
                                RepComponent("Smoothness", 35, 67),
                            ),
                            asides = listOf("Swing" to "0.14 torso",
                                "Asymmetry" to "0.06 torso"),
                        ),
                        RepCardData(
                            title = "Rep 3", chip = "unmeasured",
                            chipColor = Nocturne.muted, score = null, scoreColor = null,
                            measured = false,
                            note = "Wrists left the frame at the turnaround. Not a bad " +
                                "rep — an unmeasured one, and it counts neither way.",
                        ),
                    ),
                    runLine = "run 260828-221455-4f8a59 · build 1.2.0 · mediapipe-heavy",
                    onBackToWeek = nstate::goWeek,
                    repsOpen = nstate.repsOpen,
                    onToggleReps = nstate::toggleReps,
                )
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
                onBackToWeek = nstate::goWeek,
            )
        },
    )
}

@Composable
private fun PickHook(onPickVideo: () -> Unit) {
    androidx.compose.runtime.LaunchedEffect(Unit) { }
}

private fun uploadStages(active: com.barrapp.data.Work?): Pair<List<UploadStage>, Int> {
    val stages = listOf(
        UploadStage("Sent", active?.let { w ->
            "clip on the server" + if (w.uploadedParts.isNotEmpty())
                " · ${w.uploadedParts.size} part(s) sent" else ""
        } ?: "22.0s clip · 41 MB"),
        UploadStage("Movement recognised",
            active?.stage?.takeIf { it.contains("recognising", true) }
                ?: "Muscle-up · 91% confident"),
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
