package com.barrapp.ui.tracker

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBars
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.barrapp.cueEs
import com.barrapp.data.Analysis
import com.barrapp.data.MeasuredFault
import com.barrapp.faultEs
import com.barrapp.ui.replay.ReplayPlan
import com.barrapp.ui.theme.Tk
import com.barrapp.ui.theme.body
import com.barrapp.ui.theme.display
import com.barrapp.ui.theme.mono
import java.io.File

/**
 * One rep pulled apart (design 2c): your worst rep for a fault, beside your
 * best rep of the same set, frozen on the key frame, with the number that
 * fired and one thing to try in the next series. The comparison is always
 * with yourself — never with anyone else.
 *
 * The frame comes straight from the clip (same [keyFrame] as the fault
 * viewer): the phone has no skeleton, so no angle is drawn over the picture —
 * only the measured value and its goal are stated.
 */

/** One correction, ready to show. Built by [repCorrections]. */
data class RepCorrectionData(
    val rep: Int,           // 1-based
    val bestRep: Int,       // 1-based
    val atS: Double,
    val bestAtS: Double,
    val title: String,      // «BALANCEO» (en mayúsculas)
    val value: String,      // «19°»
    val bestValue: String?, // «5°» — null cuando no hay comparación posible
    val goal: String,       // «OBJETIVO MENOS DE 8°»
    val why: String,        // explicación humana
    val cue: String,        // instrucción para la próxima serie
    val index: Int,         // 0-based dentro de la lista
    val total: Int,
)

/**
 * The corrections of a set: one per distinct measured fault, at most
 * [MAX_SLIDES], worst first (same normalised exceedance the server ranks by).
 *
 * Each one pits the rep that shows the fault worst against the set's best
 * scored rep. When the best rep measured the same fault, its value is the
 * comparison («En la rep 1 eran 5°»); when it did not — or nothing was scored
 * — `bestValue` is null and the screen keeps to the number that did fire
 * rather than inventing a comparison.
 */
fun repCorrections(a: Analysis): List<RepCorrectionData> {
    data class Fired(val repIndex: Int, val fault: MeasuredFault, val excess: Double)
    val keyOf = { f: MeasuredFault -> f.errorId.ifBlank { f.name } }
    val bestIndex = a.reps.withIndex()
        .filter { it.value.score != null }
        .maxByOrNull { it.value.score!! }?.index
    val worst = a.reps.flatMapIndexed { i, rep ->
        rep.faults.filter { it.name.isNotBlank() }.map { Fired(i, it, ReplayPlan.exceedance(it)) }
    }
        .groupBy { keyOf(it.fault) }
        .map { (_, same) -> same.maxBy { it.excess } }
        .sortedByDescending { it.excess }
        .take(MAX_SLIDES)
    return worst.mapIndexed { position, c ->
        val f = c.fault
        val title = faultEs(f.name)
        // A comparison needs a different, scored best rep that measured the
        // same fault; otherwise the number stands on its own.
        val bestFault = bestIndex?.let { b -> a.reps[b].faults.firstOrNull { keyOf(it) == keyOf(f) } }
        val bestRep = if (bestIndex == null || bestIndex == c.repIndex) c.repIndex + 1 else bestIndex + 1
        val bestValue: String? = when {
            bestIndex == null || bestIndex == c.repIndex -> null
            bestFault == null -> null
            else -> bestFault.value?.let { fmtValue(it, bestFault.unit) }
        }
        val bestAt = when {
            bestIndex == null || bestIndex == c.repIndex -> faultMoment(a.reps[c.repIndex], f)
            bestFault != null -> faultMoment(a.reps[bestIndex], bestFault)
            else -> repMoment(a.reps[bestIndex])
        }
        RepCorrectionData(
            rep = c.repIndex + 1,
            bestRep = bestRep,
            atS = faultMoment(a.reps[c.repIndex], f),
            bestAtS = bestAt,
            title = title.uppercase(),
            value = f.value?.let { fmtValue(it, f.unit) } ?: "—",
            bestValue = bestValue,
            goal = goalText(f.threshold, f.comparison, f.unit),
            why = correctionWhy(f, c.repIndex + 1, bestValue, bestRep),
            cue = cueEs(f.name) ?: FALLBACK_CUE,
            index = position,
            total = worst.size,
        )
    }
}

/** The same measured sentence as the viewer, extended with your own best rep when it has one. */
internal fun correctionWhy(
    fault: MeasuredFault,
    rep: Int,
    bestValue: String?,
    bestRep: Int,
): String {
    val base = faultWhy(fault.name, fault.value, fault.threshold, fault.comparison, fault.unit, rep)
    return if (bestValue != null) "$base En tu mejor rep (la $bestRep) se midió $bestValue." else base
}

/**
 * The correction screen. [onBack] leaves it; [onNext] walks to the next
 * correction (null on the last one — the button hides); [onPlay], when the
 * caller can replay the clip, shows the mock's 0.5× control.
 */
