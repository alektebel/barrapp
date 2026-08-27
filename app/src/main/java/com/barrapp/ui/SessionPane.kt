package com.barrapp.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.barrapp.data.Analysis
import com.barrapp.data.RepRow
import com.barrapp.ui.parts.ComponentBar
import com.barrapp.ui.parts.Eyebrow
import com.barrapp.ui.parts.Panel
import com.barrapp.ui.parts.Pill
import com.barrapp.ui.parts.RepTrace
import com.barrapp.ui.parts.ScoreRing
import com.barrapp.ui.parts.bandColor

/**
 * The empty state.
 *
 * A single sentence and one target. No illustration, no motivational line: the
 * app has nothing to say yet and pretending otherwise is how empty states end
 * up feeling like an apology. The plus is large, centred and the only thing to
 * press.
 */
@Composable
fun EmptyState(
    onAdd: () -> Unit,
    onSeeExample: (() -> Unit)? = null,
    modifier: Modifier = Modifier,
) {
    Box(modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier.widthIn(max = 380.dp).padding(32.dp),
        ) {
            // The greeting lives in the shell header. Repeating it here read as
            // the app saying hello twice on the one screen where it has least
            // to say.
            Text(
                "You have no training recordings",
                style = MaterialTheme.typography.headlineMedium,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(10.dp))
            Text(
                "Add a clip of a set. It gets trimmed to the exercise, the movement " +
                    "is recognised, and every rep is counted and measured.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(30.dp))
            AddButton(onAdd, large = true)
            if (onSeeExample != null) {
                Spacer(Modifier.height(12.dp))
                TextButton(onClick = onSeeExample) {
                    Text("See an example first")
                }
            }
        }
    }
}

@Composable
fun AddButton(onClick: () -> Unit, large: Boolean = false, modifier: Modifier = Modifier) {
    val diameter = if (large) 68.dp else 52.dp
    Surface(
        onClick = onClick,
        shape = CircleShape,
        color = MaterialTheme.colorScheme.primary,
        modifier = modifier.size(diameter),
    ) {
        Box(contentAlignment = Alignment.Center) {
            Icon(
                Icons.Filled.Add,
                contentDescription = "Add a training clip",
                tint = MaterialTheme.colorScheme.onPrimary,
                modifier = Modifier.size(if (large) 32.dp else 24.dp),
            )
        }
    }
}

/**
 * What the app is doing to the clip, named step by step.
 *
 * Upload progress is genuinely unknown until the server answers, so this shows
 * the named stages instead of a fake percentage. People tolerate a wait they
 * can see the shape of; they do not tolerate a bar that sits at 90%.
 */
@Composable
fun ProcessingState(
    stage: String,
    exerciseGuess: String?,
    error: String?,
    onCancel: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val stages = listOf(
        "Uploading the clip",
        "Finding the exercise",
        "Trimming to the working set",
        "Counting and measuring the reps",
    )
    val activeIndex = stages.indexOfFirst { it.equals(stage, ignoreCase = true) }
        .let { if (it < 0) 0 else it }

    Box(modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(
            Modifier.widthIn(max = 420.dp).padding(32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            PulsingBar()
            Spacer(Modifier.height(26.dp))
            stages.forEachIndexed { index, label ->
                Row(
                    Modifier.fillMaxWidth().padding(vertical = 7.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    val done = index < activeIndex
                    val active = index == activeIndex
                    Box(
                        Modifier
                            .size(8.dp)
                            .clip(CircleShape)
                            .background(
                                when {
                                    done -> MaterialTheme.colorScheme.primary.copy(alpha = 0.5f)
                                    active -> MaterialTheme.colorScheme.primary
                                    else -> MaterialTheme.colorScheme.outline
                                }
                            )
                    )
                    Text(
                        label,
                        style = MaterialTheme.typography.bodyMedium,
                        color = when {
                            active -> MaterialTheme.colorScheme.onSurface
                            done -> MaterialTheme.colorScheme.onSurfaceVariant
                            else -> MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f)
                        },
                    )
                    if (active) {
                        Spacer(Modifier.weight(1f))
                        CircularProgressIndicator(
                            Modifier.size(14.dp),
                            strokeWidth = 2.dp,
                        )
                    }
                }
            }
            AnimatedVisibility(exerciseGuess != null) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Spacer(Modifier.height(16.dp))
                    Pill("Looks like ${exerciseGuess.orEmpty()}", color = MaterialTheme.colorScheme.primary)
                }
            }
            if (error != null) {
                Spacer(Modifier.height(20.dp))
                Text(error, color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodyMedium, textAlign = TextAlign.Center)
            }
            Spacer(Modifier.height(26.dp))
            TextButton(onClick = onCancel) { Text("Cancel") }
        }
    }
}

@Composable
private fun PulsingBar() {
    val transition = rememberInfiniteTransition(label = "pulse")
    val phase by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(1600, easing = LinearEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = "phase",
    )
    val colour = MaterialTheme.colorScheme.primary
    val track = MaterialTheme.colorScheme.outline
    Canvas(Modifier.fillMaxWidth().height(34.dp)) {
        // Pixels, not dp - see RepTrace in parts/Parts.kt.
        val hair = 1.dp.toPx()
        val line = 2.5.dp.toPx()
        val half = 45.dp.toPx()          // half-width of the travelling arc
        val step = 3.dp.toPx()
        val mid = size.height / 2
        drawLine(
            color = track.copy(alpha = 0.4f),
            start = Offset(0f, mid),
            end = Offset(size.width, mid),
            strokeWidth = hair, cap = StrokeCap.Round,
        )
        // A rep-shaped pulse travelling left to right: the same arc the app is
        // looking for in the clip.
        val w = size.width
        val head = phase * (w + 2 * half) - half
        val path = Path()
        var first = true
        var t = -half
        while (t <= half) {
            val x = head + t
            val y = mid - (kotlin.math.cos(t / half * Math.PI.toFloat() / 2f) * mid * 0.75f)
            if (x in 0f..w) {
                if (first) { path.moveTo(x, y); first = false } else path.lineTo(x, y)
            }
            t += step
        }
        if (!first) drawPath(path, colour, style = Stroke(width = line, cap = StrokeCap.Round))
    }
}

