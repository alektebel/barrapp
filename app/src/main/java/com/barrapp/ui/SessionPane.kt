package com.barrapp.ui

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
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
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.barrapp.Voice
import com.barrapp.data.Analysis
import com.barrapp.data.Hold
import com.barrapp.data.RepRow
import com.barrapp.data.Technique
import com.barrapp.improvementCues
import com.barrapp.ui.parts.BarraFigure
import com.barrapp.ui.parts.ComponentBar
import com.barrapp.ui.parts.Eyebrow
import com.barrapp.ui.parts.Panel
import com.barrapp.ui.parts.Pill
import com.barrapp.ui.parts.RepTrace
import com.barrapp.ui.parts.ScoreRing
import com.barrapp.ui.parts.bandColor
import com.barrapp.ui.theme.Numeric
import kotlinx.coroutines.delay

/**
 * The empty state.
 *
 * The figure does its reps quietly on the bar, because that is what the app
 * is for and a picture of it beats a paragraph. The copy says what happens
 * when a clip is added and what does not - no leaderboard - and nothing else.
 * The plus is large, centred and the only thing to press.
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
            BarraFigure(stage = -1, width = 160.dp, height = 150.dp)
            Spacer(Modifier.height(18.dp))
            Text(
                Voice.EMPTY_TITLE,
                style = MaterialTheme.typography.headlineMedium,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(10.dp))
            Voice.EMPTY_LINES.forEach { line ->
                Text(
                    line,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.padding(vertical = 3.dp),
                )
            }
            Spacer(Modifier.height(26.dp))
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

/** The plus. Shrinks a little under the finger so a press reads as a press,
 *  which a flat circle on a flat background otherwise does not. */
@Composable
fun AddButton(onClick: () -> Unit, large: Boolean = false, modifier: Modifier = Modifier) {
    val diameter = if (large) 68.dp else 52.dp
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    val scale by animateFloatAsState(
        targetValue = if (pressed) 0.92f else 1f,
        animationSpec = tween(120),
        label = "press",
    )
    Surface(
        onClick = onClick,
        shape = CircleShape,
        color = MaterialTheme.colorScheme.primary,
        interactionSource = interaction,
        modifier = modifier
            .size(diameter)
            .graphicsLayer { scaleX = scale; scaleY = scale },
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
 * What the app is doing to the clip, shown rather than described.
 *
 * The figure works through the stages the pipeline actually has: hands
 * bracketed while the exercise is being found, trim markers while the set is
 * being cut out, lockouts counted while the reps are. Under it, the stage
 * names, and under the active one a line that changes every few seconds so a
 * long wait keeps saying something true. No percentage: the server does not
 * report one and a bar stuck at 90% is a lie.
 */
@Composable
fun ProcessingState(
    stage: String,
    exerciseGuess: String?,
    error: String?,
    onCancel: () -> Unit,
    modifier: Modifier = Modifier,
    seed: Int = 0,
) {
    val stages = Voice.STAGES.map { it.name }
    val activeIndex = stages.indexOfFirst { it.equals(stage, ignoreCase = true) }
        .let { if (it < 0) 0 else it }

    // A tick every few seconds rotates the stage line and counts the wait,
    // honestly, in seconds - because "still working" for two minutes is a
    // different thing from "still working" for ten, and the person waiting
    // is entitled to know which.
    var tick by remember { mutableIntStateOf(0) }
    var elapsed by remember { mutableIntStateOf(0) }
    LaunchedEffect(Unit) {
        while (true) {
            delay(1000)
            elapsed += 1
            if (elapsed % 4 == 0) tick += 1
        }
    }

    Box(modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(
            Modifier.widthIn(max = 420.dp).padding(horizontal = 32.dp, vertical = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Row(
                Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(Voice.processingTitle(seed), style = MaterialTheme.typography.headlineSmall)
                Text(
                    "${elapsed}s",
                    style = MaterialTheme.typography.labelMedium.merge(Numeric),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Spacer(Modifier.height(8.dp))
            BarraFigure(stage = activeIndex, width = 220.dp, height = 240.dp)
            Spacer(Modifier.height(10.dp))
            stages.forEachIndexed { index, label ->
                val done = index < activeIndex
                val active = index == activeIndex
                Column(Modifier.fillMaxWidth().padding(vertical = 5.dp)) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
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
                            style = if (active) MaterialTheme.typography.titleSmall
                            else MaterialTheme.typography.bodyMedium,
                            color = when {
                                active -> MaterialTheme.colorScheme.onSurface
                                done -> MaterialTheme.colorScheme.onSurfaceVariant
                                else -> MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f)
                            },
                        )
                    }
                    AnimatedVisibility(active) {
                        AnimatedContent(
                            targetState = Voice.stageLine(label, tick, seed),
                            transitionSpec = {
                                (fadeIn(tween(260)) + slideInVertically(tween(260)) { it / 3 })
                                    .togetherWith(fadeOut(tween(160)) + slideOutVertically(tween(160)) { -it / 3 })
                            },
                            label = "stageLine",
                        ) { line ->
                            Text(
                                line,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(start = 20.dp, top = 4.dp),
                            )
                        }
                    }
                }
            }
            AnimatedVisibility(exerciseGuess != null) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Spacer(Modifier.height(12.dp))
                    Pill("Looks like ${exerciseGuess.orEmpty()}", color = MaterialTheme.colorScheme.primary)
                }
            }
            if (error != null) {
                Spacer(Modifier.height(16.dp))
                Text(
                    Voice.failure(error), color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodyMedium, textAlign = TextAlign.Center,
                )
            }
            Spacer(Modifier.height(18.dp))
            TextButton(onClick = onCancel) { Text("Cancel") }
        }
    }
}

