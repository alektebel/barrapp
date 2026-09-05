package com.barrapp.ui.parts

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.sin

/**
 * The barra figure: a stick athlete doing the one movement the app is named
 * after, over a bar, with its own shoulder trace scrolling underneath.
 *
 * This is the loading animation, and it is not decoration. Each stage of an
 * upload changes what the drawing does, in the terms the pipeline actually
 * works in:
 *
 *   0  uploading      the figure works; nothing is measured yet
 *   1  finding        the hands are bracketed - they are the reference point
 *                     everything else is measured against
 *   2  trimming       the trace appears, faint, with trim markers sliding in
 *                     from either edge to the working set
 *   3  measuring      the trace turns live and each lockout is marked and
 *                     counted, the way the segmenter counts them
 *  -1  idle           the figure alone, slower. Used by the empty state.
 *
 * The geometry is the same the web preview used to check it, and it is
 * fractions of the box rather than pixels, so it holds its shape at any size.
 * Every stroke is converted through dp - see RepTrace for why.
 */
@Composable
fun BarraFigure(
    stage: Int,
    modifier: Modifier = Modifier,
    width: Dp = 220.dp,
    height: Dp = 260.dp,
    periodMs: Int = 1800,
) {
    // The bottom third of the box is the trace lane. Idle, there is no trace,
    // so the figure gets the whole box instead of hanging above an empty one.
    val boxHeight = if (stage < 0) height * 0.72f else height
    val transition = rememberInfiniteTransition(label = "figure")
    val phase by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(if (stage < 0) periodMs * 2 else periodMs, easing = LinearEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = "phase",
    )
    val primary = MaterialTheme.colorScheme.primary
    val ink = MaterialTheme.colorScheme.onSurface
    val rule = MaterialTheme.colorScheme.outline
    val history = remember(phase, stage) { traceHistory(phase, if (stage < 0) 0 else 60) }
    val peaks = remember(history) { countPeaks(history) }

    Box(modifier.width(width).height(boxHeight)) {
        Canvas(Modifier.fillMaxSize()) {
            drawFigure(phase, stage, history, primary, ink, rule)
        }
        if (stage >= 3) {
            Text(
                peaks.toString(),
                style = MaterialTheme.typography.labelMedium,
                color = ink,
                modifier = Modifier
                    .align(Alignment.BottomEnd)
                    .padding(end = width * 0.12f, bottom = boxHeight * 0.36f),
            )
        }
    }
}

/** Shoulder height above the bar for the last `n` samples, ending now.
 *  In the unit box's own terms: -arm at the hang, +clearance at lockout. */
internal fun traceHistory(phase: Float, n: Int, arm: Float = 0.24f, clearance: Float = 0.10f): List<Float> {
    if (n <= 0) return emptyList()
    return List(n) { i ->
        val p = phase - (n - 1 - i) * 0.05f
        val r = sin(PI * p).toFloat().let { it * it }
        -arm + r * (arm + clearance)
    }
}

/** Lockouts in the history: a local maximum above the bar. This is the same
 *  rule of thumb the real segmenter starts from - a peak clear of the rest. */
internal fun countPeaks(h: List<Float>): Int {
    var n = 0
    for (i in 1 until h.size - 1) {
        if (h[i] > h[i - 1] && h[i] >= h[i + 1] && h[i] > 0f) n++
    }
    return n
}

