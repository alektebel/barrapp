package com.barrapp.ui.tracker

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.heightIn
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.barrapp.cueEs
import com.barrapp.data.Analysis
import com.barrapp.faultCounts
import com.barrapp.faultEs
import com.barrapp.ui.theme.T
import com.barrapp.ui.theme.Tk
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

@Composable
internal fun FixesCard(
    fixes: List<FixItem>,
    onShowRep: ((Int) -> Unit)? = null,
    unjudged: String? = null,
) {
    TkCard(accent = true) {
        Eyebrow("Lo que mejorar")
        if (unjudged != null) {
            Text(unjudged, style = T.bodyInk, modifier = Modifier.padding(top = 10.dp))
            return@TkCard
        }
        if (fixes.isEmpty()) {
            Text("Nada importante que corregir en esta serie.", style = T.bodyInk,
                modifier = Modifier.padding(top = 10.dp))
            return@TkCard
        }
        fixes.forEachIndexed { i, fix ->
            Row(
                Modifier.padding(top = if (i == 0) 12.dp else 16.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Box(
                    Modifier.size(26.dp).clip(CircleShape)
                        .background(if (i == 0) Tk.primary else Tk.primary.copy(alpha = 0.35f)),
                    contentAlignment = Alignment.Center,
                ) {
                    Text("${i + 1}", style = mono(12, 0f, Tk.bg).copy(fontWeight = FontWeight.Bold))
                }
                Column(Modifier.padding(top = 2.dp)) {
                    Text(fix.title, style = T.bodyInk.copy(fontWeight = FontWeight.SemiBold))
                    fix.cue?.let { Text(it, style = T.bodyS, modifier = Modifier.padding(top = 2.dp)) }
                    Spacer(Modifier.height(2.dp))
                    Text(fix.where, style = mono(9, 0.05f, Tk.amber))
                    if (onShowRep != null && fix.repIndex != null) {
                        val rep = fix.repIndex
                        Text(
                            "Ver en la rep ${rep + 1} →",
                            style = mono(11, 0.05f, Tk.primaryLight),
                            modifier = Modifier
                                .heightIn(min = 48.dp)
                                .semantics { role = Role.Button }
                                .clickable { onShowRep(rep) }
                                .padding(vertical = 14.dp),
                        )
                    }
                }
            }
        }
    }
}
