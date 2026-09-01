package com.barrapp.ui

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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.barrapp.Progression
import com.barrapp.data.DayEntry
import com.barrapp.ui.parts.Eyebrow
import com.barrapp.ui.parts.Panel
import com.barrapp.ui.parts.Pill
import com.barrapp.ui.parts.bandColor
import kotlin.math.abs

/**
 * Progress, and the two honest ways to show it.
 *
 * The headline is **reps you can actually measure per session**, not the score.
 * That is deliberate and it is the most useful number this app has: the whole
 * measurement rests on having enough clean reps in a session to tell your
 * rep-to-rep variation from a real change, and until that count is up, no
 * comparison between sessions means anything. It is also the number entirely
 * within your control - it is a filming and volume decision, not a strength one.
 *
 * The score trend is shown underneath, greyed until there is enough behind it,
 * with the gap to the floor stated in plain words rather than implied by a
 * flat line.
 */
@Composable
fun InsightPane(
    days: List<DayEntry>,
    repTarget: Int,
    weeklyNote: String?,
    onOpenCoach: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val measured = days.filter { it.measured }.sortedBy { it.date }
    val readySessions = days.count { it.reps >= MIN_REPS_FOR_COMPARISON }
    val progression = Progression.focus(days)

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        // The progression verdict goes first because it is the decision the
        // athlete came for. Everything below it is supporting evidence.
        if (progression?.step != null) {
            item { ProgressionCard(progression) }
        }

        item {
            Panel {
                Eyebrow("Sessions you can compare")
                Spacer(Modifier.height(10.dp))
                Row(verticalAlignment = Alignment.Bottom) {
                    Text(
                        readySessions.toString(),
                        fontFamily = FontFamily.Monospace,
                        fontWeight = FontWeight.SemiBold,
                        style = MaterialTheme.typography.displaySmall,
                        color = MaterialTheme.colorScheme.primary,
                    )
                    Spacer(Modifier.size(8.dp))
                    Text(
                        "of ${days.size} recorded",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(bottom = 5.dp),
                    )
                }
                Spacer(Modifier.height(10.dp))
                Text(
                    if (readySessions >= 2)
                        "Two sessions of $MIN_REPS_FOR_COMPARISON or more reps is what it " +
                            "takes to tell a real change from your ordinary rep-to-rep " +
                            "variation. You have that."
                    else
                        "A session needs $MIN_REPS_FOR_COMPARISON measured reps before its " +
                            "median means anything, and two such sessions before anything " +
                            "can be compared. Aim for $repTarget reps in one set.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (days.isNotEmpty()) {
                    Spacer(Modifier.height(16.dp))
                    RepsPerSession(days.sortedBy { it.date }, repTarget)
                }
            }
        }

        item {
            Panel {
                Eyebrow("Session score")
                Spacer(Modifier.height(4.dp))
                if (measured.size < 2) {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "Two measured sessions before a line here means anything.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    val first = measured.first().score ?: 0
                    val last = measured.last().score ?: 0
                    val delta = last - first
                    Spacer(Modifier.height(10.dp))
                    Row(verticalAlignment = Alignment.Bottom) {
                        Text(
                            last.toString(),
                            fontFamily = FontFamily.Monospace,
                            fontWeight = FontWeight.SemiBold,
                            style = MaterialTheme.typography.displaySmall,
                            color = bandColor(measured.last().band),
                        )
                        Spacer(Modifier.size(10.dp))
                        Pill(
                            if (delta == 0) "level"
                            else "${if (delta > 0) "+" else "−"}${abs(delta)} since ${measured.first().date.takeLast(5)}",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Spacer(Modifier.height(14.dp))
                    ScoreTrend(measured)
                    Spacer(Modifier.height(12.dp))
                    Text(
                        "A baseline proxy from range, descent control and stalls. It is not " +
                            "a technique grade, and a difference this size has not been " +
                            "tested against your own variation.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        item {
            Panel {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Eyebrow("Weekly review", modifier = Modifier.weight(1f))
                    if (weeklyNote != null) {
                        Box(
                            Modifier.size(7.dp).clip(CircleShape)
                                .background(MaterialTheme.colorScheme.primary)
                        )
                    }
                }
                Spacer(Modifier.height(10.dp))
                Text(
                    weeklyNote ?: "Your first weekly review lands once there is a week of " +
                        "training behind it. You will get a notification.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (weeklyNote != null) MaterialTheme.colorScheme.onSurface
                    else MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(16.dp))
                HorizontalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f))
                Spacer(Modifier.height(14.dp))
                FilledTonalButton(onClick = onOpenCoach, modifier = Modifier.fillMaxWidth()) {
                    Text("Ask about your training")
                }
            }
        }
    }
}

const val MIN_REPS_FOR_COMPARISON = 3

/**
 * Reps per session as bars, with the comparison floor drawn across them.
 *
 * The floor line is the point: a bar under it is a session that cannot take
 * part in any comparison, and seeing three of those in a row says more than a
 * paragraph would.
 */
@Composable
private fun RepsPerSession(days: List<DayEntry>, target: Int) {
    val shown = days.takeLast(12)
    if (shown.isEmpty()) return
    val ceiling = maxOf(shown.maxOf { it.reps }, target, MIN_REPS_FOR_COMPARISON) + 1
    val primary = MaterialTheme.colorScheme.primary
    val outline = MaterialTheme.colorScheme.outline
    val dim = MaterialTheme.colorScheme.onSurfaceVariant

    Column {
        Canvas(Modifier.fillMaxWidth().height(76.dp)) {
            // Pixels, not dp - see RepTrace in parts/Parts.kt.
            val hair = 1.dp.toPx()
            val dashOn = 3.dp.toPx()
            val dashGap = 4.dp.toPx()
            val radius = 3.dp.toPx()
            val minBar = 3.dp.toPx()
            val slot = size.width / shown.size
            val barW = minOf(slot * 0.55f, 18.dp.toPx())
            val floorY = size.height - (MIN_REPS_FOR_COMPARISON.toFloat() / ceiling) * size.height

            var x = 0f
            while (x < size.width) {
                drawLine(
                    color = dim.copy(alpha = 0.55f),
                    start = Offset(x, floorY),
                    end = Offset(minOf(x + dashOn, size.width), floorY),
                    strokeWidth = hair,
                )
                x += dashOn + dashGap
            }
            shown.forEachIndexed { i, day ->
                // A minimum height for any non-zero session. One high-volume day
                // otherwise flattens a 1-rep day to nothing, and "I did one rep"
                // and "I did none" are the two facts this chart exists to
                // separate. The scale stays linear - a bar chart that bends its
                // axis to look tidy is lying about the ratio it is drawing.
                val raw = (day.reps.toFloat() / ceiling) * size.height
                val h = if (day.reps > 0) maxOf(raw, minBar) else 0f
                val left = i * slot + (slot - barW) / 2f
                drawRoundRect(
                    color = if (day.reps >= MIN_REPS_FOR_COMPARISON) primary
                    else outline,
                    topLeft = Offset(left, size.height - h),
                    size = Size(barW, h),
                    cornerRadius = CornerRadius(radius, radius),
                )
            }
        }
        Spacer(Modifier.height(6.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(
                shown.first().date.takeLast(5),
                style = MaterialTheme.typography.labelSmall,
                color = dim,
            )
            Text(
                "floor $MIN_REPS_FOR_COMPARISON reps",
                style = MaterialTheme.typography.labelSmall,
                color = dim,
            )
            Text(
                shown.last().date.takeLast(5),
                style = MaterialTheme.typography.labelSmall,
                color = dim,
            )
        }
    }
}

/** Score over the measured sessions, with each session as a point. Points and
 *  not just a line, so the sample size cannot be mistaken for a smooth trend. */
@Composable
private fun ScoreTrend(measured: List<DayEntry>) {
    val colour = MaterialTheme.colorScheme.primary
    val dim = MaterialTheme.colorScheme.outline
    Canvas(Modifier.fillMaxWidth().height(72.dp)) {
        // Pixels, not dp - see RepTrace in parts/Parts.kt.
        val hair = 1.dp.toPx()
        val line = 2.dp.toPx()
        val dot = 3.dp.toPx()
        val edge = 6.dp.toPx()
        val scores = measured.map { (it.score ?: 0).toFloat() }
        val lo = minOf(scores.min() - 6f, 100f)
        val hi = maxOf(scores.max() + 6f, lo + 1f)
        val pad = edge
        fun y(v: Float) = size.height - pad - (v - lo) / (hi - lo) * (size.height - 2 * pad)
        fun x(i: Int) =
            if (scores.size == 1) size.width / 2f
            else i.toFloat() / (scores.size - 1) * (size.width - 2 * edge) + edge

        drawLine(
            color = dim.copy(alpha = 0.5f),
            start = Offset(0f, size.height - pad),
            end = Offset(size.width, size.height - pad),
            strokeWidth = hair,
        )
        val path = Path().apply {
            moveTo(x(0), y(scores[0]))
            for (i in 1 until scores.size) lineTo(x(i), y(scores[i]))
        }
        drawPath(path, colour, style = Stroke(width = line, cap = StrokeCap.Round))
        scores.forEachIndexed { i, v ->
            drawCircle(colour, radius = dot, center = Offset(x(i), y(v)))
        }
    }
}


/**
 * The progression verdict.
 *
 * Structured so the parts cannot be confused with each other, because that
 * distinction is the product: the **standard** is a published convention, the
 * **evidence** is measured, and only the evidence carries a trace. An app that
 * blurs the two is asking to be believed rather than checked.
 */
@Composable
private fun ProgressionCard(v: Progression.Verdict) {
    val step = v.step ?: return
    Panel {
        Eyebrow(if (v.ready) "Earned" else "Working towards")
        Spacer(Modifier.height(8.dp))
        Text(
            step.towardsLabel,
            style = MaterialTheme.typography.headlineMedium,
            color = if (v.ready) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.onSurface,
        )
        Spacer(Modifier.height(4.dp))
        Text(
            "from ${v.label.lowercase()}",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        Spacer(Modifier.height(14.dp))
        Row(verticalAlignment = Alignment.Bottom) {
            Text(
                v.bestReps.toString(),
                fontFamily = FontFamily.Monospace,
                fontWeight = FontWeight.SemiBold,
                style = MaterialTheme.typography.displaySmall,
                color = if (v.bestReps >= step.reps) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.onSurface,
            )
            Spacer(Modifier.size(8.dp))
            Text(
                "of ${step.reps} verified reps",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(bottom = 5.dp),
            )
        }
        Spacer(Modifier.height(4.dp))
        Text(
            "Verified means barra measured the rep - not that you performed it. " +
                "A rep it could not measure is not counted either way.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        Spacer(Modifier.height(14.dp))
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        Spacer(Modifier.height(12.dp))

        Eyebrow("The standard")
        Spacer(Modifier.height(6.dp))
        Text(v.standard, style = MaterialTheme.typography.bodyMedium)
        Spacer(Modifier.height(4.dp))
        Text(
            "A convention, not a measurement. It is written down so you can " +
                "disagree with it.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        Spacer(Modifier.height(12.dp))
        Eyebrow("Your evidence")
        Spacer(Modifier.height(6.dp))
        Text(v.evidence, style = MaterialTheme.typography.bodyMedium)

        if (v.missing.isNotBlank()) {
            Spacer(Modifier.height(10.dp))
            Text(
                v.missing,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.primary,
            )
        }
        if (v.ready && !step.targetMeasurable) {
            Spacer(Modifier.height(10.dp))
            Text(
                step.note,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
