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
import androidx.compose.ui.graphics.Brush
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
import kotlin.math.sin

/**
 * The barra figure: an athlete doing the movement the app is named after, over
 * a bar, with the shoulder trace scrolling underneath in the same frame.
 *
 * This is the loading animation, and it is not decoration. Each stage of an
 * upload changes what the drawing does, in the terms the pipeline works in:
 *
 *   0  uploading      the figure works; nothing is measured yet
 *   1  finding        the hands are bracketed - they are the reference point
 *                     everything else is measured against
 *   2  trimming       the trace appears, faint, with trim markers sliding in
 *                     from either edge to the working set
 *   3  measuring      the trace fills and each lockout is ringed and counted,
 *                     the way the segmenter counts them
 *  -1  idle           the figure alone, slower, no trace lane. The empty state.
 *
 * ## Why it is a pull-up
 *
 * The first version had the shoulders finish above the bar, which is a
 * muscle-up and is the movement this project cares most about. It also could
 * not be drawn: with the hands fixed on the bar and the shoulders above them,
 * the arms splay outward and the figure reads as a scarecrow standing on a
 * wire. A pull-up keeps the shoulders below the bar for the whole cycle, so
 * the arms always run from a wide hand up to a narrower shoulder and every
 * frame of the loop reads as a person hanging.
 *
 * ## What makes it look drawn rather than plotted
 *
 * Limbs taper - thicker at the shoulder than at the wrist - and the joints are
 * round, so the body has weight. The elbow interpolates between two *positions*
 * (almost on the line at the hang, tucked below the hand at the top) rather
 * than being pushed sideways off the midpoint, which is what stopped the arms
 * and the bar closing into a coat-hanger trapezoid. The bar is drawn behind the
 * body with a short cap over each hand, because a bar drawn in front crosses
 * the head at the top of every rep, where the chin is above it by definition.
 *
 * Every dimension is a fraction of the box, so it holds its shape at any size,
 * and every stroke converts through dp - see RepTrace for why that matters.
 *
 * Checked frame by frame in `tools/replica.html` before it was written here.
 */
@Composable
fun BarraFigure(
    stage: Int,
    modifier: Modifier = Modifier,
    width: Dp = 220.dp,
    height: Dp = 260.dp,
    periodMs: Int = 2200,
) {
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
    val surface = MaterialTheme.colorScheme.surface
    val history = remember(phase, stage) { traceHistory(phase, if (stage < 0) 0 else TRACE_POINTS) }
    val peaks = remember(history) { countPeaks(history) }

    Box(modifier.width(width).height(height)) {
        Canvas(Modifier.fillMaxSize()) {
            drawFigure(phase, stage, history, primary, ink, rule, surface)
        }
        if (stage >= 3) {
            Text(
                "$peaks ${if (peaks == 1) "REP" else "REPS"}",
                style = MaterialTheme.typography.labelMedium,
                color = ink,
                modifier = Modifier
                    .align(Alignment.BottomEnd)
                    .padding(end = width * 0.10f, bottom = height * 0.285f),
            )
        }
    }
}

/** How many samples of the trace are kept on screen. */
internal const val TRACE_POINTS = 64

/**
 * Shoulder height relative to the bar for the last `n` samples, ending now.
 * -1 at the hang, +0.19 at the top of the pull, so the curve crosses its own
 * bar line the way a real rep's does.
 */
internal fun traceHistory(phase: Float, n: Int): List<Float> {
    if (n <= 0) return emptyList()
    return List(n) { i ->
        val p = phase - (n - 1 - i) * 0.042f
        val r = sin(PI * p).toFloat().let { it * it }
        -1f + 1.19f * r
    }
}

/** Lockouts in the history: a local maximum above the bar. The same rule of
 *  thumb the real segmenter starts from - a peak clear of the rest. */
internal fun countPeaks(h: List<Float>): Int {
    var n = 0
    for (i in 1 until h.size - 1) {
        if (h[i] > h[i - 1] && h[i] >= h[i + 1] && h[i] > 0f) n++
    }
    return n
}

/** Every joint of one frame, in pixels. */
private class Pose(w: Float, h: Float, phase: Float) {
    val barY = 0.20f * h
    val grip = 0.086f * w
    val armLong = 0.155f * h
    val armShort = 0.052f * h
    val r = sin(PI * phase).toFloat().let { it * it }        // 0 hang .. 1 chin over
    private val sway = 0.012f * w * sin(2 * PI * phase).toFloat()
    val reach = armLong - r * (armLong - armShort)
    val shX = 0.5f * w + sway
    val shY = barY + reach
    val hipX = shX + 0.7f * sway
    val hipY = shY + 0.135f * h
    // Legs hang: near vertical, converging slightly, with only a small forward
    // drift as the body rises. More travel than this and it marches in mid-air.
    private val kneeX = hipX + 0.018f * w * r
    private val kneeY = hipY + 0.088f * h
    private val ankX = kneeX + 0.012f * w * r
    private val ankY = kneeY + 0.078f * h

