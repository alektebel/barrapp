package com.barrapp.ui.tracker

import androidx.compose.foundation.background
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

/** One of the three things to improve, ready to show. */
data class FixItem(val title: String, val cue: String?, val where: String)

/**
 * The three things to improve, most important first (docs/UX-PLAN.md).
 *
 * The server ranks them (topFixes: coaching order, then how many reps showed
 * it, then how far past the threshold). An older server sends none; then the
 * three most frequent measured faults stand in, so the screen is never empty
 * for a set that had faults. Never more than three, never padded.
 */
fun fixItems(a: Analysis): List<FixItem> {
    if (a.topFixes.isNotEmpty()) {
        return a.topFixes.take(3).map {
            FixItem(faultEs(it.name), cueEs(it.name),
                "en ${it.observedReps} de ${it.judgedReps} repeticiones")
        }
    }
    return faultCounts(a).take(3).map { (name, n) ->
        FixItem(faultEs(name), cueEs(name), "en $n de ${a.reps.size} repeticiones")
    }
}

@Composable
internal fun FixesCard(fixes: List<FixItem>) {
    TkCard(accent = true) {
        Eyebrow("Lo que mejorar")
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
                }
            }
        }
    }
}
