package com.barrapp.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.barrapp.Pane
import com.barrapp.data.DayEntry
import com.barrapp.Progression
import com.barrapp.data.Goals
import com.barrapp.ui.parts.Eyebrow
import com.barrapp.ui.parts.Panel
import com.barrapp.ui.parts.bandColor

/**
 * The week is the page. The design's home leads with the trend: how many reps
 * this week, against last, day by day in the bands the app already speaks —
 * then the next unlock on the ladder, the last session, and the coach.
 */
/** The weekday label column order the design draws: Monday first. The week
 *  arithmetic uses [java.util.Calendar], not java.time — minSdk 24 has no
 *  desugaring, and a home page that crashes on Android 7 would be a poor
 *  trade for nicer date code. */
val WEEK_DAYS = listOf("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

data class WeekTally(
    val reps: Int,
    val days: Int,
    val delta: Int?,
    /** (label, entry) per day, Monday first. */
    val perDay: List<Pair<String, DayEntry?>>,
)

private fun mondayOf(cal: java.util.Calendar): java.util.Calendar {
    val c = cal.clone() as java.util.Calendar
    c.set(java.util.Calendar.HOUR_OF_DAY, 0)
    c.set(java.util.Calendar.MINUTE, 0)
    c.set(java.util.Calendar.SECOND, 0)
    c.set(java.util.Calendar.MILLISECOND, 0)
    c.firstDayOfWeek = java.util.Calendar.MONDAY
    c.set(java.util.Calendar.DAY_OF_WEEK, java.util.Calendar.MONDAY)
    return c
}

private fun keyOf(c: java.util.Calendar): String =
    "%04d-%02d-%02d".format(
        c.get(java.util.Calendar.YEAR),
        c.get(java.util.Calendar.MONTH) + 1,
        c.get(java.util.Calendar.DAY_OF_MONTH),
    )

fun weekTally(days: List<DayEntry>, now: java.util.Calendar = java.util.Calendar.getInstance()): WeekTally {
    val byDate = days.associateBy { it.date }
    val monday = mondayOf(now)
    fun tally(start: java.util.Calendar): Pair<Int, Int> {
        var reps = 0
        var n = 0
        val c = start.clone() as java.util.Calendar
        for (i in 0..6) {
            byDate[keyOf(c)]?.let {
                reps += it.reps
                if (it.reps > 0) n++
            }
            c.add(java.util.Calendar.DAY_OF_MONTH, 1)
        }
        return reps to n
    }
    val (reps, n) = tally(monday)
    val lastMonday = (monday.clone() as java.util.Calendar)
        .apply { add(java.util.Calendar.DAY_OF_MONTH, -7) }
    val (lastReps, _) = tally(lastMonday)
    val perDay = WEEK_DAYS.map { label ->
        val c = monday.clone() as java.util.Calendar
        c.add(java.util.Calendar.DAY_OF_MONTH, WEEK_DAYS.indexOf(label))
        label to byDate[keyOf(c)]
    }
    return WeekTally(
        reps = reps,
        days = n,
        delta = if (lastReps > 0 || reps > 0) reps - lastReps else null,
        perDay = perDay,
    )
}

@Composable
fun WeekHome(
    days: List<DayEntry>,
    goals: Goals?,
    firstName: String,
    onOpenLadder: () -> Unit,
    onOpenCoach: () -> Unit,
    onAdd: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val tally = weekTally(days)
    Column(modifier.fillMaxWidth()) {
        Eyebrow("This week", Modifier.padding(bottom = 8.dp))
        Row(verticalAlignment = Alignment.Bottom) {
            Text(
                "${tally.reps}",
                style = com.barrapp.ui.theme.NumberLarge,
            )
            Spacer(Modifier.padding(start = 8.dp))
            Text(
                "reps measured\nacross ${tally.days} ${if (tally.days == 1) "day" else "days"}",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(bottom = 6.dp),
            )
            Spacer(Modifier.weight(1f))
            tally.delta?.let { d ->
                val label = when {
                    d > 0 -> "+$d vs last"
                    d == 0 -> "level with last"
                    else -> "$d vs last"
                }
                Text(
                    label,
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                    modifier = Modifier
                        .padding(bottom = 8.dp)
                        .background(
                            if (d > 0) MaterialTheme.colorScheme.primaryContainer
                            else MaterialTheme.colorScheme.surfaceVariant,
                            RoundedCornerShape(6.dp),
                        )
                        .padding(horizontal = 9.dp, vertical = 5.dp),
                )
            }
        }

        // Seven columns, one per day, in the bands. Empty days are a stub, not
        // a zero — nothing measured is not the same as measured nothing.
        Row(
            Modifier.fillMaxWidth().padding(top = 18.dp).height(92.dp),
            horizontalArrangement = Arrangement.spacedBy(7.dp),
        ) {
            val maxReps = (tally.perDay.maxOfOrNull { it.second?.reps ?: 0 } ?: 0)
                .coerceAtLeast(1)
            tally.perDay.forEach { (label, entry) ->
                Column(
                    Modifier.weight(1f).fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Bottom,
                ) {
                    val reps = entry?.reps ?: 0
                    val height = when {
                        reps <= 0 -> 4.dp
                        else -> (92.dp * reps / maxReps).coerceAtLeast(12.dp)
                    }
                    Box(
                        Modifier.fillMaxWidth().height(height).background(
                            if (reps > 0) bandColor(entry!!.band)
                            else MaterialTheme.colorScheme.outline,
                            RoundedCornerShape(4.dp),
                        ),
                    )
                    Spacer(Modifier.height(6.dp))
                    Text(
                        label.take(1),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        Spacer(Modifier.height(20.dp))
        NextUnlock(days, goals, onOpenLadder)
        LastSession(days)
        Spacer(Modifier.height(12.dp))
        Panel {
            Text(
                "Ask what the week actually shows",
                style = MaterialTheme.typography.titleSmall,
            )
            TextButton(onClick = onOpenCoach, contentPadding = androidx.compose.foundation.layout.PaddingValues(0.dp)) {
                Text("Open the coach")
            }
        }
    }
}

@Composable
private fun NextUnlock(days: List<DayEntry>, goals: Goals?, onOpenLadder: () -> Unit) {
    val verdicts = Progression.verdicts(days, goals?.focusExercise)
    val step = verdicts.firstOrNull {
        it.step != null && it.qualifyingDays.size < it.step.days
    }?.step ?: verdicts.firstOrNull { it.step != null }?.step ?: return
    val movement = verdicts.first { it.step === step }.movement
    val cleared = verdicts.first { it.step === step }.qualifyingDays.size
    Panel(Modifier.padding(bottom = 12.dp)) {
        Eyebrow("Next unlock")
        Spacer(Modifier.height(6.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "$cleared / ${step.days}",
                style = MaterialTheme.typography.titleLarge,
                color = MaterialTheme.colorScheme.primary,
            )
            Spacer(Modifier.weight(1f))
            Text(
                movement.replace('_', ' ').replaceFirstChar { it.uppercase() },
                style = MaterialTheme.typography.titleSmall,
            )
        }
        Spacer(Modifier.height(4.dp))
        val left = step.days - cleared
        Text(
            "${step.reps} verified reps at ${step.quality}+ · " +
                "$left ${if (left == 1) "day" else "days"} to go",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        TextButton(onClick = onOpenLadder, contentPadding = androidx.compose.foundation.layout.PaddingValues(0.dp)) {
            Text("Your ladder")
        }
    }
}

@Composable
private fun LastSession(days: List<DayEntry>) {
    val last = days.maxByOrNull { it.date } ?: return
    Panel(Modifier.padding(bottom = 12.dp)) {
        Eyebrow("Last session")
        Spacer(Modifier.height(6.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "${last.exerciseLabel.replaceFirstChar { it.uppercase() }} · ${last.reps} reps",
                style = MaterialTheme.typography.titleSmall,
                modifier = Modifier.weight(1f),
            )
            Box(
                Modifier.size(width = 10.dp, height = 10.dp).background(
                    bandColor(last.band), RoundedCornerShape(5.dp),
                ),
            )
        }
        Spacer(Modifier.height(2.dp))
        Text(
            java.text.SimpleDateFormat("EEE d MMM", java.util.Locale.UK)
                .format(java.text.SimpleDateFormat("yyyy-MM-dd", java.util.Locale.UK)
                    .parse(last.date) ?: last.date),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
