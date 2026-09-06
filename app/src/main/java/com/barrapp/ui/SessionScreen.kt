package com.barrapp.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import com.barrapp.ui.theme.Nocturne
import com.barrapp.ui.theme.N
import com.barrapp.ui.theme.nocturne

/** Appendix E — the verdict is the page: one word, the cost in a line, two
 *  things to carry, and the reps behind it. */
@Composable
fun SessionScreen(
    eyebrow: String,
    verdict: String,
    subtitle: String,
    score: Int?,
    scoreBand: String,
    bandColor: Color,
    cues: List<String>,
    onWatchReplay: (() -> Unit)?,
    reps: List<RepCardData>,
    runLine: String,
    onBackToWeek: () -> Unit,
    repsOpen: Boolean,
    onToggleReps: () -> Unit,
) {
    Column {
        androidx.compose.material3.Text("← Week", style = N.back,
            modifier = Modifier.padding(bottom = 14.dp)
                .then(NoRipple.noRipple(onBackToWeek)))

        androidx.compose.material3.Text(eyebrow.uppercase(), style = N.eyebrowMuted)

        Row(Modifier.fillMaxWidth().padding(top = 12.dp)) {
            Column(Modifier.weight(1f)) {
                androidx.compose.material3.Text(verdict, style = N.verdict)
                androidx.compose.material3.Text(subtitle, style = N.cardBody,
                    modifier = Modifier.padding(top = 9.dp))
            }
            Spacer(Modifier.width(16.dp))
            Box(Modifier.size(80.dp), contentAlignment = Alignment.Center) {
                Canvas(Modifier.size(80.dp)) {
                    drawArc(Color(0xFF292B31), -90f, 360f, false,
                        style = Stroke(7f, cap = StrokeCap.Round))
                    if (score != null) {
                        drawArc(bandColor, -90f, 360f * score / 100f, false,
                            style = Stroke(7f, cap = StrokeCap.Round))
                    }
                }
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    androidx.compose.material3.Text(
                        score?.toString() ?: "—",
                        style = N.ringBig.copy(color = if (score != null) bandColor
                            else Nocturne.fgA(0.4f)),
                    )
                    androidx.compose.material3.Text(scoreBand.uppercase(), style = N.ringLabel,
                        modifier = Modifier.padding(top = 3.dp))
                }
            }
        }

        Column(
            Modifier.fillMaxWidth().padding(top = 18.dp)
                .background(Nocturne.surface, RoundedCornerShape(8.dp))
                .border(1.dp, Nocturne.hairline, RoundedCornerShape(8.dp))
                .padding(14.dp),
        ) {
            androidx.compose.material3.Text(
                "TWO THINGS TO CARRY INTO THE NEXT SET", style = N.eyebrowAccent)
            cues.take(2).forEachIndexed { i, cue ->
                Row(Modifier.fillMaxWidth().padding(top = if (i == 0) 12.dp else 10.dp)) {
                    androidx.compose.material3.Text(
                        "0${i + 1}", style = N.cueNumber,
                        modifier = Modifier.width(24.dp),
                    )
                    androidx.compose.material3.Text(cue, style = N.cue,
                        modifier = Modifier.weight(1f))
                }
            }
        }

        Row(Modifier.fillMaxWidth().padding(top = 11.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            val shape = RoundedCornerShape(8.dp)
            Box(
                Modifier.weight(1f)
                    .border(1.dp, Nocturne.accent, shape)
                    .padding(vertical = 10.dp)
                    .then(
                        if (onWatchReplay != null) NoRipple.noRipple(onWatchReplay)
                        else Modifier
                    ),
                contentAlignment = Alignment.Center,
            ) {
                androidx.compose.material3.Text("Watch the replay", style = N.button
                    .copy(color = Nocturne.accentText))
            }
            Box(
                Modifier.weight(1f)
                    .border(1.dp, Nocturne.fgA(0.16f), shape)
                    .padding(vertical = 10.dp)
                    .then(NoRipple.noRipple(onToggleReps)),
                contentAlignment = Alignment.Center,
            ) {
                androidx.compose.material3.Text("Each rep", style = N.button
                    .copy(color = Nocturne.fg))
            }
        }

        if (repsOpen) {
            Column(Modifier.fillMaxWidth().padding(top = 14.dp)) {
                reps.forEachIndexed { i, rep ->
                    RepCard(rep, modifier = if (i == 0) Modifier
                        else Modifier.padding(top = 9.dp))
                }
                androidx.compose.material3.Text(runLine, style = N.runLine,
                    modifier = Modifier.padding(top = 12.dp))
            }
        }
    }
}

