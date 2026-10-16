package com.barrapp.ui

import kotlinx.coroutines.launch
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.barrapp.cueEs
import com.barrapp.data.Analysis
import com.barrapp.ui.replay.RepReplay
import com.barrapp.ui.replay.ReplayPlan
import com.barrapp.ui.replay.rememberRepReplayState
import com.barrapp.ui.theme.T
import com.barrapp.ui.theme.Tk
import com.barrapp.ui.theme.body
import com.barrapp.ui.theme.mono
import com.barrapp.ui.tracker.TkSecondaryButton

/**
 * The set, full screen, with the measurement over it (ui/replay/RepReplay).
 *
 * Below the video, only the reps that have something to say: a fault, or a
 * shape unlike the rest of the set. Tapping one moves the video to its
 * turnaround. A clean set says so in one line instead of listing nineteen
 * clean reps.
 */
@Composable
fun ReplayScreen(
    analysis: Analysis?,
    clip: java.io.File?,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    BackHandler(onBack = onBack)
    val scroll = rememberScrollState()
    Column(
        modifier
            .fillMaxSize()
            .background(Tk.bg)
            .verticalScroll(scroll)
            // Edge to edge: the last line must clear the system navigation bar.
            .navigationBarsPadding()
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text(
            "← Volver",
            style = mono(12, 0.05f, Tk.primaryLight),
            modifier = Modifier
                .heightIn(min = 48.dp)
                .semantics { role = Role.Button }
                .clickable(onClick = onBack)
                .padding(vertical = 14.dp),
        )
        when {
            clip == null -> Missing("Este teléfono ya no guarda una copia del clip.", onBack)
            analysis == null || analysis.reps.none { it.endS > it.startS } ->
                Missing("Esta serie no tiene repeticiones medidas que marcar.", onBack)
            else -> Body(analysis, clip, scroll)
        }
    }
}

@Composable
private fun Missing(message: String, onBack: () -> Unit) {
    Column(Modifier.fillMaxWidth().padding(top = 48.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Text(message, style = T.lead)
        Spacer(Modifier.size(20.dp))
        TkSecondaryButton("Volver a la sesión", onBack)
    }
}

@Composable
private fun Body(analysis: Analysis, clip: java.io.File, scroll: androidx.compose.foundation.ScrollState) {
    val scope = androidx.compose.runtime.rememberCoroutineScope()
    val replay = rememberRepReplayState()
    val plan = remember(analysis) { ReplayPlan.from(analysis, analysis.durationS) }
    RepReplay(analysis, clip, state = replay, fullScreen = true)

    val worth = plan.reps.filter { it.fault != null || it.outlier }
    if (worth.isEmpty()) {
        // Nothing to point at is only a clean set when the reps were judged.
        Text(
            if (plan.reps.none { it.measured })
                "No se pudo juzgar ninguna repetición de esta serie: el contador es fiable, la técnica no se midió."
            else "Ninguna repetición se salió del patrón ni mostró un fallo.",
            style = T.lead,
        )
        return
    }
    Text("Para mirar", style = T.sectionTitle)
    worth.forEach { rep ->
        Row(
            Modifier
                .fillMaxWidth()
                .heightIn(min = 48.dp)
                .clip(androidx.compose.foundation.shape.RoundedCornerShape(12.dp))
                .background(Tk.surface)
                .semantics(mergeDescendants = true) { role = Role.Button }
                .clickable {
                    replay.showRep(rep.index)
                    // El vídeo está arriba: si la lista se ha desplazado, el salto no se vería.
                    scope.launch { scroll.animateScrollTo(0) }
                }
                .padding(horizontal = 14.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Box(Modifier.size(8.dp).clip(CircleShape).background(if (rep.fault != null) Tk.amber else Tk.ink))
            Column(Modifier.weight(1f)) {
                Text(
                    "Rep ${rep.number} · " + (rep.fault ?: "distinta al resto"),
                    style = T.itemTitle,
                )
                val cue = rep.faultKeys.firstOrNull()?.let(::cueEs)
                    ?: rep.shapeNote
                cue?.let { Text(it, style = body(12, Tk.muted), modifier = Modifier.padding(top = 2.dp)) }
            }
            Text("%.1f s".format(rep.moment), style = mono(10, 0f, Tk.muted))
        }
    }
}
