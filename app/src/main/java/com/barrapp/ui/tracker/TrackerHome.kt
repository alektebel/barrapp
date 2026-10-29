package com.barrapp.ui.tracker

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.drawOutline
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.barrapp.Gamification
import com.barrapp.ui.theme.T
import com.barrapp.ui.theme.Tk
import com.barrapp.ui.theme.body
import com.barrapp.ui.theme.display
import com.barrapp.ui.theme.mono
import com.barrapp.ui.theme.scoreInk
import java.text.DecimalFormat
import java.text.DecimalFormatSymbols
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Locale

/** One movement's share of the last training day — the design's "SER n" row,
 *  carrying what this app can actually attribute: a movement, not a set. */
data class SessionRowData(val label: String, val score: Int?, val reps: Int)

data class LastSessionData(
    val movement: String,
    val date: String,
    val reps: Int,
    val score: Int?,
    /** Reps that were scored. 0 with reps > 0 is a counted, never judged set. */
    val judged: Int = reps,
    val rows: List<SessionRowData>,
    /** The fault the day showed most, and how many reps showed it. */
    val topFault: Pair<String, Int>?,
    /**
     * The last clip's per-rep score, in rep order; null where the pose model
     * could not read a rep. Empty until it is wired from the analysis: the
     * rep strip then falls back to the session's aggregate bar.
     */
    val repScores: List<Int?> = emptyList(),
    /** Clips (series) the session folds, for the «N REPS · M SERIES» line. */
    val sets: Int = 1,
)

/** The ladder's current rung, for the «SIGUIENTE LOGRO» row. */
data class NextGoalData(
    val label: String,
    val done: Int,
    val target: Int,
) {
    val fraction: Float
        get() = if (target <= 0) 0f else (done.toFloat() / target).coerceIn(0f, 1f)
}

data class HomeData(
    val name: String,
    val standing: Gamification.Standing,
    val week: List<Gamification.WeekDay>,
    val mission: Gamification.Mission,
    val lastSession: LastSessionData?,
    val badges: List<Gamification.Badge>,
    /** The next rung of the ladder; null hides the row until it is wired. */
    val nextGoal: NextGoalData? = null,
    /** Weekly session target for «N/T SESIONES SEM.»; 0 shows only the count. */
    val weekTarget: Int = 0,
    /** Clips that finished and have not been opened yet. */
    val newResults: Int = 0,
)

/**
 * Inicio, design 2a.
 *
 * One main action — the orange mission card, with the ink GRABAR SERIE slab.
 * Everything else reports: a single strip carries streak, level/XP and the
 * week's sessions, the last session shows itself as a clip with one bar per
 * rep, and the next ladder rung dangles from a dashed row. Every number is
 * measured: a phone that has filmed nothing shows zeroes and an empty clip
 * card rather than someone else's streak.
 */
@Composable
fun TrackerHome(
    data: HomeData,
    onOpenSession: () -> Unit,
    onOpenCoach: () -> Unit,
    onOpenCalendar: () -> Unit,
    onOpenLadder: () -> Unit,
    onRecord: () -> Unit,
    modifier: Modifier = Modifier,
    onOpenNew: () -> Unit = {},
) {
    Column(
        modifier
            .fillMaxWidth()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp)
            .padding(top = 8.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Greeting(data)
        if (data.newResults > 0) NewResultsBanner(data.newResults, onOpenNew)
        StatStrip(data, onOpenCalendar)
        MissionCard(data.mission, onRecord)
        LastSessionSection(data.lastSession, onOpenSession, onRecord)
        NextGoalRow(data.nextGoal, onOpenLadder)
    }
}

@Composable
private fun Greeting(data: HomeData) {
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.Bottom,
    ) {
        Column {
            Text(todayLabel(), style = mono(12, 0.02f))
            Spacer(Modifier.height(4.dp))
            Text(
                "HOLA, ${displayName(data.name).uppercase()}",
                style = display(30),
            )
        }
        Box(
            Modifier
                .size(44.dp)
                .clip(InnerShape)
                .background(Tk.surface)
                .border(2.dp, Tk.border, InnerShape),
            contentAlignment = Alignment.Center,
        ) {
            Text(initial(data.name), style = display(16))
        }
    }
}

/** Streak, level/XP and the week's sessions: one strip, 2px separators. The
 *  week cell opens the calendar — it is where the old week card's VER MES
 *  went. */
