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
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.barrapp.Progression
import com.barrapp.data.DayEntry
import com.barrapp.data.Goals
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
    Column(modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TextButton(onClick = onBack) { Text("Volver") }
            Spacer(Modifier.size(6.dp))
            Column(Modifier.weight(1f)) {
                Text("Plan", style = MaterialTheme.typography.titleMedium)
                Text(
                    "Qué trabajar y qué te gana el siguiente paso.",
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
                    Eyebrow("El plan")
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
                            "Filma una serie de cualquier movimiento de la escalera y el árbitro " +
                                "empieza aquí: dominadas, fondos, flexiones, sentadillas.",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    } else {
                        Text(
                            "Próxima sesión: trabaja ${focus.label.lowercase()}" +
                                focus.nextSetTarget(),
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                }
            }

            items(verdicts, key = { it.movement }) { v ->
                VerdictCard(v)
            }

            item {
                Text(
                    "Cada estándar de aquí es una convención publicada, no una medición. " +
                        "Las repeticiones se miden; el listón que tienen que superar está escrito " +
                        "para que puedas discutirlo.",
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
    val missingDays = step.days - qualifyingDays.size
    return " — apunta a $target repeticiones verificadas en una serie" +
        if (missingDays > 0) ", en $missingDays día${if (missingDays == 1) "" else "s"} más" else ""
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
                    if (v.ready) "Estándar superado" else "Camino de ${step.towardsLabel}",
                    style = MaterialTheme.typography.titleMedium,
                )
            }
            Pill(
                if (v.ready) "logrado" else "${v.bestReps}/${step.reps}",
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
                "mejor sesión · ${step.reps} reps con ${step.quality}+ en ${step.days} días",
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