/** A measured session: what it was, how many reps, and every rep in order.
 *  Or a held position: what it was and for how long. */
@Composable
fun SessionDetail(
    analysis: Analysis,
    onAdd: () -> Unit,
    onDelete: (() -> Unit)?,
    modifier: Modifier = Modifier,
    onReplay: (() -> Unit)? = null,
    technique: Technique? = null,
) {
    var repsExpanded by remember { mutableStateOf(false) }
    val hold = analysis.hold
    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item { SessionHeader(analysis, repsExpanded, onToggleReps =
            if (analysis.reps.isEmpty()) null else ({ repsExpanded = !repsExpanded })) }

        if (onReplay != null) {
            item {
                OutlinedButton(onClick = onReplay, modifier = Modifier.fillMaxWidth()) {
                    Text(if (hold != null) "Watch the hold again" else "Watch again, with the feedback on the timeline")
                }
            }
        }

        if (hold != null) {
            // A hold has nothing to improve on the evidence available - the
            // seconds are the measurement - so the card says what it saw
            // and how sure it is, and stops there.
            item { HoldCard(hold) }
        } else {
            // The whole verdict in one line, then at most three things to fix.
            // Everything measured lives one tap away; what sits on the surface
            // is what carries into the next set.
            item {
                Panel {
                    Eyebrow("Improve")
                    Spacer(Modifier.height(8.dp))
                    val cues = improvementCues(analysis)
                    if (cues.isEmpty()) {
                        Text(
                            "Nothing flagged — the set measured clean.",
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    } else {
                        cues.forEachIndexed { i, cue ->
                            Text(
                                "${i + 1}.  $cue",
                                style = MaterialTheme.typography.bodyLarge,
                                modifier = Modifier.padding(vertical = 4.dp),
                            )
                        }
                    }
                    if (analysis.headline.isNotBlank()) {
                        Spacer(Modifier.height(8.dp))
                        Text(
                            analysis.headline,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    if (analysis.narrative.isNotBlank()) {
                        var full by remember { mutableStateOf(false) }
                        TextButton(onClick = { full = !full }, contentPadding = PaddingValues(0.dp)) {
                            Text(if (full) "Show less" else "Read the full analysis")
                        }
                        if (full) {
                            Text(analysis.narrative, style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                }
            }
        }

        if (technique != null) {
            item { TechniqueCard(technique) }
        }

        // Per-rep detail is opt-in: the surface stays short, the numbers stay
        // one tap away on the rep count.
        if (repsExpanded && analysis.reps.isNotEmpty()) {
            item { Eyebrow("Each rep") }
            itemsIndexed(analysis.reps) { index, rep -> RepCard(rep, index + 1) }
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

        // The id of the run that produced everything above it. Small, quiet,
        // and the only thing standing between "it gave me the wrong number"
        // and knowing which of hundreds of runs to look at.
        if (analysis.traceId.isNotBlank()) {
            item {
                Text(
                    "run ${analysis.traceId}" +
                        (analysis.provenance?.summary?.let { " · $it" } ?: ""),
                    style = MaterialTheme.typography.labelSmall.merge(Numeric),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 4.dp),
                )
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
private fun SessionHeader(
    analysis: Analysis,
    repsExpanded: Boolean = false,
    onToggleReps: (() -> Unit)? = null,
) {
    val hold = analysis.hold
    Panel {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Eyebrow(analysis.sessionDate.ifBlank { "Session" })
                Spacer(Modifier.height(6.dp))
                Text(
                    hold?.label
                        ?: analysis.detected?.label
                        ?: analysis.exercise.replace('_', ' ').replaceFirstChar { it.uppercase() },
                    style = MaterialTheme.typography.headlineSmall,
                )
                Spacer(Modifier.height(6.dp))
                if (hold != null) {
                    Text(
                        "held still · time is the measurement",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    // The rep count is the handle for the per-rep detail: the
                    // numbers stay off the surface until this is pressed.
                    val base = "${analysis.repCount} rep${if (analysis.repCount == 1) "" else "s"} measured" +
                        if (analysis.candidateCount > analysis.repCount)
                            " of ${analysis.candidateCount} found" else ""
                    Text(
                        base,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    // The toggle is its own line. Appended to the count it
                    // wrapped on a 390dp phone and left the tappable half
                    // orphaned on a second line, which read as a typo rather
                    // than as a control.
                    if (onToggleReps != null) {
                        Text(
                            if (repsExpanded) "Hide each rep" else "Show each rep",
                            style = MaterialTheme.typography.labelLarge,
                            color = MaterialTheme.colorScheme.primary,
                            modifier = Modifier
                                .clickable(onClick = onToggleReps)
                                .padding(top = 4.dp),
                        )
                    }
                }
            }
            if (hold != null) {
                HoldClock(hold.seconds)
            } else {
                ScoreRing(
                    score = analysis.sessionScore,
                    band = analysis.sessionBand,
                    diameter = 76.dp,
                    caption = "session",
                )
            }
        }

        analysis.detected?.takeIf { hold == null }?.let { d ->
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
                (if (hold != null) "Held %.1fs–%.1fs of a %.1fs clip." else "Trimmed to %.1fs–%.1fs of a %.1fs clip.")
                    .format(t.startS, t.endS, analysis.durationS),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/** Seconds held, large, counting up to the value the way the score ring
 *  sweeps up to its score. No ring, because there is no scale: a hold is not
 *  out of anything. */
@Composable
private fun HoldClock(seconds: Double) {
    val shown by animateFloatAsState(
        targetValue = seconds.toFloat(),
        animationSpec = tween(700),
        label = "held",
    )
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Row(verticalAlignment = Alignment.Bottom) {
            Text(
                shown.toInt().toString(),
                fontFamily = FontFamily.Monospace,
                fontWeight = FontWeight.SemiBold,
                style = MaterialTheme.typography.displaySmall,
                color = MaterialTheme.colorScheme.primary,
            )
            Text(
                "s",
                fontFamily = FontFamily.Monospace,
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.primary,
                modifier = Modifier.padding(bottom = 4.dp, start = 2.dp),
            )
        }
        Text(
            "held",
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun HoldCard(hold: Hold) {
    Panel {
        Eyebrow("What it saw")
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Pill(
                if (hold.certain) "recognised" else "uncertain",
                color = if (hold.certain) MaterialTheme.colorScheme.primary
                else MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                "${(hold.confidence * 100).toInt()}% confident",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Spacer(Modifier.height(8.dp))
        Text(
            hold.reason.replaceFirstChar { it.uppercase() } + ".",
            style = MaterialTheme.typography.bodyMedium,
        )
        if (!hold.certain && hold.runnerUp != null) {
            Spacer(Modifier.height(6.dp))
            Text(
                "Could also be a ${hold.runnerUp.replace('_', ' ')}.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Spacer(Modifier.height(10.dp))
        Text(
            "Time held is the measurement. How straight the line was is an angle in " +
                "the image, and a few degrees of camera position move that more than " +
                "technique does - so it is not scored.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/**
 * What the movement is for, quoted. Every line here came from an openly
 * licensed source and says which one; none of it is a measurement, and the
 * card is careful to keep the two apart - the measured faults sit in the
 * Improve panel above, in the app's own words.
 */
@Composable
fun TechniqueCard(t: Technique) {
    var open by remember { mutableStateOf(false) }
    Panel {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Eyebrow("About the ${t.name.lowercase()}")
                Spacer(Modifier.height(4.dp))
                Text(
                    "Cues and common faults, quoted from open sources. Not measured here.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            TextButton(onClick = { open = !open }) { Text(if (open) "Less" else "Read") }
        }
        AnimatedVisibility(open) {
            Column {
                if (t.cues.isNotEmpty()) {
                    Spacer(Modifier.height(8.dp))
                    Eyebrow("Cues")
                    t.cues.forEach {
                        Text("· $it", style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier.padding(vertical = 3.dp))
                    }
                }
                if (t.faults.isNotEmpty()) {
                    Spacer(Modifier.height(8.dp))
                    Eyebrow("Faults to avoid")
                    t.faults.forEach {
                        Text("· $it", style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier.padding(vertical = 3.dp))
                    }
                }
                if (t.muscles.isNotEmpty()) {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "Works: " + t.muscles.joinToString(", "),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Spacer(Modifier.height(8.dp))
                Text(
                    "Source: " + t.attribution +
                        t.sources.firstOrNull()?.let { " · ${it.title}" }.orEmpty(),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
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
