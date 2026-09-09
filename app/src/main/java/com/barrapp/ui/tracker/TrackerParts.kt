package com.barrapp.ui.tracker

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.barrapp.ui.theme.T
import com.barrapp.ui.theme.Tk
import com.barrapp.ui.theme.scoreInk

/**
 * The pieces every screen in the redesign is built from.
 *
 * Each one is a Tailwind stack from the design resolved once: `rounded-2xl p-4
 * bg-[#161626] border border-[#2a2a44]` is [TkCard], `h-1.5 rounded-full` over
 * a `#2a2a44` track is [Meter], and the entry animations are the design's own
 * `animate-slide-up` / `animate-badge-pop` keyframes with their cubic-beziers.
 */

/** rounded-2xl */
val CardShape = RoundedCornerShape(16.dp)
/** rounded-xl */
val InnerShape = RoundedCornerShape(12.dp)
/** rounded-lg */
val ChipShape = RoundedCornerShape(8.dp)

fun Modifier.noRipple(onClick: () -> Unit): Modifier = this.clickable(
    interactionSource = MutableInteractionSource(),
    indication = null,
    onClick = onClick,
)

/** The design's one card. `border` carries the accented variant the mission
 *  and summary cards use (`1.5px solid rgba(124,93,250,0.3)`). */
@Composable
fun TkCard(
    modifier: Modifier = Modifier,
    accent: Boolean = false,
    padding: PaddingValues = PaddingValues(16.dp),
    background: Color = Tk.surface,
    content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit,
) {
    Column(
        modifier
            .fillMaxWidth()
            .clip(CardShape)
            .background(background)
            .border(
                if (accent) 1.5.dp else 1.dp,
                if (accent) Tk.primaryA(0.3f) else Tk.border,
                CardShape,
            )
            .padding(padding),
        content = content,
    )
}

/** A mono, uppercase, letter-spaced section label. */
@Composable
fun Eyebrow(
    text: String,
    modifier: Modifier = Modifier,
    style: TextStyle = T.eyebrow,
) = Text(text.uppercase(), style = style, modifier = modifier)

/** `h-1.5 rounded-full` with a `#2a2a44` track, animating from zero the way
 *  the design's `transition-all duration-1000` does. */
@Composable
fun Meter(
    fraction: Float,
    color: Color,
    modifier: Modifier = Modifier,
    height: Dp = 6.dp,
    track: Color = Tk.border,
    animate: Boolean = true,
) {
    var ready by remember { mutableStateOf(!animate) }
    LaunchedEffect(Unit) { ready = true }
    val width by animateFloatAsState(
        targetValue = if (ready) fraction.coerceIn(0f, 1f) else 0f,
        animationSpec = tween(1000),
        label = "meter",
    )
    Box(
        modifier
            .fillMaxWidth()
            .height(height)
            .clip(RoundedCornerShape(height / 2))
            .background(track),
    ) {
        Box(
            Modifier
                .fillMaxWidth(width)
                .fillMaxHeight()
                .clip(RoundedCornerShape(height / 2))
                .background(color),
        )
    }
}

/**
 * The score ring.
 *
 * An unmeasured score draws the track alone and an em dash, never a zero-length
 * arc that would read as "scored zero". A rep the pose model could not read is
 * not a bad rep.
 */
@Composable
fun ScoreRing(
    score: Int?,
    modifier: Modifier = Modifier,
    size: Dp = 52.dp,
    stroke: Dp = 5.dp,
    label: String? = null,
    textStyle: TextStyle? = null,
) {
    var ready by remember { mutableStateOf(false) }
    LaunchedEffect(score) { ready = true }
    val sweep by animateFloatAsState(
        targetValue = if (ready) ((score ?: 0) / 100f).coerceIn(0f, 1f) else 0f,
        animationSpec = tween(1100),
        label = "ring",
    )
    val ink = scoreInk(score)
    Box(modifier.size(size), contentAlignment = Alignment.Center) {
        Canvas(Modifier.size(size)) {
            val w = stroke.toPx()
            val inset = w / 2f
            val arc = Size(this.size.width - w, this.size.height - w)
            drawArc(
                color = Tk.border,
                startAngle = -90f, sweepAngle = 360f, useCenter = false,
                topLeft = Offset(inset, inset), size = arc,
                style = Stroke(w, cap = StrokeCap.Round),
            )
            if (score != null) {
                drawArc(
                    color = ink,
                    startAngle = -90f, sweepAngle = 360f * sweep, useCenter = false,
                    topLeft = Offset(inset, inset), size = arc,
                    style = Stroke(w, cap = StrokeCap.Round),
                )
            }
        }
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                score?.toString() ?: "—",
                style = textStyle ?: com.barrapp.ui.theme.mono(
                    (size.value * 0.21f).toInt().coerceAtLeast(9),
                    0f, ink, androidx.compose.ui.text.font.FontWeight.SemiBold,
                ),
            )
            if (label != null) {
                Text(label, style = T.eyebrowTiny, textAlign = TextAlign.Center)
            }
        }
    }
}

