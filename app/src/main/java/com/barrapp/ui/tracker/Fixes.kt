package com.barrapp.ui.tracker

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import com.barrapp.cueEs
import com.barrapp.data.Analysis
import com.barrapp.faultCounts
import com.barrapp.faultEs
import com.barrapp.ui.theme.T
import com.barrapp.ui.theme.Tk
import com.barrapp.ui.theme.display
import com.barrapp.ui.theme.mono

/** One of the three things to improve, ready to show. [repIndex] is the rep
 *  that shows it worst, for "Ver en la rep N"; null when none does. */
data class FixItem(
    val title: String,
    val cue: String?,
    val where: String,
    val repIndex: Int? = null,
)

/**
 * The three things to improve, most important first (docs/UX-PLAN.md).
 *
 * The server ranks them (topFixes: coaching order, then how many reps showed
 * it, then how far past the threshold). An older server sends none; then the
 * three most frequent measured faults stand in, so the screen is never empty
 * for a set that had faults. Never more than three, never padded.
 */
fun fixItems(a: Analysis): List<FixItem> {
    val plan = com.barrapp.ui.replay.ReplayPlan.from(a, a.durationS)
    if (a.topFixes.isNotEmpty()) {
        return a.topFixes.take(3).map {
            FixItem(faultEs(it.name), cueEs(it.name),
                "en ${it.observedReps} de ${it.judgedReps} repeticiones",
                plan.worstRepFor(it.name)?.index)
        }
    }
    return faultCounts(a).take(3).map { (name, n) ->
        FixItem(faultEs(name), cueEs(name), "en $n de ${a.reps.size} repeticiones",
            plan.worstRepFor(name)?.index)
    }
}

/**
 * Why a counted set was not judged, from what the analysis already says; null
 * when at least one rep was scored. Never reads as a clean set.
 */
fun unjudgedNote(a: Analysis): String? {
    if (!a.unmeasuredSet) return null
    val n = a.reps.size.takeIf { it > 0 } ?: a.repCount
    val why = a.reps.firstNotNullOfOrNull { it.assessmentBlocked?.takeIf { s -> s.isNotBlank() } }
        ?: a.reps.firstNotNullOfOrNull { it.scoreNote.takeIf { s -> s.isNotBlank() } }
        ?: a.blockers.firstOrNull { it.isNotBlank() }
    val head = if (n == 1) "No se pudo juzgar la repetición." else "No se pudo juzgar ninguna de las $n repeticiones."
    val tail = "Eso no quiere decir que salieran bien: no hay nada medido que corregir ni que dar por bueno."
    return if (why != null) "$head ${why.trim().trimEnd('.')}. $tail" else "$head $tail"
}

/**
 * "Lo que mejorar", in the design's own shape (2b): a mono label and one
 * bordered row per fix — the rep that shows it as the tag, the cue as the
 * sub-line, and the whole row leading to that rep in the video. No orange
 * card and no hard shadow: this section asks for attention, not for action.
 *
 * `selectedRep` (the rep shown in the clip right now) tints its row, the
 * design's way of answering "which one am I looking at?".
 */
@Composable
internal fun FixesCard(
    fixes: List<FixItem>,
    onShowRep: ((Int) -> Unit)? = null,
    unjudged: String? = null,
    selectedRep: Int? = null,
) {
    if (unjudged != null) {
        TkCard {
            Eyebrow("Serie sin juzgar")
            Text(unjudged, style = T.bodyInk, modifier = Modifier.padding(top = 10.dp))
        }
        return
    }
    if (fixes.isEmpty()) {
        TkCard {
            Eyebrow("Lo que mejorar")
            Text("Nada importante que corregir en esta serie.", style = T.bodyInk,
                modifier = Modifier.padding(top = 10.dp))
        }
        return
    }
    Column {
        Eyebrow(
            if (onShowRep != null) "Lo que mejorar · toca para verlo" else "Lo que mejorar",
            style = mono(12, 0.05f, Tk.muted),
        )
        Spacer(Modifier.height(8.dp))
        fixes.forEachIndexed { i, fix ->
            val rep = fix.repIndex
            val tappable = onShowRep != null && rep != null
            val selected = rep != null && rep == selectedRep
            val shape = CardShape
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(top = if (i == 0) 0.dp else 8.dp)
                    .clip(shape)
                    .background(if (selected) Tk.orangeSoft else Tk.surface)
                    .border(2.dp, Tk.border, shape)
                    .then(
                        if (onShowRep != null && rep != null)
                            Modifier.clickable { onShowRep(rep) }
                        else Modifier
                    )
                    .semantics {
                        if (onShowRep != null && rep != null) {
                            role = Role.Button
                            contentDescription = "Ver en el vídeo la rep ${rep + 1}: ${fix.title}"
                        }
                    }
                    .padding(12.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                // The tag is the evidence: the rep where this shows worst.
                Text(
                    rep?.let { "REP ${it + 1}" } ?: "${i + 1}",
                    style = mono(12, 0f, Tk.ink, FontWeight.SemiBold),
                )
                Column(Modifier.weight(1f)) {
                    Text(fix.title, style = T.itemTitle)
                    fix.cue?.let {
                        Text(it, style = T.bodyS, modifier = Modifier.padding(top = 2.dp))
                    }
                    Text(
                        fix.where,
                        style = mono(9, 0.05f, Tk.muted),
                        modifier = Modifier.padding(top = 3.dp),
                    )
                }
                if (onShowRep != null && rep != null) {
                    Text("→", style = display(18, color = Tk.ink))
                }
            }
        }
    }
}