/** A measured session: what it was, how many reps, and every rep in order. */
@Composable
fun SessionDetail(
    analysis: Analysis,
    onAdd: () -> Unit,
    onDelete: (() -> Unit)?,
    modifier: Modifier = Modifier,
) {
    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item { SessionHeader(analysis) }

        if (analysis.reps.isNotEmpty()) {
            item { Eyebrow("Reps") }
            itemsIndexed(analysis.reps) { index, rep -> RepCard(rep, index + 1) }
        }

        if (analysis.narrative.isNotBlank()) {
            item {
                Panel {
                    Eyebrow("Read-out")
                    Spacer(Modifier.height(8.dp))
                    Text(analysis.narrative, style = MaterialTheme.typography.bodyMedium)
                }
            }
        }

        if (analysis.blockers.isNotEmpty()) {
            item {
                Panel {
                    Eyebrow("Why some of this is held back")
                    Spacer(Modifier.height(8.dp))
                    analysis.blockers.forEach {
                        Text(
                            "· " + it.replaceFirstChar { c -> c.uppercase() }
                                .let { line -> if (line.endsWith(".")) line else "$line." },
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(vertical = 2.dp),
                        )
                    }
                }
            }
        }

        if (analysis.nextSession.isNotBlank()) {
            item {
                Panel {
                    Eyebrow("Next session")
                    Spacer(Modifier.height(8.dp))
                    Text(analysis.nextSession, style = MaterialTheme.typography.bodyMedium)
                }
            }
        }

        item {
            Row(
                Modifier.fillMaxWidth().padding(top = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                FilledTonalButton(onClick = onAdd, modifier = Modifier.weight(1f)) {
                    Text("Add another clip")
                }
                if (onDelete != null) {
                    OutlinedButton(onClick = onDelete) { Text("Delete") }
                }
            }
        }
    }
}

@Composable
private fun SessionHeader(analysis: Analysis) {
    Panel {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Eyebrow(analysis.sessionDate.ifBlank { "Session" })
                Spacer(Modifier.height(6.dp))
                Text(
                    analysis.detected?.label
                        ?: analysis.exercise.replace('_', ' ').replaceFirstChar { it.uppercase() },
                    style = MaterialTheme.typography.headlineSmall,
                )
                Spacer(Modifier.height(6.dp))
                Text(
                    "${analysis.repCount} rep${if (analysis.repCount == 1) "" else "s"} measured" +
                        if (analysis.candidateCount > analysis.repCount)
                            " of ${analysis.candidateCount} found" else "",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            ScoreRing(
                score = analysis.sessionScore,
                band = analysis.sessionBand,
                diameter = 76.dp,
                caption = "session",
            )
        }

        analysis.detected?.let { d ->
            Spacer(Modifier.height(14.dp))
            HorizontalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f))
            Spacer(Modifier.height(12.dp))
            Row(verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Pill(
                    if (d.certain) "recognised" else "uncertain",
                    color = if (d.certain) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    "${(d.confidence * 100).toInt()}% confident",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Spacer(Modifier.height(8.dp))
            Text(
                d.reason.replaceFirstChar { it.uppercase() } + ".",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (!d.certain && d.runnerUp != null) {
                Spacer(Modifier.height(6.dp))
                Text(
                    "Could also be a ${d.runnerUp.replace('_', ' ')}.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        analysis.trim?.let { t ->
            Spacer(Modifier.height(10.dp))
            Text(
                "Trimmed to %.1fs–%.1fs of a %.1fs clip.".format(t.startS, t.endS, analysis.durationS),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun RepCard(rep: RepRow, number: Int) {
    val colour = bandColor(rep.band)
    Panel(padding = PaddingValues(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text("Rep $number", style = MaterialTheme.typography.titleMedium)
                    Pill(rep.band, color = colour)
                }
                Spacer(Modifier.height(4.dp))
                Text(
                    "%.1fs–%.1fs".format(rep.startS, rep.endS),
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            ScoreRing(rep.score, rep.band, diameter = 56.dp)
        }

        if (rep.trace.size >= 3) {
            Spacer(Modifier.height(12.dp))
            RepTrace(rep.trace, rep.band)
        }

        if (rep.score == null) {
            Spacer(Modifier.height(10.dp))
            Text(
                rep.scoreNote.ifBlank { "This rep could not be measured." },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else if (rep.components.isNotEmpty()) {
            Spacer(Modifier.height(14.dp))
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                rep.components.forEach { c ->
                    ComponentBar(c.name, c.value, c.why, c.weight)
                }
            }
        }

        if (rep.asides.isNotEmpty()) {
            Spacer(Modifier.height(14.dp))
            HorizontalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = 0.4f))
            Spacer(Modifier.height(10.dp))
            Eyebrow("Measured, not scored")
            Spacer(Modifier.height(6.dp))
            rep.asides.forEach { a ->
                Row(
                    Modifier.fillMaxWidth().padding(vertical = 2.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text(
                        a.name.replaceFirstChar { it.uppercase() },
                        style = MaterialTheme.typography.bodySmall,
                    )
                    Text(
                        "%.2f torso".format(a.value),
                        fontFamily = FontFamily.Monospace,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        rep.problems.forEach {
            Spacer(Modifier.height(8.dp))
            Text(it, style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error)
        }
    }
}
