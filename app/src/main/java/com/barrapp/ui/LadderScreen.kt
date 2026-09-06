package com.barrapp.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import com.barrapp.ui.theme.Nocturne
import com.barrapp.ui.theme.N
import com.barrapp.ui.theme.nocturne

/** Appendix D — the ladder. A step opens when the standard is met with
 *  verified reps; the spine runs accent down to the fold of the ladder, then
 *  hairline. Dots glow while a step is earned. */
@Composable
fun LadderScreen(steps: List<LadderStep>) {
    Column {
        androidx.compose.material3.Text("Your ladder", style = N.pageTitle)
        androidx.compose.material3.Text(
            "A step opens when the standard is met with verified reps. The standard " +
                "is a written convention — argue with it if you like. Measurement is " +
                "the part that isn't up for debate.",
            style = N.bodyNote, modifier = Modifier.padding(top = 6.dp),
        )

        Box(Modifier.fillMaxWidth().padding(top = 20.dp)) {
            // the spine, behind everything: 2dp wide at x=9 (left:8px + half width)
            Canvas(Modifier.matchParentSize()) {
                val x = 9.dp.toPx()
                val fold = size.height * 0.46f
                drawLine(Nocturne.accent, Offset(x, 8.dp.toPx()), Offset(x, fold), 2.dp.toPx())
                drawLine(Nocturne.hairline, Offset(x, fold),
                    Offset(x, size.height - 8.dp.toPx()), 2.dp.toPx())
            }

            Column(Modifier.fillMaxWidth()) {
                steps.forEach { step ->
                    Row(Modifier.fillMaxWidth().padding(bottom = 12.dp)) {
                        // the dot column, 26dp, dot at top:15px
                        Box(Modifier.width(26.dp)) {
                            Dot(step.dot, Modifier.padding(top = 15.dp)
                                .align(Alignment.TopStart).offset(x = (-2).dp))
                        }
                        LadderCard(step, Modifier.weight(1f))
                    }
                }
            }
        }
    }
}

@Composable
private fun Dot(kind: LadderDot, modifier: Modifier) {
    Canvas(modifier.size(14.dp)) {
        when (kind) {
            LadderDot.EARNED -> {
                drawCircle(Nocturne.accent.copy(alpha = 0.25f), 7f + 6.dp.toPx())
                drawCircle(Nocturne.background, 7f + 4.dp.toPx())
                drawCircle(Nocturne.accent, 7f)
            }
            LadderDot.CURRENT -> {
                drawCircle(Nocturne.background, 7f + 4.dp.toPx())
                drawCircle(Nocturne.background, 7f)
                drawCircle(Nocturne.accent, 7f, style = Stroke(2.dp.toPx()))
            }
            LadderDot.LOCKED -> {
                drawCircle(Nocturne.background, 7f + 2.dp.toPx())
                drawCircle(Nocturne.background, 7f)
                drawCircle(Nocturne.nothing, 7f, style = Stroke(2.dp.toPx()))
            }
        }
    }
}

@Composable
private fun LadderCard(step: LadderStep, modifier: Modifier) {
    val shape = RoundedCornerShape(8.dp)
    Column(
        modifier
            .then(if (step.ghost) Modifier else Modifier.background(Nocturne.surface, shape))
            .border(1.dp, step.borderColor, shape)
            .padding(if (step.big) 14.dp else 13.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            androidx.compose.material3.Text(
                step.title,
                style = if (step.big) N.stepTitleBig else N.stepTitle,
                modifier = Modifier.weight(1f),
            )
            if (step.count != null) {
                androidx.compose.material3.Text(step.count!!, style = N.stepCount)
            }
            if (step.chip != null) {
                Spacer(Modifier.width(8.dp))
                LadderChip(step.chip!!)
            }
        }
        if (step.progress != null) {
            Box(Modifier.fillMaxWidth().padding(top = 11.dp).height(5.dp)
                .background(Nocturne.dim, RoundedCornerShape(3.dp))) {
                Box(Modifier.fillMaxWidth(step.progress ?: 0f).height(5.dp)
                    .background(Nocturne.accent, RoundedCornerShape(3.dp)))
            }
        }
        step.lines.forEachIndexed { i, line ->
            androidx.compose.material3.Text(
                androidx.compose.ui.text.buildAnnotatedString {
                    if (line.label.isNotBlank()) {
                        withStyle(androidx.compose.ui.text.SpanStyle(
                            fontWeight = FontWeight.Medium, color = Nocturne.fg),
                        ) { append(line.label + " — ") }
                    }
                    append(line.text)
                },
                style = if (line.accent) N.stepCount else N.stepNote,
                modifier = Modifier.padding(top = if (i == 0 && step.progress == null) 5.dp else 6.dp),
            )
        }
    }
}

@Composable
private fun LadderChip(chip: LadderChipKind) {
    val shape = RoundedCornerShape(6.dp)
    val bg = when (chip) {
        LadderChipKind.EARNED -> Nocturne.deep
        LadderChipKind.READY -> Color.Transparent
        LadderChipKind.NOT_MEASURABLE -> Nocturne.dim
    }
    val fg = when (chip) {
        LadderChipKind.EARNED -> Nocturne.onDeep
        LadderChipKind.READY -> Nocturne.accentText
        LadderChipKind.NOT_MEASURABLE -> Nocturne.muted
    }
    val label = when (chip) {
        LadderChipKind.EARNED -> "EARNED"
        LadderChipKind.READY -> "READY NOW"
        LadderChipKind.NOT_MEASURABLE -> "NOT MEASURABLE"
    }
    val m = when (chip) {
        LadderChipKind.READY -> Modifier.background(bg, shape)
            .border(1.dp, Nocturne.accent, shape)
        else -> Modifier.background(bg, shape)
    }
    Box(m.padding(horizontal = 8.dp, vertical = 3.dp)) {
        androidx.compose.material3.Text(label, style = nocturne(500, 10, 1f).copy(color = fg))
    }
}

enum class LadderDot { EARNED, CURRENT, LOCKED }
enum class LadderChipKind { EARNED, READY, NOT_MEASURABLE }

data class LadderLine(val label: String, val text: String, val accent: Boolean = false)

data class LadderStep(
    val title: String,
    val chip: LadderChipKind? = null,
    val count: String? = null,
    val progress: Float? = null,
    val lines: List<LadderLine> = emptyList(),
    val dot: LadderDot = LadderDot.EARNED,
    val borderColor: Color = Nocturne.hairline,
    val big: Boolean = false,
    val ghost: Boolean = false,
)