    val handL = Offset(0.5f * w - grip, barY)
    val handR = Offset(0.5f * w + grip, barY)
    val shL = Offset(shX - 0.050f * w, shY)
    val shR = Offset(shX + 0.050f * w, shY)
    val hipL = Offset(hipX - 0.030f * w, hipY)
    val hipR = Offset(hipX + 0.030f * w, hipY)
    val kneeL = Offset(kneeX - 0.022f * w, kneeY)
    val kneeR = Offset(kneeX + 0.022f * w, kneeY)
    val ankL = Offset(ankX - 0.015f * w, ankY)
    val ankR = Offset(ankX + 0.015f * w, ankY)
    val headR = 0.040f * h
    val head = Offset(shX, shY - 0.080f * h)
    val neck = Offset(shX, shY - 0.020f * h)
    val shoulder = Offset(shX, shY)
    val hip = Offset(hipX, hipY)

    /** Almost on the line at the hang, tucked below the hand at the top. */
    fun elbow(hand: Offset, sh: Offset, side: Float, w: Float, h: Float): Offset {
        val flex = (armLong - reach) / (armLong - armShort)
        val sx = (hand.x + sh.x) / 2f + side * 0.012f * w
        val sy = (hand.y + sh.y) / 2f
        val tx = hand.x + side * 0.016f * w
        val ty = sh.y + 0.072f * h
        return Offset(sx + (tx - sx) * flex, sy + (ty - sy) * flex)
    }
}

/** A limb: a stroke that tapers from `w0` at `a` to `w1` at `b`, with round
 *  joints. A constant-width line reads as a diagram; this reads as a body. */
private fun DrawScope.limb(a: Offset, b: Offset, w0: Float, w1: Float, colour: Color) {
    val dx = b.x - a.x
    val dy = b.y - a.y
    val len = hypot(dx, dy).takeIf { it > 1e-3f } ?: 1f
    val nx = -dy / len
    val ny = dx / len
    val path = Path().apply {
        moveTo(a.x + nx * w0 / 2f, a.y + ny * w0 / 2f)
        lineTo(b.x + nx * w1 / 2f, b.y + ny * w1 / 2f)
        lineTo(b.x - nx * w1 / 2f, b.y - ny * w1 / 2f)
        lineTo(a.x - nx * w0 / 2f, a.y - ny * w0 / 2f)
        close()
    }
    drawPath(path, colour)
    drawCircle(colour, w0 / 2f, a)
    drawCircle(colour, w1 / 2f, b)
}

/** One whole body at `phase`. Drawn far side first, so it has a front and a
 *  back rather than reading flat. */
private fun DrawScope.body(phase: Float, figureHeight: Float, colour: Color, alpha: Float): Pose {
    val w = size.width
    val h = figureHeight
    val p = Pose(w, h, phase)
    val c = colour.copy(alpha = alpha)
    val eL = p.elbow(p.handL, p.shL, -1f, w, h)
    val eR = p.elbow(p.handR, p.shR, +1f, w, h)
    val u = 0.016f * h
    limb(p.handR, eR, u * 0.65f, u * 0.82f, c)
    limb(eR, p.shR, u * 0.82f, u * 0.92f, c)
    limb(p.hipR, p.kneeR, u * 0.92f, u * 0.78f, c)
    limb(p.kneeR, p.ankR, u * 0.78f, u * 0.52f, c)
    limb(p.shoulder, p.hip, u * 1.40f, u * 1.02f, c)
    limb(p.shL, p.shR, u * 0.92f, u * 0.92f, c)
    limb(p.hipL, p.hipR, u * 0.95f, u * 0.95f, c)
    limb(p.handL, eL, u * 0.75f, u * 0.95f, c)
    limb(eL, p.shL, u * 0.95f, u * 1.05f, c)
    limb(p.hipL, p.kneeL, u * 1.02f, u * 0.86f, c)
    limb(p.kneeL, p.ankL, u * 0.86f, u * 0.58f, c)
    limb(p.shoulder, p.neck, u * 0.82f, u * 0.72f, c)
    drawCircle(c, p.headR, p.head)
    return p
}