@Composable
private fun RepCard(rep: RepCardData, modifier: Modifier) {
    val shape = RoundedCornerShape(8.dp)
    Column(
        modifier.fillMaxWidth()
            .background(Nocturne.surface, shape)
            .border(1.dp, Nocturne.hairline, shape)
            .padding(14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            androidx.compose.material3.Text(rep.title, style = N.repTitle)
            Spacer(Modifier.width(10.dp))
            Box(
                Modifier.background(
                    rep.chipColor.copy(alpha = 0.16f), RoundedCornerShape(6.dp),
                ).padding(horizontal = 8.dp, vertical = 3.dp),
            ) {
                androidx.compose.material3.Text(rep.chip, style = nocturne(500, 10, 1f)
                    .copy(color = rep.chipColor))
            }
            Spacer(Modifier.weight(1f))
            androidx.compose.material3.Text(
                rep.score ?: "—", style = N.repScore.copy(
                    color = rep.scoreColor ?: Nocturne.fgA(0.4f),
                ),
            )
        }

        if (rep.measured) {
            androidx.compose.material3.Text(rep.times, style = N.repTimes,
                modifier = Modifier.padding(top = 6.dp))

            RepTrace(rep.trace, rep.traceColor, Modifier.fillMaxWidth()
                .padding(top = 10.dp).height(54.dp))

            Column(Modifier.fillMaxWidth().padding(top = 12.dp),
                verticalArrangement = Arrangement.spacedBy(9.dp)) {
                rep.components.forEach { c ->
                    Column {
                        Row(Modifier.fillMaxWidth()) {
                            androidx.compose.material3.Text(c.name, style = N.barLabel)
                            androidx.compose.material3.Text(" ·${c.weightPct}%",
                                style = N.barWeight)
                            Spacer(Modifier.weight(1f))
                            androidx.compose.material3.Text("${c.value}%", style = N.barValue)
                        }
                        Box(Modifier.fillMaxWidth().padding(top = 5.dp).height(4.dp)
                            .background(Nocturne.dim, RoundedCornerShape(2.dp))) {
                            Box(Modifier.fillMaxWidth(c.value / 100f).height(4.dp)
                                .background(Nocturne.accent, RoundedCornerShape(2.dp)))
                        }
                    }
                }
            }

            if (rep.asides.isNotEmpty()) {
                Box(Modifier.fillMaxWidth().padding(vertical = 12.dp).height(1.dp)
                    .background(Nocturne.fgA(0.1f)))
                androidx.compose.material3.Text("MEASURED, NOT SCORED", style = N.eyebrowMuted)
                rep.asides.forEach { a ->
                    Row(Modifier.fillMaxWidth().padding(top = 6.dp)) {
                        androidx.compose.material3.Text(a.first, style = N.asideRow,
                            modifier = Modifier.weight(1f))
                        androidx.compose.material3.Text(a.second, style = N.asideValue)
                    }
                }
            }
        } else {
            androidx.compose.material3.Text(rep.note, style = N.cardBody,
                modifier = Modifier.padding(top = 8.dp))
        }
    }
}

data class RepComponent(val name: String, val weightPct: Int, val value: Int)

data class RepCardData(
    val title: String,
    val chip: String,
    val chipColor: Color,
    val score: String?,
    val scoreColor: Color?,
    val measured: Boolean,
    val times: String = "",
    val trace: List<Float> = emptyList(),       // 0..1, bottom-up
    val traceColor: Color = Nocturne.solid,
    val components: List<RepComponent> = emptyList(),
    val asides: List<Pair<String, String>> = emptyList(),
    val note: String = "",
)

/** The rep's own trace, over the design's dashed rest line (y=33 of 54). */
@Composable
fun RepTrace(values: List<Float>, color: Color, modifier: Modifier) {
    Canvas(modifier) {
        val w = 300f
        val h = 54f
        val sx = size.width / w
        val sy = size.height / h
        drawLine(Nocturne.hairline, Offset(0f, 33f * sy), Offset(size.width, 33f * sy),
            1f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(4f * sx, 3f * sy)))
        if (values.size >= 2) {
            val path = Path()
            values.forEachIndexed { i, v ->
                val x = i / (values.size - 1f) * size.width
                val y = (47f - v.coerceIn(0f, 1f) * 38f) * sy
                if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
            }
            drawPath(path, color, style = Stroke(2f * sx, cap = StrokeCap.Round))
        }
    }
}