/** The amber fault tag the rep cards wear. */
@Composable
fun FaultChip(text: String, color: Color = Tk.amber, modifier: Modifier = Modifier) {
    Text(
        text,
        style = com.barrapp.ui.theme.body(9, color),
        modifier = modifier
            .clip(RoundedCornerShape(6.dp))
            .background(color.copy(alpha = 0.12f))
            .border(1.dp, color.copy(alpha = 0.2f), RoundedCornerShape(6.dp))
            .padding(horizontal = 6.dp, vertical = 2.dp),
    )
}

/** `bg-gradient-to-br from-[#7c5dfa] to-[#a78bfa]`, the design's primary CTA. */
@Composable
fun TkPrimaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    Box(
        modifier
            .fillMaxWidth()
            .clip(CardShape)
            .background(
                if (enabled) Brush.linearGradient(listOf(Tk.primary, Tk.primaryLight))
                else Brush.linearGradient(listOf(Tk.card, Tk.card))
            )
            .then(if (enabled) Modifier.noRipple(onClick) else Modifier)
            .padding(vertical = 16.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text.uppercase(),
            style = T.button.copy(color = if (enabled) Color.White else Tk.muted),
        )
    }
}

/** The outlined secondary — `bg-[#161626] border-[#2a2a44] text-[#a78bfa]`. */
@Composable
fun TkSecondaryButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    tint: Color = Tk.primaryLight,
    border: Color = Tk.border,
    background: Color = Tk.surface,
) {
    Box(
        modifier
            .fillMaxWidth()
            .clip(CardShape)
            .background(background)
            .border(1.5.dp, border, CardShape)
            .noRipple(onClick)
            .padding(vertical = 14.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(text.uppercase(), style = T.buttonSmall.copy(color = tint))
    }
}

/**
 * `animate-slide-up`: 28px up, 450ms on the design's own
 * `cubic-bezier(0.22,1,0.36,1)`, with the stagger delays it uses to walk a
 * list of cards onto the screen.
 */
@Composable
fun SlideUp(
    delayMillis: Int = 0,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    var shown by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { shown = true }
    val spec = tween<Float>(
        durationMillis = 450,
        delayMillis = delayMillis,
        easing = androidx.compose.animation.core.CubicBezierEasing(0.22f, 1f, 0.36f, 1f),
    )
    val progress by animateFloatAsState(if (shown) 1f else 0f, spec, label = "slideUp")
    Box(
        modifier
            .alpha(progress)
            .padding(top = ((1f - progress) * 14).dp),
    ) { content() }
}

/** `animate-pulse-ring`: the halo behind the record button and the analysing
 *  camera, 2s, scale 1 → 1.12, opacity 0.6 → 0.2. */
@Composable
fun PulseRing(
    modifier: Modifier = Modifier,
    color: Color = Tk.primaryA(0.4f),
    stroke: Dp = 2.dp,
    delayMillis: Int = 0,
) {
    val transition = rememberInfiniteTransition(label = "pulse")
    val t by transition.animateFloat(
        initialValue = 0f, targetValue = 1f,
        animationSpec = infiniteRepeatable(
            tween(2000, delayMillis = delayMillis, easing = LinearEasing),
            RepeatMode.Restart,
        ),
        label = "pulseT",
    )
    // 0 -> 1 -> 0 over the cycle, which is what the keyframes' 0/50/100 do.
    val phase = 1f - kotlin.math.abs(t * 2f - 1f)
    Box(
        modifier
            .scale(1f + 0.12f * phase)
            .alpha(0.6f - 0.4f * phase)
            .border(stroke, color, androidx.compose.foundation.shape.CircleShape),
    )
}

/** A row of stat tiles — the design's `grid-cols-3` summary. */
@Composable
fun StatTiles(
    tiles: List<Triple<String, String, String>>,
    modifier: Modifier = Modifier,
    tint: (Int) -> Color = { Tk.teal },
) {
    Row(modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        tiles.forEachIndexed { i, (value, label, note) ->
            SlideUp(delayMillis = i * 80, modifier = Modifier.weight(1f)) {
                TkCard(padding = PaddingValues(12.dp)) {
                    Text(value, style = T.statValue, textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth())
                    Text(label.uppercase(), style = T.eyebrowTiny, textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth().padding(top = 4.dp))
                    Text(note, style = com.barrapp.ui.theme.mono(8, 0.05f, tint(i)),
                        textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth().padding(top = 2.dp))
                }
            }
        }
    }
}
