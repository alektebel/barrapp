package com.barrapp.ui.tracker

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.barrapp.Gamification
import com.barrapp.ui.theme.T
import com.barrapp.ui.theme.Tk
import com.barrapp.ui.theme.body
import com.barrapp.ui.theme.mono
import com.barrapp.ui.theme.scoreInk
import com.barrapp.ui.theme.scoreLabel

/** One movement's share of the last training day — the design's "SER n" row,
 *  carrying what this app can actually attribute: a movement, not a set. */
data class SessionRowData(val label: String, val score: Int?, val reps: Int)

data class LastSessionData(
    val movement: String,
    val date: String,
    val reps: Int,
    val score: Int?,
    val rows: List<SessionRowData>,
    /** The fault the day showed most, and how many reps showed it. */
    val topFault: Pair<String, Int>?,
)

data class HomeData(
    val name: String,
    val standing: Gamification.Standing,
    val week: List<Gamification.WeekDay>,
    val mission: Gamification.Mission,
    val lastSession: LastSessionData?,
    val badges: List<Gamification.Badge>,
)

/**
 * Inicio.
 *
 * The mockup's home, card for card. What differs is only ever the source: the
 * streak, the XP bar, the week strip and the badges read measured training, so
 * a phone that has filmed nothing shows zeroes and an empty last-session card
 * rather than someone else's 18-day streak.
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
        XpCard(data.standing)
        MissionCard(data.mission, onRecord)
        WeekCard(data.week, onOpenCalendar)
        LastSessionCard(data.lastSession, onOpenSession, onOpenCoach, onRecord)
        BadgesCard(data.badges, onOpenLadder)
    }
}

@Composable
private fun Greeting(data: HomeData) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top) {
        Column(Modifier.weight(1f)) {
            Text("Buenas,", style = T.eyebrowWide)
            Text(data.name.uppercase(), style = T.name)
            Row(
                Modifier.padding(top = 2.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Text("Lv.${data.standing.level}", style = mono(10, 0.05f, Tk.primary))
                Text("·", style = mono(10, 0f, Tk.border))
                Text(data.standing.title, style = mono(10))
            }
        }
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Box(
                Modifier
                    .size(56.dp)
                    .clip(CardShape)
                    .background(Tk.amberA(0.1f))
                    .border(1.5.dp, Tk.amberA(0.25f), CardShape),
                contentAlignment = Alignment.Center,
            ) {
                Text("🔥", style = body(24, Tk.amber))
            }
            Text("${data.standing.streak}", style = T.streak)
            Text("RACHA", style = T.eyebrowTiny)
        }
    }
}

@Composable
private fun XpCard(standing: Gamification.Standing) {
    TkCard {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Eyebrow("XP al siguiente nivel")
            Text(
                "${standing.xp} / ${standing.maxXp}",
                style = mono(10, 0.05f, Tk.primaryLight),
            )
        }
        Spacer(Modifier.height(8.dp))
        Box(
            Modifier
                .fillMaxWidth()
                .height(6.dp)
                .clip(RoundedCornerShape(3.dp))
                .background(Tk.border),
        ) {
            Box(
                Modifier
                    .fillMaxWidth(standing.fraction)
                    .height(6.dp)
                    .clip(RoundedCornerShape(3.dp))
                    .background(Brush.horizontalGradient(listOf(Tk.primary, Tk.primaryLight))),
            )
        }
        Spacer(Modifier.height(6.dp))
        Text(
            if (standing.empty)
                "Aún sin XP. Cada rep medida suma; filma una serie para empezar."
            else "${standing.toNext} XP para el nivel ${standing.level + 1} — ${standing.nextTitle}",
            style = T.noteNine,
        )
    }
}

@Composable
private fun MissionCard(mission: Gamification.Mission, onRecord: () -> Unit) {
    TkCard(accent = true, modifier = Modifier.noRipple(onRecord)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.width(4.dp).height(16.dp)
                .clip(RoundedCornerShape(2.dp)).background(Tk.primary))
            Spacer(Modifier.width(8.dp))
            Eyebrow("Misión de hoy", style = T.eyebrowMission)
        }
        Spacer(Modifier.height(12.dp))
        Text(
            "${mission.targetReps} reps · ${mission.movement}".uppercase(),
            style = T.missionTitle,
        )
        Spacer(Modifier.height(2.dp))
        Text("Foco: ${mission.focus}", style = T.bodyS)
        Spacer(Modifier.height(16.dp))
        // One segment per rep the standard asks for, filled by what was
        // measured today. Never more segments than the standard, never more
        // filled than were actually measured.
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            repeat(mission.targetReps.coerceIn(1, 12)) { i ->
                val filled = i < mission.doneReps
                Box(
                    Modifier
                        .weight(1f)
                        .height(6.dp)
                        .clip(RoundedCornerShape(3.dp))
                        .background(if (filled) Tk.primary else Tk.border),
                )
            }
        }
        Spacer(Modifier.height(8.dp))
        Text(
            if (mission.complete)
                "Misión cumplida · ${mission.doneReps} reps medidas hoy"
            else "${mission.doneReps} de ${mission.targetReps} reps medidas hoy · " +
                "+${mission.xpReward} XP al terminar",
            style = T.eyebrowNine,
        )
    }
}

@Composable
private fun WeekCard(week: List<Gamification.WeekDay>, onOpenCalendar: () -> Unit) {
    TkCard(modifier = Modifier.noRipple(onOpenCalendar)) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Eyebrow("Esta semana")
            Text("VER MES", style = mono(9, 0.05f, Tk.primary))
        }
        Spacer(Modifier.height(12.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            week.forEach { day ->
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text(day.label, style = T.eyebrowNine)
                    Box(
                        Modifier
                            .size(32.dp)
                            .clip(CircleShape)
                            .background(
                                when {
                                    day.done -> Tk.primary
                                    day.today -> Color.Transparent
                                    else -> Tk.card
                                }
                            )
                            .then(
                                if (day.today && !day.done)
                                    Modifier.border(1.5.dp, Tk.primaryA(0.5f), CircleShape)
                                else Modifier
                            ),
                        contentAlignment = Alignment.Center,
                    ) {
                        when {
                            day.done -> androidx.compose.foundation.Canvas(Modifier.size(12.dp)) {
                                drawCheck(Color.White)
                            }
                            day.today -> Box(Modifier.size(6.dp).background(Tk.primary, CircleShape))
                        }
                    }
                    Text(
                        day.score?.toString().orEmpty(),
                        style = mono(8, 0.05f, scoreInk(day.score)),
                    )
                }
            }
        }
    }
}

@Composable
private fun LastSessionCard(
    session: LastSessionData?,
    onOpenSession: () -> Unit,
    onOpenCoach: () -> Unit,
    onRecord: () -> Unit,
) {
    if (session == null) {
        // Nothing measured yet. The mockup's literal here was a full record —
        // an exercise, a rep count and a score — which a new user reads as
        // their own training. An empty state says less and lies none.
        TkCard(modifier = Modifier.noRipple(onRecord)) {
            Eyebrow("Última sesión")
            Spacer(Modifier.height(4.dp))
            Text("SIN SESIONES", style = T.sectionTitle)
            Spacer(Modifier.height(4.dp))
            Text(
                "Filma una serie y barra la medirá. Tu última sesión aparecerá aquí.",
                style = T.bodyS,
            )
        }
        return
    }
    TkCard(modifier = Modifier.noRipple(onOpenSession)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top) {
            Column(Modifier.weight(1f)) {
                Eyebrow("Última sesión")
                Text(session.movement.uppercase(), style = T.sectionTitle)
                Text("${session.date} · ${session.reps} reps", style = T.bodyS)
            }
            Column(horizontalAlignment = Alignment.End) {
                Text(
                    session.score?.toString() ?: "—",
                    style = T.bigScore.copy(color = scoreInk(session.score)),
                )
                Text("CALIDAD MEDIA", style = T.eyebrowTiny)
                Text(
                    scoreLabel(session.score),
                    style = mono(8, 0.05f, scoreInk(session.score)),
                )
            }
        }
        Spacer(Modifier.height(12.dp))
        session.rows.forEach { row ->
            Row(
                Modifier.fillMaxWidth().padding(bottom = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Text(
                    row.label.uppercase(),
                    style = T.eyebrowNine,
                    modifier = Modifier.width(58.dp),
                    maxLines = 1,
                )
                Meter(
                    fraction = (row.score ?: 0) / 100f,
                    color = scoreInk(row.score),
                    height = 4.dp,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    row.score?.toString() ?: "—",
                    style = mono(9, 0.05f, scoreInk(row.score)),
                    modifier = Modifier.width(20.dp),
                    textAlign = TextAlign.End,
                )
                Text(
                    "${row.reps} reps",
                    style = T.eyebrowTiny,
                    modifier = Modifier.width(44.dp),
                    textAlign = TextAlign.End,
                )
            }
        }
        session.topFault?.let { (fault, count) ->
            Row(
                Modifier
                    .fillMaxWidth()
                    .clip(InnerShape)
                    .background(Tk.amberA(0.08f))
                    .border(1.dp, Tk.amberA(0.2f), InnerShape)
                    .noRipple(onOpenCoach)
                    .padding(horizontal = 12.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                androidx.compose.foundation.Canvas(Modifier.size(14.dp)) { drawWarning(Tk.amber) }
                Text(
                    "$fault · $count reps afectadas",
                    style = body(12, Tk.amber),
                    modifier = Modifier.weight(1f),
                )
                Text("VER COACH →", style = T.eyebrowNine)
            }
        }
    }
}

@Composable
private fun BadgesCard(badges: List<Gamification.Badge>, onOpenLadder: () -> Unit) {
    TkCard {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Eyebrow("Logros")
            Text(
                "VER ESCALERA",
                style = mono(9, 0.05f, Tk.primary),
                modifier = Modifier.noRipple(onOpenLadder),
            )
        }
        Spacer(Modifier.height(12.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            badges.forEach { badge ->
                Column(
                    Modifier.weight(1f),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Box(
                        Modifier
                            .size(48.dp)
                            // Emoji are colour glyphs, so an alpha on the text
                            // colour leaves a locked badge looking earned. The
                            // whole tile fades instead.
                            .alpha(if (badge.unlocked) 1f else 0.35f)
                            .clip(CardShape)
                            .background(if (badge.unlocked) Tk.primaryA(0.12f) else Tk.locked)
                            .border(
                                1.dp,
                                if (badge.unlocked) Tk.primaryA(0.3f) else Tk.border,
                                CardShape,
                            ),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(badge.icon, style = body(22, Tk.ink))
                    }
                    Text(
                        badge.label,
                        style = mono(7, 0f, if (badge.unlocked) Tk.muted else Tk.faint, line = 1.2f),
                        textAlign = TextAlign.Center,
                    )
                }
            }
        }
    }
}