@Composable
private fun StatStrip(data: HomeData, onOpenCalendar: () -> Unit) {
    val done = data.week.count { it.done }
    Row(
        Modifier
            .fillMaxWidth()
            .height(IntrinsicSize.Min)
            .clip(CardShape)
            .background(Tk.surface)
            .border(2.dp, Tk.border, CardShape),
    ) {
        StatCell(data.standing.streak.toString(), "Días seguidos", Modifier.weight(1f))
        StripDivider()
        StatCell(
            "NV ${data.standing.level}",
            "${xpEs(data.standing.totalXp)} XP",
            Modifier.weight(1f),
        )
        StripDivider()
        Column(
            Modifier
                .weight(1f)
                .noRipple(onOpenCalendar)
                .padding(horizontal = 10.dp, vertical = 10.dp),
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            Text(
                if (data.weekTarget > 0) "$done/${data.weekTarget}" else "$done",
                style = display(22),
            )
            Text("SESIONES SEM.", style = mono(11, 0.02f, line = 1.25f))
        }
    }
}

@Composable
private fun RowScope.StatCell(value: String, label: String, modifier: Modifier) {
    Column(
        modifier.padding(horizontal = 10.dp, vertical = 10.dp),
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        Text(value, style = display(22))
        Text(label.uppercase(), style = mono(11, 0.02f, line = 1.25f))
    }
}

@Composable
private fun RowScope.StripDivider() {
    Box(Modifier.width(2.dp).fillMaxHeight().background(Tk.border))
}

@Composable
private fun MissionCard(mission: Gamification.Mission, onRecord: () -> Unit) {
    TkCard(accent = true) {
        Eyebrow("Misión de hoy", style = T.eyebrowMission)
        Spacer(Modifier.height(12.dp))
        Text(
            "${mission.targetReps} reps · ${mission.movement}".uppercase(),
            style = T.missionTitle,
        )
        Spacer(Modifier.height(8.dp))
        Text(mission.focus, style = body(14, Tk.ink, 1.4f))
        Spacer(Modifier.height(12.dp))
        // One segment per rep the standard asks for, filled by what was
        // measured today. Ink fills on the orange ground — orange there would
        // vanish, and the orange is already spent on the action itself.
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            repeat(mission.targetReps.coerceIn(1, 12)) { i ->
                Box(
                    Modifier
                        .weight(1f)
                        .height(6.dp)
                        .clip(RoundedCornerShape(3.dp))
                        .background(if (i < mission.doneReps) Tk.ink else Tk.orangeSoft),
                )
            }
        }
        Spacer(Modifier.height(8.dp))
        Text(
            if (mission.complete)
                "Misión cumplida · ${mission.doneReps} reps medidas hoy"
            else "${mission.doneReps} de ${mission.targetReps} reps medidas hoy · " +
                "+${mission.xpReward} XP al terminar",
            style = mono(9, 0.05f, Tk.ink),
        )
        Spacer(Modifier.height(12.dp))
        // The card already wears the hard shadow; the slab inside it does not
        // double it.
        TkPrimaryButton("Grabar serie", onRecord, shadow = false)
    }
}

@Composable
private fun LastSessionSection(
    session: LastSessionData?,
    onOpenSession: () -> Unit,
    onRecord: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Eyebrow(
                if (session == null) "Última sesión" else "Última sesión · ${session.date}",
                style = mono(12, 0.02f),
            )
            if (session != null) {
                Text(
                    "VER",
                    style = mono(12, 0.05f, Tk.ink),
                    textDecoration = TextDecoration.Underline,
                )
            }
        }
        if (session == null) {
            // Nothing measured yet. An empty state says less and lies none;
            // tapping it starts where the data comes from.
            TkCard(padding = PaddingValues(8.dp), modifier = Modifier.noRipple(onRecord)) {
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    ClipThumb(hasClip = false)
                    Column(
                        Modifier.weight(1f).heightIn(min = 88.dp).padding(vertical = 2.dp),
                        verticalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Text("Sin sesiones todavía", style = T.rowTitle)
                        Text(
                            "Filma una serie y aquí aparecerá su clip, con la nota de cada rep.",
                            style = T.bodyS,
                        )
                    }
                }
            }
        } else {
            // The clip is the entry: the whole card opens the session.
            TkCard(padding = PaddingValues(8.dp), modifier = Modifier.noRipple(onOpenSession)) {
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    ClipThumb(hasClip = true)
                    Column(
                        Modifier.weight(1f).heightIn(min = 88.dp).padding(vertical = 2.dp),
                        verticalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Row {
                            Text(
                                session.movement.uppercase(),
                                style = T.rowTitle,
                                modifier = Modifier.weight(1f).alignByBaseline(),
                            )
                            Text(
                                session.score?.toString() ?: "—",
                                style = display(22, color = scoreInk(session.score)),
                                modifier = Modifier.alignByBaseline(),
                            )
                        }
                        Text(sessionMeta(session), style = mono(11, 0.02f))
                        RepStrip(session)
                    }
                }
            }
        }
    }
}

/** The clip's frame: dark ground and the bar, until a real thumbnail reaches
 *  the screen. Decorative either way — the card's own texts describe it. */
