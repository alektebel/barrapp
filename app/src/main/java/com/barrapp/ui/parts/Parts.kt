package com.barrapp.ui.parts

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.barrapp.ui.theme.LocalBandColors

/** The colour for a quality band. Kept in one place so a band never renders in
 *  two different colours in two different panes. */
@Composable
fun bandColor(band: String): Color {
    val c = LocalBandColors.current
    return when (band) {
        "strong" -> c.strong
        "solid" -> c.solid
        "shaky" -> c.shaky
        "broken down", "broken" -> c.broken
        else -> c.unmeasured
    }
}

/**
 * A score as a ring.
 *
 * An unmeasured rep draws an open dashed ring and an em dash rather than a
 * zero. A pose failure is not a bad rep, and drawing it as one would be the
 * most misleading thing this screen could do.
 */
@Composable
fun ScoreRing(
    score: Int?,
    band: String,
    modifier: Modifier = Modifier,
    diameter: Dp = 64.dp,
    caption: String? = null,
) {
    val colour = bandColor(band)
    val target = (score ?: 0) / 100f
    val sweep by animateFloatAsState(
        targetValue = target,
        animationSpec = tween(700),
        label = "score",
    )
    val track = MaterialTheme.colorScheme.outline
    Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = modifier) {
        Box(Modifier.size(diameter), contentAlignment = Alignment.Center) {
            Canvas(Modifier.size(diameter)) {
                val stroke = size.minDimension * 0.10f
                val inset = stroke / 2f
                val arcSize = Size(size.width - stroke, size.height - stroke)
                drawArc(
                    color = track.copy(alpha = 0.45f),
                    startAngle = -90f, sweepAngle = 360f, useCenter = false,
                    topLeft = Offset(inset, inset), size = arcSize,
                    style = Stroke(width = stroke, cap = StrokeCap.Round),
                )
                if (score != null) {
                    drawArc(
                        color = colour,
                        startAngle = -90f, sweepAngle = 360f * sweep, useCenter = false,
                        topLeft = Offset(inset, inset), size = arcSize,
                        style = Stroke(width = stroke, cap = StrokeCap.Round),
                    )
                }
            }
            Text(
                text = score?.toString() ?: "—",
                fontFamily = FontFamily.Monospace,
                fontWeight = FontWeight.SemiBold,
                fontSize = (diameter.value * 0.30f).sp,
                color = if (score == null) MaterialTheme.colorScheme.onSurfaceVariant else colour,
            )
        }
        if (caption != null) {
            Text(
                caption,
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = 6.dp),
            )
        }
    }
}

/**
 * The rep's own trace: shoulder height relative to the bar, through the rep.
 *
 * This is the single most informative thing the app can draw, because the shape
 * carries what a number cannot - a clean arc versus a grind with a stall
 * halfway up. The dashed line is the bar.
 */
@Composable
fun RepTrace(
    points: List<Float>,
    band: String,
    modifier: Modifier = Modifier,
    height: Dp = 56.dp,
    showBarLine: Boolean = true,
) {
    if (points.size < 3) return
    val colour = bandColor(band)
    val rule = MaterialTheme.colorScheme.outline
    Canvas(modifier.fillMaxWidth().height(height)) {
        // DrawScope works in PIXELS, not dp. A literal here is a third of its
        // apparent weight on a 3x-density phone, which turns every line in this
        // app into a hairline. DrawScope is a Density, so convert.
        val hair = 1.dp.toPx()
        val line = 2.dp.toPx()
        val dashOn = 4.dp.toPx()
        val dashGap = 3.dp.toPx()
        val lo = points.min()
        val hi = points.max()
        val span = (hi - lo).takeIf { it > 1e-4f } ?: 1f
        val pad = size.height * 0.12f
        fun y(v: Float) = size.height - pad - (v - lo) / span * (size.height - 2 * pad)
        fun x(i: Int) = i.toFloat() / (points.size - 1) * size.width

        if (showBarLine && lo < 0f && hi > 0f) {
            val zero = y(0f)
            var cursor = 0f
            while (cursor < size.width) {
                drawLine(
                    color = rule,
                    start = Offset(cursor, zero),
                    end = Offset(minOf(cursor + dashOn, size.width), zero),
                    strokeWidth = hair,
                )
                cursor += dashOn + dashGap
            }
        }
        val path = Path().apply {
            moveTo(x(0), y(points[0]))
            for (i in 1 until points.size) lineTo(x(i), y(points[i]))
        }
        drawPath(path, colour, style = Stroke(width = line, cap = StrokeCap.Round))
    }
}

/** Small all-caps label. Used for the robustness classes and for section
 *  eyebrows, where the letter-spacing does the work of a divider. */
@Composable
fun Eyebrow(text: String, modifier: Modifier = Modifier, color: Color? = null) {
    Text(
        text.uppercase(),
        style = MaterialTheme.typography.labelMedium,
        color = color ?: MaterialTheme.colorScheme.primary,
        modifier = modifier,
    )
}

/** A bordered pill. Outline rather than fill, so several can sit together
 *  without the row turning into a stack of coloured blocks. */
@Composable
fun Pill(
    text: String,
    modifier: Modifier = Modifier,
    color: Color? = null,
) {
    val c = color ?: MaterialTheme.colorScheme.onSurfaceVariant
    Box(
        modifier
            .clip(RoundedCornerShape(6.dp))
            .background(c.copy(alpha = 0.10f))
            .border(1.dp, c.copy(alpha = 0.55f), RoundedCornerShape(6.dp))
            .padding(horizontal = 9.dp, vertical = 4.dp)
    ) {
        Text(text, style = MaterialTheme.typography.labelSmall, color = c)
    }
}

/** The app's one card. Everything sits on this so surfaces stay consistent. */
@Composable
fun Panel(
    modifier: Modifier = Modifier,
    padding: PaddingValues = PaddingValues(18.dp),
    content: @Composable () -> Unit,
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(14.dp),
        color = MaterialTheme.colorScheme.surface,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline.copy(alpha = 0.6f)),
    ) {
        Column(Modifier.padding(padding)) { content() }
    }
}

/** A labelled horizontal bar, 0..1. Used for the score components. */
@Composable
fun ComponentBar(
    label: String,
    value: Double?,
    why: String,
    weight: Double,
    modifier: Modifier = Modifier,
) {
    val colour = MaterialTheme.colorScheme.primary
    val track = MaterialTheme.colorScheme.outline
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.Bottom,
        ) {
            Text(
                label.replaceFirstChar { it.uppercase() },
                style = MaterialTheme.typography.titleSmall,
            )
            Text(
                value?.let { "${(it * 100).toInt()}%" } ?: "—",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Canvas(Modifier.fillMaxWidth().height(5.dp)) {
            val r = size.height / 2
            drawRoundRect(
                color = track.copy(alpha = 0.4f),
                cornerRadius = CornerRadius(r, r),
            )
            if (value != null && value > 0.0) {
                drawRoundRect(
                    color = colour,
                    size = Size(size.width * value.toFloat().coerceIn(0f, 1f), size.height),
                    cornerRadius = CornerRadius(r, r),
                )
            }
        }
        Text(
            why,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            "weight ${(weight * 100).toInt()}%",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
        )
    }
}
