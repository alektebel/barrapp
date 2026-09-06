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
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import com.barrapp.ui.theme.Nocturne
import com.barrapp.ui.theme.N

/** Appendix F — the wait is four named stages, never a percentage. */
@Composable
fun UploadScreen(
    stages: List<UploadStage>,   // exactly four, in order; one is active
    activeIndex: Int,
    done: Boolean,
    onSkip: () -> Unit,
    onBackToWeek: () -> Unit,
) {
    Column {
        androidx.compose.material3.Text("← Week", style = N.back,
            modifier = Modifier.padding(bottom = 14.dp)
                .then(NoRipple.noRipple(onBackToWeek)))

        androidx.compose.material3.Text("Measuring your set", style = N.pageTitle)
        androidx.compose.material3.Text(
            "No percentage, because there isn't an honest one. Four named stages " +
                "instead. You can leave — it keeps going.",
            style = N.bodyNote, modifier = Modifier.padding(top = 6.dp),
        )

        Box(Modifier.fillMaxWidth().padding(top = 22.dp)) {
            Canvas(Modifier.matchParentSize()) {
                val x = 7.dp.toPx()
                val top = 10.dp.toPx()
                val bottom = size.height - 10.dp.toPx()
                val fold = top + (bottom - top) * 0.62f
                drawLine(Nocturne.accent, Offset(x, top), Offset(x, fold), 2.dp.toPx())
                drawLine(Nocturne.hairline, Offset(x, fold), Offset(x, bottom), 2.dp.toPx())
            }
            Column(Modifier.fillMaxWidth().padding(start = 26.dp)) {
                stages.forEachIndexed { i, stage ->
                    val active = i == activeIndex && !done
                    val past = i < activeIndex || done
                    Row(Modifier.fillMaxWidth().padding(vertical = 10.dp)) {
                        Box(Modifier.width(26.dp), contentAlignment = Alignment.TopStart) {
                            Canvas(Modifier.size(10.dp)
                                .padding(top = 0.dp)
                                .offset(y = 14.dp)) {
                                when {
                                    past -> drawCircle(Nocturne.accent, 5f)
                                    active -> drawCircle(Nocturne.accent, 5f)
                                    else -> {
                                        drawCircle(Nocturne.background, 5f)
                                        drawCircle(Nocturne.nothing, 5f,
                                            style = Stroke(2f))
                                    }
                                }
                            }
                        }
                        Column(Modifier.weight(1f)) {
                            androidx.compose.material3.Text(
                                stage.title,
                                style = N.stageTitle.copy(
                                    color = if (i == activeIndex && !done) Nocturne.accentText
                                    else Nocturne.fg),
                            )
                            androidx.compose.material3.Text(stage.subtitle,
                                style = N.stageSub)
                        }
                    }
                }
            }
        }

        Box(
            Modifier.fillMaxWidth().padding(top = 20.dp)
                .border(1.dp, Nocturne.fgA(0.16f), RoundedCornerShape(8.dp))
                .padding(vertical = 11.dp)
                .then(NoRipple.noRipple(onSkip)),
            contentAlignment = Alignment.Center,
        ) {
            androidx.compose.material3.Text("Skip ahead to the result", style = N.button)
        }
    }
}

data class UploadStage(val title: String, val subtitle: String)