@Composable
private fun ClipThumb(hasClip: Boolean) {
    Box(
        Modifier
            .size(88.dp)
            .clip(InnerShape)
            .background(Tk.dark)
            .then(
                if (hasClip)
                    Modifier.clearAndSetSemantics { contentDescription = "Vídeo de la última sesión" }
                else
                    Modifier.clearAndSetSemantics { }
            ),
        contentAlignment = Alignment.TopCenter,
    ) {
        Box(
            Modifier
                .padding(top = 14.dp)
                .width(64.dp)
                .height(3.dp)
                .background(Tk.darkLine),
        )
    }
}

private fun sessionMeta(session: LastSessionData): String {
    val parts = mutableListOf("${session.reps} reps")
    if (session.sets > 1) parts += "${session.sets} series"
    if (session.score == null && session.reps > 0) parts += "sin puntuar"
    return parts.joinToString(" · ").uppercase()
}

/**
 * One bar per rep, height by its score, in its band's ink. A rep the pose
 * model could not read is a grey stub — never zero, never red. Without
 * per-rep data yet, it falls back to the session's aggregate bar and draws
 * nothing it did not measure.
 */
@Composable
private fun RepStrip(session: LastSessionData) {
    val perRep: List<Int?> = when {
        session.repScores.isNotEmpty() -> session.repScores
        session.rows.size > 1 -> session.rows.map { it.score }
        else -> emptyList()
    }
    if (perRep.isEmpty()) {
        Meter(
            fraction = (session.score ?: 0) / 100f,
            color = scoreInk(session.score),
            height = 6.dp,
        )
    } else {
        Row(
            Modifier.fillMaxWidth().height(22.dp),
            horizontalArrangement = Arrangement.spacedBy(3.dp),
            verticalAlignment = Alignment.Bottom,
        ) {
            perRep.forEach { score ->
                Box(
                    Modifier
                        .weight(1f)
                        .height((((score ?: 0) / 100f) * 22).dp.coerceIn(3.dp, 22.dp))
                        .background(scoreInk(score)),
                )
            }
        }
    }
}

@Composable
private fun NextGoalRow(goal: NextGoalData?, onOpenLadder: () -> Unit) {
    if (goal == null || goal.target <= 0) return
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Eyebrow("Siguiente logro", style = mono(12, 0.02f))
        Row(
            Modifier
                .fillMaxWidth()
                .dashedBorder(CardShape)
                .noRipple(onOpenLadder)
                .padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                "${goal.target}",
                style = display(20),
                textAlign = TextAlign.Center,
                modifier = Modifier.width(44.dp),
            )
            Column(
                Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Text(goal.label, style = T.itemTitle)
                Meter(fraction = goal.fraction, color = Tk.ink, height = 6.dp)
            }
            Text("${goal.done}/${goal.target}", style = mono(12, 0.05f, Tk.ink))
        }
    }
}

/** The design's 2px dashed border — Modifier.border cannot dash, so the
 *  outline draws itself behind the content. */
private fun Modifier.dashedBorder(
    shape: Shape,
    color: Color = Tk.border,
    width: Dp = 2.dp,
): Modifier = drawBehind {
    drawOutline(
        shape.createOutline(size, layoutDirection, this),
        color = color,
        style = Stroke(
            width = width.toPx(),
            pathEffect = PathEffect.dashPathEffect(floatArrayOf(4.dp.toPx(), 3.dp.toPx())),
        ),
    )
}

/** «MARTES 17 OCT» — the phone's today, in Spanish, mono caps. */
private fun todayLabel(): String =
    SimpleDateFormat("EEEE d MMM", Locale("es", "ES"))
        .format(Calendar.getInstance().time)
        .uppercase(Locale("es"))

/** 1240 → «1.240», the design's Spanish grouping. */
private fun xpEs(xp: Int): String {
    val symbols = DecimalFormatSymbols(Locale("es")).apply {
        groupingSeparator = '.'
        decimalSeparator = ','
    }
    return DecimalFormat("#,##0", symbols).format(xp.toLong())
}

private fun displayName(name: String): String = name.trim().ifBlank { "atleta" }

private fun initial(name: String): String =
    name.trim().firstOrNull()?.uppercase() ?: "·"

/** "Terminado", a la vista: el aviso no se va hasta que abres el resultado. */
@Composable
private fun NewResultsBanner(count: Int, onOpen: () -> Unit) {
    TkCard(Modifier.noRipple(onOpen), accent = true) {
        Eyebrow(if (count == 1) "Listo" else "Listos", style = T.eyebrowMission)
        Text(
            if (count == 1) "1 análisis nuevo" else "$count análisis nuevos",
            style = T.missionTitle,
            modifier = Modifier.padding(top = 4.dp),
        )
        Text("Toca para verlos", style = T.bodyInk, modifier = Modifier.padding(top = 2.dp))
    }
}