private fun DrawScope.drawFigure(
    phase: Float,
    stage: Int,
    history: List<Float>,
    primary: Color,
    ink: Color,
    rule: Color,
) {
    val w = size.width
    val h = size.height
    // Pixels, not dp, inside a Canvas.
    val hair = 1.dp.toPx()
    val thin = 1.5.dp.toPx()
    val line = 2.dp.toPx()
    val limb = 2.5.dp.toPx()
    val heavy = 3.dp.toPx()

    // ---- geometry, as fractions of the box ------------------------------
    val barY = 0.22f * h
    val cx = 0.5f * w
    val grip = 0.10f * w
    val arm = 0.24f * h
    val torso = 0.22f * h
    val clearance = 0.10f * h
    val r = sin(PI * phase).toFloat().let { it * it }           // 0 hang .. 1 lockout
    val sway = 0.02f * w * sin(2 * PI * phase).toFloat()
    val shY = barY + arm - r * (arm + clearance)
    val shX = cx + sway
    val hipX = shX + 0.5f * sway
    val hipY = shY + torso
    val kneeX = hipX + 0.01f * w + 0.03f * w * r
    val kneeY = hipY + 0.14f * h
    val ankX = kneeX + 0.005f * w
    val ankY = kneeY + 0.13f * h - 0.02f * h * r
    val headR = 0.045f * h
    val headY = shY - 0.075f * h
    val handL = Offset(cx - grip, barY)
    val handR = Offset(cx + grip, barY)
    val shL = Offset(shX - 0.035f * w, shY)
    val shR = Offset(shX + 0.035f * w, shY)

    fun elbow(hand: Offset, sh: Offset, side: Float): Offset {
        val len = hypot(sh.x - hand.x, sh.y - hand.y)
        val flex = max(0f, 1f - len / arm)                      // 0 straight .. 1 folded
        return Offset((hand.x + sh.x) / 2 + side * 0.07f * w * flex,
            (hand.y + sh.y) / 2 + 0.02f * h * flex)
    }
    val eL = elbow(handL, shL, -1f)
    val eR = elbow(handR, shR, +1f)

    // ---- the bar --------------------------------------------------------
    drawLine(ink, Offset(0.12f * w, barY), Offset(0.88f * w, barY), heavy, StrokeCap.Round)
    for (x in floatArrayOf(0.16f, 0.84f)) {
        drawLine(rule, Offset(x * w, barY), Offset(x * w, barY + 0.05f * h), line, StrokeCap.Round)
    }

    // ---- the figure -----------------------------------------------------
    fun seg(a: Offset, b: Offset) = drawLine(primary, a, b, limb, StrokeCap.Round)
    seg(handL, eL); seg(eL, shL); seg(handR, eR); seg(eR, shR)
    seg(shL, shR)
    seg(Offset(shX, shY), Offset(hipX, hipY))
    seg(Offset(hipX, hipY), Offset(kneeX, kneeY)); seg(Offset(kneeX, kneeY), Offset(ankX, ankY))
    drawCircle(primary, headR, Offset(shX, headY))

    // ---- stage 1: the hands are the reference. Bracket them. ----------
    if (stage == 1) {
        val b = 0.035f * w
        val a = 0.6f + 0.4f * sin(4 * PI * phase).toFloat()
        for (hand in listOf(handL, handR)) {
            drawRect(
                primary.copy(alpha = a.coerceIn(0.2f, 1f)),
                topLeft = Offset(hand.x - b, hand.y - b),
                size = Size(2 * b, 2 * b),
                style = Stroke(width = thin),
            )
        }
    }

    // ---- the trace: shoulder height above the bar, over time -------------
    val tTop = 0.66f * h
    val tBot = 0.94f * h
    val x0 = 0.12f * w
    val x1 = 0.88f * w
    val zero = tTop + (tBot - tTop) * (clearance / (arm + clearance))   // bar level
    // The dashed line is the bar, *as a reference for the trace*. Drawn before
    // the trace exists it is a rule under nothing - which is what the empty
    // state and the first two stages showed: a dashed line floating in space,
    // measuring air. It arrives with the thing it measures.
    if (stage >= 2) {
        drawLine(
            rule, Offset(x0, zero), Offset(x1, zero), hair, StrokeCap.Round,
            pathEffect = PathEffect.dashPathEffect(floatArrayOf(4.dp.toPx(), 3.dp.toPx())),
        )
    }
    if (stage >= 2 && history.size > 2) {
        val path = Path()
        history.forEachIndexed { i, v ->
            val x = x0 + (x1 - x0) * i / (history.size - 1)
            val y = zero - v / (0.24f + 0.10f) * (tBot - tTop)
            if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
        }
        drawPath(path, if (stage >= 3) primary else rule, style = Stroke(width = line, cap = StrokeCap.Round))
    }
    // ---- stage 2: trim markers slide in from the edges --------------------
    if (stage == 2) {
        val t = 0.5f - 0.5f * cos(2 * PI * phase).toFloat()
        val inset = 0.14f * (x1 - x0) * t
        for (x in floatArrayOf(x0 + inset, x1 - inset)) {
            drawLine(primary, Offset(x, tTop - 4.dp.toPx()), Offset(x, tBot + 4.dp.toPx()), thin, StrokeCap.Round)
        }
    }
    // ---- stage 3: mark each lockout ---------------------------------------
    if (stage >= 3 && history.size > 2) {
        for (i in 1 until history.size - 1) {
            val v = history[i]
            if (v > history[i - 1] && v >= history[i + 1] && v > 0f) {
                val x = x0 + (x1 - x0) * i / (history.size - 1)
                val y = zero - v / (0.24f + 0.10f) * (tBot - tTop)
                drawCircle(primary, 3.dp.toPx(), Offset(x, y))
            }
        }
    }
}

