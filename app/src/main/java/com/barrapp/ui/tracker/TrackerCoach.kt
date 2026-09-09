package com.barrapp.ui.tracker

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.barrapp.Drill
import com.barrapp.ui.theme.T
import com.barrapp.ui.theme.Tk
import com.barrapp.ui.theme.body
import com.barrapp.ui.theme.mono

/** One technique rule, as the app measured it over the recent window. */
data class CoachRule(
    val id: String,
    val title: String,
    val phase: String,
    /** "Corregir" / "Progresando" / "Correcto" / "Sin juzgar" */
    val verdict: String,
    val verdictInk: Color,
    val description: String,
    val cue: String,
)

/** A fault the coach is working on, with the evidence behind it. */
data class CoachFocus(
    val fault: String,
    val cue: String,
    val drill: Drill?,
    val repsAffected: Int,
    /** How much it fell against the previous window; null with nothing to
     *  compare against. */
    val improvementPct: Int?,
    val improving: Boolean,
)

data class CoachData(
    val movement: String,
    val sessions: Int,
    val focus: CoachFocus?,
    val secondary: CoachFocus?,
    val rules: List<CoachRule>,
    val drills: List<Drill>,
    val totalMinutes: Int,
)

/**
 * Coach.
 *
 * The mockup fronts each fault with an Unsplash photograph. This app ships no
 * photo assets and does not fetch remote images — an image request would carry
 * the fact that this athlete is working on this fault to a third party — so
 * the hero panels are the design's gradient with its type on top. That is the
 * one place this screen renders less than the mockup.
 *
 * Everything else is measured: the focus is the fault the ledger counted most
 * over the last four weeks, the rules are the checks the pipeline actually
 * ran, and a rule that could not be judged says so instead of passing.
 */
@Composable
fun TrackerCoach(
    data: CoachData,
    onAskCoach: () -> Unit,
    onRecord: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var openRule by remember { mutableStateOf(data.rules.firstOrNull()?.id) }
    var secondOpen by remember { mutableStateOf(false) }

    Column(
        modifier
            .fillMaxWidth()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp)
            .padding(top = 8.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Column {
            Text("BarrApp", style = T.eyebrowWide)
            Text("COACH", style = T.pageTitle)
            Text(
                if (data.sessions > 0)
                    "Basado en tus últimas ${data.sessions} sesiones de ${data.movement}"
                else "Todavía sin sesiones que leer",
                style = T.bodyS,
                modifier = Modifier.padding(top = 2.dp),
            )
        }

        if (data.focus == null) {
            TkCard {
                Text("NADA QUE CORREGIR TODAVÍA", style = T.sectionTitle)
                Spacer(Modifier.height(6.dp))
                Text(
                    "El coach solo habla de errores que se han medido. Filma una serie " +
                        "y trabajará sobre lo que salga de ella.",
                    style = T.bodyS,
                )
                Spacer(Modifier.height(16.dp))
                TkPrimaryButton("Grabar un set", onRecord)
            }
        } else {
            SlideUp { FocusCard(data.focus) }
        }

        if (data.rules.isNotEmpty()) {
            SlideUp(delayMillis = 100) {
                TkCard(padding = PaddingValues(0.dp)) {
                    Column(Modifier.padding(start = 16.dp, end = 16.dp, top = 16.dp, bottom = 8.dp)) {
                        Eyebrow("Reglas de técnica · ${data.movement}")
                        Text(
                            "El sistema evalúa estos criterios en cada repetición",
                            style = T.noteNine,
                            modifier = Modifier.padding(top = 2.dp),
                        )
                    }
                    data.rules.forEach { rule ->
                        Box(Modifier.fillMaxWidth().height(1.dp).background(Tk.border))
                        RuleRow(
                            rule = rule,
                            open = openRule == rule.id,
                            onToggle = { openRule = if (openRule == rule.id) null else rule.id },
                        )
                    }
                }
            }
        }

        if (data.drills.isNotEmpty()) {
            SlideUp(delayMillis = 200) {
                TkCard {
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Eyebrow("Ejercicios correctivos de hoy")
                        Text("~${data.totalMinutes} min", style = T.eyebrowNine)
                    }
                    Spacer(Modifier.height(12.dp))
                    data.drills.forEachIndexed { i, drill ->
                        Row(
                            Modifier.fillMaxWidth().padding(vertical = 10.dp),
                            horizontalArrangement = Arrangement.spacedBy(12.dp),
                        ) {
                            Box(
                                Modifier
                                    .size(28.dp)
                                    .clip(ChipShape)
                                    .background(Tk.primaryA(0.15f)),
                                contentAlignment = Alignment.Center,
                            ) {
                                Text(
                                    "${i + 1}",
                                    style = com.barrapp.ui.theme.display(
                                        14, androidx.compose.ui.text.font.FontWeight.Black,
                                        1f, 0f, Tk.primaryLight,
                                    ),
                                )
                            }
                            Column(Modifier.weight(1f)) {
                                Row(
                                    Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                ) {
                                    Text(drill.title, style = T.itemTitle)
                                    Text(drill.sets, style = mono(9, 0.05f, Tk.primary))
                                }
                                Text(drill.focus, style = T.noteTiny,
                                    modifier = Modifier.padding(top = 2.dp))
                                Text(drill.duration, style = mono(9, 0.05f, Tk.faint),
                                    modifier = Modifier.padding(top = 2.dp))
                            }
                        }
                        if (i < data.drills.size - 1) {
                            Box(Modifier.fillMaxWidth().height(1.dp).background(Tk.border))
                        }
                    }
                }
            }
        }

        data.secondary?.let { second ->
            SlideUp(delayMillis = 300) {
                TkCard(padding = PaddingValues(0.dp)) {
                    Box(
                        Modifier
                            .fillMaxWidth()
                            .height(112.dp)
                            .background(heroBrush(if (second.improving) Tk.teal else Tk.amber))
                            .noRipple { secondOpen = !secondOpen }
                            .padding(16.dp),
                    ) {
                        Column(
                            Modifier.fillMaxSize(),
                            verticalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(8.dp),
                            ) {
                                Box(
                                    Modifier.size(width = 6.dp, height = 16.dp)
                                        .clip(RoundedCornerShape(3.dp))
                                        .background(if (second.improving) Tk.teal else Tk.amber)
                                )
                                Text(
                                    if (second.improving) "MEJORANDO" else "EN SEGUIMIENTO",
                                    style = mono(9, 0.12f, if (second.improving) Tk.teal else Tk.amber),
                                )
                            }
                            Spacer(Modifier.height(24.dp))
                            Text(second.fault.uppercase(), style = T.missionTitle)
                        }
                    }
                    AnimatedVisibility(secondOpen) {
                        Column(Modifier.padding(16.dp)) {
                            Text(second.cue, style = T.bodyS)
                            Spacer(Modifier.height(12.dp))
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                second.improvementPct?.let { pct ->
                                    Tag(
                                        if (pct >= 0) "↓ $pct% en 4 semanas"
                                        else "↑ ${-pct}% en 4 semanas",
                                        if (pct >= 0) Tk.teal else Tk.amber,
                                    )
                                }
                                Tag("${second.repsAffected} reps este mes", Tk.muted)
                            }
                        }
                    }
                }
            }
        }

        TkSecondaryButton(
            "Preguntar al coach",
            onAskCoach,
            tint = Tk.primaryLight,
            border = Tk.primaryA(0.25f),
            background = Tk.primaryA(0.12f),
        )
    }
}

