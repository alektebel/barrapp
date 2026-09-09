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
    Column(Modifier.fillMaxWidth()) {
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

/** One choice the athlete can make about the set. `value` is what the server
 *  receives; blank means "not declared", which is always the first option. */
data class Declaration(val label: String, val value: String, val note: String = "")

val STANDARDS = listOf(
    Declaration("Not declared", "", "checks that depend on it are marked, not assumed"),
    Declaration("Strict", "strict", "no swing, no kip - the bar work judged to the strict standard"),
    Declaration("Kipping", "kipping", "swing is allowed; only the strict-only checks are dropped"),
)

val CAMERA_SIDES = listOf(
    Declaration("Not sure", "", "the pipeline estimates the angle from the pose"),
    Declaration("Side-on", "SAGITTAL", "the best angle for hip line and lockout"),
    Declaration("Front-on", "FRONTAL", "needed for knee-in and elbow flare; hides hip sag"),
    Declaration("Diagonal", "OBLIQUE", "between the two; some checks will be withheld"),
)

/**
 * Before the clip is picked: what the athlete declares about the set.
 *
 * Two facts the pipeline refuses to guess - the technique standard and where
 * the camera stood. Both default to "not declared", which is always an
 * honest answer; a wrong declaration is worse than none, so the copy under
 * each option says what it changes. The choice is sent with the job and
 * comes back on the session page as the standard the checks were judged to.
 */
@Composable
fun DeclareScreen(
    standard: String,
    camera: String,
    onStandard: (String) -> Unit,
    onCamera: (String) -> Unit,
    onPick: () -> Unit,
    onBackToWeek: () -> Unit,
) {
    Column(Modifier.fillMaxWidth()) {
        androidx.compose.material3.Text("← Week", style = N.back,
            modifier = Modifier.padding(bottom = 14.dp)
                .then(NoRipple.noRipple(onBackToWeek)))

        androidx.compose.material3.Text("Before the clip", style = N.pageTitle)
        androidx.compose.material3.Text(
            "Two things Barra will not guess. Leave them as they are if you " +
                "are not sure - a check that cannot be made is reported as such, " +
                "never as a pass.",
            style = N.bodyNote, modifier = Modifier.padding(top = 6.dp),
        )

        DeclarationGroup("STANDARD", STANDARDS, standard, onStandard)
        DeclarationGroup("CAMERA", CAMERA_SIDES, camera, onCamera)

        Box(
            Modifier.fillMaxWidth().padding(top = 22.dp)
                .background(Nocturne.accent, RoundedCornerShape(8.dp))
                .padding(vertical = 12.dp)
                .then(NoRipple.noRipple(onPick)),
            contentAlignment = Alignment.Center,
        ) {
            androidx.compose.material3.Text("Pick the clip",
                style = N.button.copy(color = Nocturne.background))
        }
    }
}

@Composable
private fun DeclarationGroup(
    title: String,
    options: List<Declaration>,
    selected: String,
    onSelect: (String) -> Unit,
) {
    androidx.compose.material3.Text(title, style = N.eyebrowMuted,
        modifier = Modifier.padding(top = 22.dp, bottom = 4.dp))
    options.forEach { o ->
        val on = o.value == selected
        val shape = RoundedCornerShape(8.dp)
        Row(
            Modifier.fillMaxWidth().padding(top = 6.dp)
                .background(if (on) Nocturne.surface else Nocturne.background, shape)
                .border(1.dp, if (on) Nocturne.accent else Nocturne.hairline, shape)
                .padding(horizontal = 12.dp, vertical = 10.dp)
                .then(NoRipple.noRipple { onSelect(o.value) }),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Canvas(Modifier.size(10.dp)) {
                if (on) drawCircle(Nocturne.accent, 5f)
                else drawCircle(Nocturne.nothing, 5f, style = Stroke(2f))
            }
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                androidx.compose.material3.Text(o.label, style = N.stageTitle.copy(
                    color = if (on) Nocturne.accentText else Nocturne.fg))
                if (o.note.isNotBlank()) {
                    androidx.compose.material3.Text(o.note, style = N.stageSub)
                }
            }
        }
    }
}