@Composable
fun RepCorrection(
    data: RepCorrectionData,
    clip: File?,
    onBack: () -> Unit,
    onNext: (() -> Unit)?,
    onPlay: (() -> Unit)? = null,
) {
    Column(
        Modifier
            .fillMaxSize()
            .background(Tk.bg)
            .windowInsetsPadding(WindowInsets.systemBars),
    ) {
        // «← REP 4 · BALANCEO»
        Row(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Box(
                Modifier
                    .size(48.dp)
                    .clip(InnerShape)
                    .background(Tk.surface)
                    .border(2.dp, Tk.border, InnerShape)
                    .clickable(onClick = onBack)
                    .semantics { role = Role.Button; contentDescription = "Volver" },
                contentAlignment = Alignment.Center,
            ) {
                Text("←", style = display(16, color = Tk.ink))
            }
            Column(Modifier.weight(1f)) {
                Text(
                    "REP ${data.rep} · ${shortFault(data.title)}",
                    style = display(20, line = 1f),
                )
                Text(
                    "${clockLabel(data.atS)} · PAUSADO EN EL PUNTO CLAVE",
                    style = mono(11, 0.05f, Tk.muted),
                )
            }
        }

        Column(
            Modifier
                .weight(1f)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp),
        ) {
            // The two frames, side by side, straight from the clip.
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(vertical = 10.dp)
                    .height(220.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                FrameBox(
                    clip = clip,
                    atS = data.atS,
                    label = "TU REP ${data.rep}",
                    badgeText = data.value,
                    badgeBackground = Tk.primary,
                    modifier = Modifier.weight(1f),
                )
                FrameBox(
                    clip = clip,
                    atS = data.bestAtS,
                    label = "TU MEJOR (REP ${data.bestRep})",
                    badgeText = data.bestValue,
                    badgeBackground = Tk.surface,
                    modifier = Modifier.weight(1f),
                )
            }

            // The number that fired, and the standard it is measured against.
            Row(
                Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Column(Modifier.weight(1f)) {
                    Text(data.value, style = display(30))
                    Text(
                        data.goal,
                        style = mono(11, 0.05f, Tk.muted),
                        modifier = Modifier.padding(top = 2.dp),
                    )
                }
                if (onPlay != null) {
                    Box(
                        Modifier
                            .size(48.dp)
                            .clip(InnerShape)
                            .background(Tk.surface)
                            .border(2.dp, Tk.border, InnerShape)
                            .clickable(onClick = onPlay)
                            .semantics {
                                role = Role.Button
                                contentDescription = "Ver la repetición a mitad de velocidad"
                            },
                        contentAlignment = Alignment.Center,
                    ) {
                        Text("0.5×", style = mono(12, 0f, Tk.ink, FontWeight.SemiBold))
                    }
                }
            }

            Text(
                data.title,
                style = display(22, line = 1.05f),
                modifier = Modifier.padding(top = 12.dp),
            )
            Text(
                data.why,
                style = body(14, Tk.muted, 1.5f),
                modifier = Modifier.padding(top = 10.dp),
            )

            TkCard(
                Modifier.padding(top = 14.dp),
                padding = PaddingValues(12.dp),
            ) {
                Eyebrow("PRUEBA EN LA PRÓXIMA SERIE")
                Text(
                    data.cue,
                    style = body(15, Tk.ink, 1.4f, FontWeight.SemiBold),
                    modifier = Modifier.padding(top = 6.dp),
                )
            }
        }

        if (onNext != null) {
            Box(
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 16.dp)
                    .heightIn(min = 52.dp)
                    .hardShadow(InnerShape, offset = 3.dp)
                    .clip(InnerShape)
                    .background(Tk.primary)
                    .border(2.dp, Tk.border, InnerShape)
                    .clickable(onClick = onNext)
                    .padding(horizontal = 16.dp, vertical = 14.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    "SIGUIENTE CORRECCIÓN · ${data.index + 1}/${data.total}",
                    style = display(16, color = Tk.ink),
                )
            }
        }
    }
}

/** One clip frame with its name and, when there is a number, its badge. */
@Composable
private fun FrameBox(
    clip: File?,
    atS: Double,
    label: String,
    badgeText: String?,
    badgeBackground: Color,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier
            .clip(CardShape)
            .background(Tk.dark)
            .border(2.dp, Tk.border, CardShape),
    ) {
        val frame = keyFrame(clip, atS)
        if (frame != null) {
            Image(
                frame,
                contentDescription = "Fotograma en ${clockLabel(atS)}",
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize(),
            )
        } else {
            Column(
                Modifier.fillMaxSize(),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(clockLabel(atS), style = mono(11, 0.05f, Tk.faint))
            }
        }
        Text(
            label,
            style = mono(10, 0.05f, Tk.onInk, FontWeight.SemiBold),
            modifier = Modifier
                .align(Alignment.TopStart)
                .padding(8.dp)
                .clip(RoundedCornerShape(6.dp))
                .background(Tk.ink.copy(alpha = 0.75f))
                .padding(horizontal = 6.dp, vertical = 2.dp),
        )
        if (badgeText != null) {
            Text(
                badgeText,
                style = display(20, color = Tk.ink),
                modifier = Modifier
                    .align(Alignment.BottomEnd)
                    .padding(10.dp)
                    .clip(CardShape)
                    .background(badgeBackground)
                    .border(2.dp, Tk.border, CardShape)
                    .padding(horizontal = 10.dp, vertical = 4.dp),
            )
        }
    }
}
