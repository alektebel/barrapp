package com.barrapp.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.barrapp.ui.theme.Nocturne
import com.barrapp.ui.theme.N

/** Appendix B — the week is the home page. Values are the design's literals;
 *  the real app feeds its own tally through the parameters. */
@Composable
fun WeekScreen(
    reps: Int,
    measuredDays: Int,
    delta: String,
    bars: List<WeekBar>,
    unlockTitle: String,
    unlockCount: String,
    unlockNote: String,
    unlockProgress: Float,
    onOpenLadder: () -> Unit,
    lastSession: LastSessionCard?,
    onOpenSession: () -> Unit,
    onOpenCoach: () -> Unit,
) {
    Column(Modifier.fillMaxWidth()) {
        androidx.compose.material3.Text("THIS WEEK", style = N.eyebrowAccent,
            modifier = Modifier.padding(bottom = 8.dp))

        Row(verticalAlignment = Alignment.Bottom) {
            androidx.compose.material3.Text("$reps", style = N.bigNumber)
            Spacer(Modifier.width(8.dp))
            androidx.compose.material3.Text(
                "reps measured\nacross $measuredDays days",
                style = N.caption, modifier = Modifier.padding(bottom = 6.dp),
            )
            Spacer(Modifier.weight(1f))
            androidx.compose.material3.Text(
                delta,
                style = N.chip,
                modifier = Modifier
                    .padding(bottom = 8.dp)
                    .border(1.dp, Nocturne.accent, RoundedCornerShape(6.dp))
                    .padding(horizontal = 9.dp, vertical = 5.dp),
            )
        }

        Row(
            Modifier.fillMaxWidth().padding(top = 18.dp).height(92.dp),
            horizontalArrangement = Arrangement.spacedBy(7.dp),
        ) {
            bars.forEach { bar ->
                Column(
                    Modifier.weight(1f).fillMaxWidth().height(92.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Bottom,
                ) {
                    WeekBarView(bar, Modifier.fillMaxWidth())
                    Spacer(Modifier.height(6.dp))
                    androidx.compose.material3.Text(bar.letter, style = N.dayLetter)
                }
            }
        }

        // FlowRow, not Row: four labels plus their dots cannot fit one line on
        // a narrow phone or at a large font scale, and a Row would push the
        // last one off the edge instead of wrapping it.
        @OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
        androidx.compose.foundation.layout.FlowRow(
            Modifier.fillMaxWidth().padding(top = 10.dp),
            horizontalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            LegendDot(Nocturne.strong, "strong")
            LegendDot(Nocturne.solid, "solid")
            LegendDot(Nocturne.shaky, "shaky")
            LegendDot(null, "nothing measured")
        }

        NocturneDivider(Modifier.padding(vertical = 20.dp))

        // Next unlock — the whole card is the tap target for the ladder
        Column(
            Modifier.fillMaxWidth()
                .background(Nocturne.surface, RoundedCornerShape(8.dp))
                .border(1.dp, Nocturne.hairline, RoundedCornerShape(8.dp))
                .padding(14.dp)
                .then(NoRipple.noRipple(onOpenLadder)),
        ) {
            Row(verticalAlignment = Alignment.Bottom) {
                androidx.compose.material3.Text("NEXT UNLOCK", style = N.eyebrowAccent)
                Spacer(Modifier.weight(1f))
                androidx.compose.material3.Text(unlockCount, style = N.chip
                    .copy(color = Nocturne.fgA(0.5f)))
            }
            androidx.compose.material3.Text(unlockTitle, style = N.cardTitle,
                modifier = Modifier.padding(top = 8.dp))
            androidx.compose.material3.Text(unlockNote, style = N.cardBody,
                modifier = Modifier.padding(top = 3.dp))
            Box(
                Modifier.fillMaxWidth().padding(top = 12.dp).height(5.dp)
                    .background(Nocturne.dim, RoundedCornerShape(3.dp)),
            ) {
                Box(
                    Modifier.fillMaxWidth(unlockProgress).height(5.dp)
                        .background(Nocturne.accent, RoundedCornerShape(3.dp)),
                )
            }
        }

        androidx.compose.material3.Text("LAST SESSION", style = N.eyebrowMuted,
            modifier = Modifier.padding(top = 20.dp, bottom = 9.dp))

        if (lastSession != null) {
            Row(
                Modifier.fillMaxWidth()
                    .background(Nocturne.surface, RoundedCornerShape(8.dp))
                    .border(1.dp, Nocturne.hairline, RoundedCornerShape(8.dp))
                    .padding(14.dp)
                    .then(NoRipple.noRipple(onOpenSession)),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(Modifier.size(56.dp), contentAlignment = Alignment.Center) {
                    Canvas(Modifier.size(56.dp)) {
                        // r25, stroke 5, track dim, arc solid by fraction,
                        // rotate(-90) -> start at -90 degrees
                        drawArc(Color(0xFF292B31), -90f, 360f, false,
                            style = Stroke(5f, cap = StrokeCap.Round))
                        drawArc(lastSession.ringColor, -90f,
                            360f * lastSession.ringFraction, false,
                            style = Stroke(5f, cap = StrokeCap.Round))
                    }
                    androidx.compose.material3.Text(
                        "${lastSession.score}",
                        style = N.ringNumber.copy(color = lastSession.ringColor),
                    )
                }
                Spacer(Modifier.width(14.dp))
                Column(Modifier.weight(1f)) {
                    androidx.compose.material3.Text(lastSession.title, style = N.logo)
                    androidx.compose.material3.Text(lastSession.note, style = N.cardBody,
                        modifier = Modifier.padding(top = 4.dp))
                    androidx.compose.material3.Text(lastSession.meta, style = N.sessionMeta
                        .copy(color = Nocturne.fgA(0.4f)), modifier = Modifier.padding(top = 7.dp))
                }
            }
        }

        Row(
            Modifier.fillMaxWidth().padding(top = 11.dp)
                .border(1.dp, Nocturne.fgA(0.16f), RoundedCornerShape(8.dp))
                .padding(horizontal = 14.dp, vertical = 12.dp)
                .then(NoRipple.noRipple(onOpenCoach)),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            androidx.compose.material3.Text(
                "Ask what the week actually shows", style = N.question,
                modifier = Modifier.weight(1f),
            )
            androidx.compose.material3.Text("→", style = N.button
                .copy(color = Nocturne.accent))
        }
    }
}

/** One day bar. A rep either measured (a fill), filmed-but-nothing (dashed
 *  outline), or not trained (a stub). */
data class WeekBar(
    val letter: String,
    val fillFraction: Float?,      // null = the 4px stub
    val color: Color?,             // null fillFraction -> ignored
    val dashed: Boolean = false,
)

@Composable
private fun WeekBarView(bar: WeekBar, modifier: Modifier) {
    // The bar lives in a 92dp column with the day label below it. A bar drawn
    // to the full 92dp, plus the 6dp spacer and the label, overflowed the
    // column and drew over the label - so the tallest bar is capped to leave
    // room for the letter underneath.
    val maxBar = 72.dp
    val height = when {
        bar.fillFraction == null -> 4.dp
        bar.dashed -> (maxBar * bar.fillFraction)
        else -> (maxBar * bar.fillFraction).coerceAtLeast(4.dp)
    }
    Box(modifier.height(height)) {
        if (bar.dashed) {
            Canvas(Modifier.fillMaxWidth().height(height)) {
                drawRoundRect(
                    color = Color.Transparent,
                    cornerRadius = androidx.compose.ui.geometry.CornerRadius(4.dp.toPx()),
                    style = Stroke(
                        width = 1.dp.toPx(),
                        pathEffect = androidx.compose.ui.graphics.PathEffect
                            .dashPathEffect(floatArrayOf(6f, 4f)),
                    ),
                    topLeft = Offset(0.5f, 0.5f),
                    size = Size0(size.width - 1f, size.height - 1f),
                )
            }
        } else {
            Box(
                Modifier.fillMaxWidth().height(height)
                    .background(bar.color ?: Nocturne.hairline, RoundedCornerShape(4.dp)),
            )
        }
    }
}

private fun Size0(w: Float, h: Float) = androidx.compose.ui.geometry.Size(w, h)

@Composable
private fun LegendDot(color: Color?, label: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(7.dp)) {
            if (color != null) {
                Box(Modifier.fillMaxWidth().height(7.dp)
                    .background(color, RoundedCornerShape(2.dp)))
            } else {
                Canvas(Modifier.fillMaxWidth().height(7.dp)) {
                    drawRoundRect(
                        color = Nocturne.nothing,
                        cornerRadius = androidx.compose.ui.geometry.CornerRadius(2.dp.toPx()),
                        style = Stroke(1.dp.toPx(), pathEffect =
                            androidx.compose.ui.graphics.PathEffect.dashPathEffect(floatArrayOf(4f, 3f))),
                    )
                }
            }
        }
        Spacer(Modifier.width(5.dp))
        androidx.compose.material3.Text(label, style = N.legend)
    }
}

/** The design's divider: a hairline that fades at both ends. The stops are
 *  expressed as fractions of the width (48px on a 356dp content width). */
@Composable
fun NocturneDivider(modifier: Modifier = Modifier) {
    Box(
        modifier.fillMaxWidth().height(1.dp)
            .background(
                androidx.compose.ui.graphics.Brush.horizontalGradient(
                    0f to Color.Transparent,
                    0.13f to Nocturne.fgA(0.16f),
                    0.87f to Nocturne.fgA(0.16f),
                    1f to Color.Transparent,
                ),
            ),
    )
}

object NoRipple {
    /** The design shows no pressed state, so clicks carry no indication. */
    fun noRipple(action: () -> Unit): Modifier = Modifier.clickable(
        interactionSource = MutableInteractionSource(),
        indication = null,
        onClick = action,
    )
}

data class LastSessionCard(
    val title: String,
    val note: String,
    val meta: String,
    val score: Int,
    val ringFraction: Float,
    val ringColor: Color,
)