@Composable
private fun FocusCard(focus: CoachFocus) {
    TkCard(padding = PaddingValues(0.dp), accent = true) {
        Box(
            Modifier
                .fillMaxWidth()
                .height(144.dp)
                .background(heroBrush(Tk.amber))
                .padding(16.dp),
            contentAlignment = Alignment.BottomStart,
        ) {
            Column {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Box(
                        Modifier.size(width = 6.dp, height = 16.dp)
                            .clip(RoundedCornerShape(3.dp)).background(Tk.amber)
                    )
                    Text("FOCO DE HOY", style = mono(9, 0.15f, Tk.amber))
                }
                Spacer(Modifier.height(4.dp))
                Text(focus.fault.uppercase(), style = T.cardHeadline)
                Text(
                    buildString {
                        append("${focus.repsAffected} reps afectadas")
                        focus.improvementPct?.let {
                            append(if (it >= 0) " · ↓ $it% en 4 semanas" else " · ↑ ${-it}% en 4 semanas")
                        }
                    },
                    style = body(12, Tk.inkA(0.7f)),
                    modifier = Modifier.padding(top = 2.dp),
                )
            }
        }
        Column(Modifier.background(Tk.surface).padding(16.dp)) {
            Text(focus.cue, style = T.bodyS)
            focus.drill?.let { drill ->
                Spacer(Modifier.height(12.dp))
                Row(
                    Modifier
                        .fillMaxWidth()
                        .clip(InnerShape)
                        .background(Tk.primaryA(0.1f))
                        .border(1.dp, Tk.primaryA(0.2f), InnerShape)
                        .padding(horizontal = 12.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text("🏋️", style = body(18, Tk.ink))
                    Column {
                        Text("Ejercicio correctivo", style = T.itemTitleSmall)
                        Text("${drill.title} · ${drill.sets}", style = body(10, Tk.primaryLight))
                    }
                }
            }
        }
    }
}

@Composable
private fun RuleRow(rule: CoachRule, open: Boolean, onToggle: () -> Unit) {
    Column {
        Row(
            Modifier.fillMaxWidth().noRipple(onToggle).padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(Modifier.size(8.dp).clip(CircleShape).background(rule.verdictInk))
            Spacer(Modifier.size(12.dp))
            Column(Modifier.weight(1f)) {
                Text(rule.title, style = T.itemTitle)
                Text(rule.phase, style = T.eyebrowNine)
            }
            Text(rule.verdict, style = mono(9, 0.05f, rule.verdictInk))
            Spacer(Modifier.size(10.dp))
            androidx.compose.foundation.Canvas(Modifier.size(14.dp)) {
                drawChevron(Tk.muted, flipped = open)
            }
        }
        AnimatedVisibility(open) {
            Column(Modifier.padding(start = 16.dp, end = 16.dp, bottom = 16.dp)) {
                Text(rule.description, style = T.bodyS)
                if (rule.cue.isNotBlank()) {
                    Spacer(Modifier.height(8.dp))
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .clip(InnerShape)
                            .background(Tk.primaryA(0.08f))
                            .border(1.dp, Tk.primaryA(0.15f), InnerShape)
                            .padding(horizontal = 12.dp, vertical = 10.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Text("💡", style = body(14, Tk.primaryLight))
                        Text(rule.cue, style = body(12, Tk.primaryLight))
                    }
                }
            }
        }
    }
}

@Composable
private fun Tag(text: String, ink: Color) {
    Text(
        text,
        style = body(10, ink),
        modifier = Modifier
            .clip(ChipShape)
            .background(ink.copy(alpha = 0.1f))
            .border(1.dp, ink.copy(alpha = 0.2f), ChipShape)
            .padding(horizontal = 8.dp, vertical = 4.dp),
    )
}

/** The gradient that stands in for the mockup's darkened photograph. */
private fun heroBrush(tint: Color) = Brush.linearGradient(
    listOf(
        Tk.card,
        tint.copy(alpha = 0.10f),
        Tk.surface,
    )
)