private fun DrawScope.drawFigure(
    phase: Float,
    stage: Int,
    history: List<Float>,
    primary: Color,
    ink: Color,
    rule: Color,
    surface: Color,
) {
    val w = size.width
    val h = size.height
    // The body is laid out against a reference height rather than the box. With
    // a trace lane the body uses the top two thirds and the lane the rest; with
    // no lane (idle) the same proportions are scaled up to fill the box, which
    // is why the idle figure is not a squashed copy of the working one.
    val fh = if (stage < 0) h / 0.66f else h
    // Pixels, not dp, inside a Canvas.
    val hair = 1.dp.toPx()
    val thin = 1.5.dp.toPx()
    val line = 2.dp.toPx()
    val bar = 3.5.dp.toPx()

    // ---- the bar goes BEHIND the body ------------------------------------
    val p0 = Pose(w, fh, phase)
    drawLine(ink, Offset(0.09f * w, p0.barY), Offset(0.91f * w, p0.barY), bar, StrokeCap.Round)
    for (x in floatArrayOf(0.12f, 0.88f)) {
        drawLine(rule, Offset(x * w, p0.barY), Offset(x * w, p0.barY + 0.042f * fh),
            2.5.dp.toPx(), StrokeCap.Round)
    }

    // ---- one motion ghost, so a still frame reads as movement ------------
    if (stage >= 0) body(phase - 0.045f, fh, primary, 0.18f)
    val p = body(phase, fh, primary, 1f)

    // A short cap of bar over each hand, so the hands read as gripping it.
    for (hand in listOf(p.handL, p.handR)) {
        drawLine(ink, Offset(hand.x - 0.022f * w, p.barY), Offset(hand.x + 0.022f * w, p.barY),
            bar, StrokeCap.Round)
    }

    // ---- the hands are the reference. Always marked, loud while finding. --
    val strong = stage == 1
    val pulse = if (strong) 0.55f + 0.45f * sin(4 * PI * phase).toFloat() else 0.32f
    val markC = primary.copy(alpha = pulse.coerceIn(0.2f, 1f))
    val markW = if (strong) thin else 1.2.dp.toPx()
    val b = if (strong) 0.030f * w else 0.024f * w
    for (hand in listOf(p.handL, p.handR)) {
        val k = b * 0.55f
        // Corner brackets, not a box: they frame without boxing in.
        for (sx in floatArrayOf(-1f, 1f)) for (sy in floatArrayOf(-1f, 1f)) {
            drawLine(markC, Offset(hand.x + sx * b, hand.y + sy * b - sy * k),
                Offset(hand.x + sx * b, hand.y + sy * b), markW, StrokeCap.Round)
            drawLine(markC, Offset(hand.x + sx * b, hand.y + sy * b),
                Offset(hand.x + sx * b - sx * k, hand.y + sy * b), markW, StrokeCap.Round)
        }
    }

    // ---- the trace, in the same frame -------------------------------------
    if (stage < 2 || history.size <= 2) return
    val tTop = 0.70f * h
    val tBot = 0.955f * h
    val x0 = 0.10f * w
    val x1 = 0.90f * w
    val zero = tTop + (tBot - tTop) * 0.16f                  // the bar
    fun px(i: Int) = x0 + (x1 - x0) * i / (history.size - 1)
    fun py(v: Float) = zero - v * 0.84f * (tBot - tTop)

    drawLine(
        rule, Offset(x0, zero), Offset(x1, zero), hair, StrokeCap.Round,
        pathEffect = PathEffect.dashPathEffect(floatArrayOf(3.dp.toPx(), 3.dp.toPx())),
    )
    if (stage >= 3) {
        // A soft fill under the curve: it reads as a measurement, not a doodle.
        val fill = Path().apply {
            moveTo(px(0), tBot)
            history.forEachIndexed { i, v -> lineTo(px(i), py(v)) }
            lineTo(px(history.size - 1), tBot)
            close()
        }
        drawPath(
            fill,
            Brush.verticalGradient(
                listOf(primary.copy(alpha = 0.30f), primary.copy(alpha = 0f)),
                startY = tTop, endY = tBot,
            ),
        )
    }
    val curve = Path().apply {
        history.forEachIndexed { i, v -> if (i == 0) moveTo(px(i), py(v)) else lineTo(px(i), py(v)) }
    }
    drawPath(curve, if (stage >= 3) primary else rule,
        style = Stroke(width = line, cap = StrokeCap.Round))

    if (stage == 2) {
        val t = 0.5f - 0.5f * cos(2 * PI * phase).toFloat()
        val inset = 0.16f * (x1 - x0) * t
        for (x in floatArrayOf(x0 + inset, x1 - inset)) {
            drawLine(primary, Offset(x, tTop - 3.dp.toPx()), Offset(x, tBot + 3.dp.toPx()),
                thin, StrokeCap.Round)
            drawCircle(primary, 2.2.dp.toPx(), Offset(x, tTop - 6.dp.toPx()))
        }
    }
    if (stage >= 3) {
        for (i in 1 until history.size - 1) {
            val v = history[i]
            if (v > history[i - 1] && v >= history[i + 1] && v > 0f) {
                val x = px(i)
                val y = py(v)
                drawLine(primary.copy(alpha = 0.35f), Offset(x, y), Offset(x, zero), hair)
                drawCircle(surface, 3.6.dp.toPx(), Offset(x, y))
                drawCircle(primary, 3.6.dp.toPx(), Offset(x, y), style = Stroke(width = line))
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