/**
 * The bottom bar's glyphs, drawn rather than picked from the icon set. The
 * icon set's closest matches were a calendar, a house and an information
 * mark, and "progress" is not information. These say what each pane holds:
 * a month of dots, a bar with someone on it, a line going the right way.
 */
@Composable
fun NavGlyph(kind: String, selected: Boolean, modifier: Modifier = Modifier) {
    val colour = if (selected) MaterialTheme.colorScheme.onSurface
    else MaterialTheme.colorScheme.onSurfaceVariant
    Canvas(modifier.width(22.dp).height(22.dp)) {
        val s = size.minDimension
        val line = 1.8.dp.toPx()
        when (kind) {
            "calendar" -> {
                // a month: three rows of dots, one of them filled
                for (row in 0 until 3) for (col in 0 until 4) {
                    val c = Offset(s * (0.18f + col * 0.213f), s * (0.28f + row * 0.24f))
                    val filled = (row == 1 && col == 2) || (row == 2 && col == 0)
                    if (filled) drawCircle(colour, s * 0.075f, c)
                    else drawCircle(colour.copy(alpha = 0.55f), s * 0.05f, c)
                }
            }
            "session" -> {
                // the bar, and a head above it
                drawLine(colour, Offset(s * 0.1f, s * 0.42f), Offset(s * 0.9f, s * 0.42f), line, StrokeCap.Round)
                drawCircle(colour, s * 0.11f, Offset(s * 0.5f, s * 0.24f))
                drawLine(colour, Offset(s * 0.5f, s * 0.42f), Offset(s * 0.5f, s * 0.86f), line, StrokeCap.Round)
                drawLine(colour, Offset(s * 0.33f, s * 0.42f), Offset(s * 0.4f, s * 0.58f), line, StrokeCap.Round)
                drawLine(colour, Offset(s * 0.67f, s * 0.42f), Offset(s * 0.6f, s * 0.58f), line, StrokeCap.Round)
            }
            else -> {
                // progress: a line that has to earn its slope
                val p = Path().apply {
                    moveTo(s * 0.12f, s * 0.78f)
                    lineTo(s * 0.36f, s * 0.6f)
                    lineTo(s * 0.55f, s * 0.68f)
                    lineTo(s * 0.88f, s * 0.26f)
                }
                drawPath(p, colour, style = Stroke(width = line, cap = StrokeCap.Round))
                drawCircle(colour, s * 0.07f, Offset(s * 0.88f, s * 0.26f))
            }
        }
    }
}
