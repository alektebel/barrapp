package com.barrapp.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.barrapp.Progression
import com.barrapp.data.DayEntry
import com.barrapp.data.Goals
import com.barrapp.data.Techniques
import com.barrapp.ui.parts.Eyebrow
import com.barrapp.ui.parts.Panel
import com.barrapp.ui.parts.Pill

/**
 * The referee's page.
 *
 * The top is the plan in one line: what to work, what counts as a set. Below
 * it, every movement the ladder tracks - with history or named as the goal -
 * gets its verdict: the standard written out, the evidence measured, and what
 * is still missing stated in plain words. The referee never says "you are
 * ready" on its own authority; it says the standard was met, and shows the
 * evidence. Both are on this page on purpose.
 */
@Composable
fun PlanScreen(
    days: List<DayEntry>,
    goals: Goals?,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    Column(modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TextButton(onClick = onBack) { Text("Back") }
            Spacer(Modifier.size(6.dp))
            Column(Modifier.weight(1f)) {
                Text("Plan", style = MaterialTheme.typography.titleMedium)
                Text(
                    "What to work, and what earns the next step.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f))

        LazyColumn(
            modifier = Modifier.weight(1f).fillMaxWidth(),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            val verdicts = planVerdicts(days, goals?.focusExercise)
            item {
                Panel {
                    Eyebrow("The plan")
                    Spacer(Modifier.height(8.dp))
                    if (goals?.goal?.isNotBlank() == true) {
                        Text(
                            goals.goal,
                            style = MaterialTheme.typography.bodyLarge,
                        )
                        Spacer(Modifier.height(4.dp))
                    }
                    val focus = verdicts.firstOrNull()
                    if (focus == null) {
                        Text(
                            "Film a set of any ladder movement and the referee " +
                                "starts here: pull-ups, dips, push-ups, squats.",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    } else {
                        Text(
                            "Next session: work ${focus.label.lowercase()}" +
                                focus.nextSetTarget(),
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                }
            }

            items(verdicts, key = { it.movement }) { v ->
                VerdictCard(v)
            }

            // What the next step is for, quoted from open sources - so the
            // page that says "work the dip" can also say what a dip is.
            val next = verdicts.firstOrNull()?.step?.towards
            val technique = next?.let { Techniques.forExercise(context, it) }
            if (technique != null) {
                item { TechniqueCard(technique) }
            }

            item {
                Text(
                    "Every standard here is a published convention, not a measurement. " +
                        "The reps are measured; the bar they have to clear is written down " +
                        "so you can argue with it.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

/** The movements the plan talks about, in the order they matter: the goal's
 *  focus first, then whatever has the most verified history. */
private fun planVerdicts(days: List<DayEntry>, focusExercise: String?): List<Progression.Verdict> {
    val trained = Progression.LADDER.keys.map { Progression.assess(it, days) }
        .filter { it.bestReps > 0 }
        .sortedByDescending { it.bestReps }
    val focus = focusExercise?.takeIf { it in Progression.LADDER }
        ?.let { Progression.assess(it, days) }
        ?.takeIf { it.bestReps == 0 }
    return listOfNotNull(focus) + trained
}

/** The next-session target, stated as a number the standard actually needs. */
private fun Progression.Verdict.nextSetTarget(): String {
    val step = step ?: return ""
    val target = if (bestReps >= step.reps) step.reps
    else minOf(step.reps, bestReps + 2).coerceAtLeast(3)
    return " — aim for $target verified reps in one set" +
        if (step.days > qualifyingDays.size) ", on ${step.days - qualifyingDays.size} " +
            "more day${if (step.days - qualifyingDays.size == 1) "" else "s"}" else ""
}

@Composable
private fun VerdictCard(v: Progression.Verdict) {
    val step = v.step ?: return
    Panel {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Eyebrow(v.label)
                Spacer(Modifier.height(2.dp))
                Text(
                    if (v.ready) "Standard cleared" else "Working towards ${step.towardsLabel}",
                    style = MaterialTheme.typography.titleMedium,
                )
            }
            Pill(
                if (v.ready) "earned" else "${v.bestReps}/${step.reps}",
                color = if (v.ready) MaterialTheme.colorScheme.primary
                else MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Spacer(Modifier.height(10.dp))
        Row(verticalAlignment = Alignment.Bottom) {
            Text(
                "${v.bestReps}",
                fontFamily = FontFamily.Monospace,
                fontWeight = FontWeight.SemiBold,
                style = MaterialTheme.typography.headlineSmall,
                color = if (v.bestReps >= step.reps) MaterialTheme.colorScheme.primary
                else MaterialTheme.colorScheme.onSurface,
            )
            Spacer(Modifier.size(6.dp))
            Text(
                "best session · ${step.reps} reps at ${step.quality}+ on ${step.days} days",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(bottom = 3.dp),
            )
        }
        if (v.evidence.isNotBlank()) {
            Spacer(Modifier.height(8.dp))
            Text(v.evidence, style = MaterialTheme.typography.bodySmall)
        }
        if (v.missing.isNotBlank()) {
            Spacer(Modifier.height(6.dp))
            Text(
                v.missing,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.primary,
            )
        }
        if (v.ready && !step.targetMeasurable) {
            Spacer(Modifier.height(6.dp))
            Text(
                step.note,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
