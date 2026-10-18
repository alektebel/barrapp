package com.barrapp.ui.tracker

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.barrapp.FaultTrend
import com.barrapp.ui.theme.T
import com.barrapp.ui.theme.Tk
import com.barrapp.ui.theme.display
import com.barrapp.ui.theme.mono
import com.barrapp.ui.theme.scoreInk
import kotlin.math.abs
import kotlin.math.ceil

data class TrendPoint(val label: String, val score: Int)

data class PersonalBest(
    val movement: String,
    val metric: String,
    val value: String,
    val unit: String,
    val date: String,
)

data class HistoryRow(
    val date: String,
    val dateLabel: String,
    val movement: String,
    val reps: Int,
    val clips: Int,
    val score: Int?,
)

/**
 * One measured session of a movement: a dot of the quality chart and, when
 * tapped, the session's own card - the history lives inside the points now.
 */
data class SessionPoint(
    /** ISO date, what [onOpenDay] expects. */
    val date: String,
    /** The human one: "8 sept". */
    val dateLabel: String,
    /** The day's quality; null when nothing could be measured. */
    val score: Int?,
    /** Clean (verified) reps of the movement that day. */
    val reps: Int = 0,
    /** The session's note in human words, e.g. its top fault. */
    val note: String = "",
)

/** One movement's chart: its sessions oldest first, its average and records. */
data class MovementSeries(
    val id: String,
    /** Human name: "Dominada". */
    val label: String,
    val sessions: List<SessionPoint>,
    /** Mean quality of the window; the chart draws it as the band. */
    val average: Int? = null,
    /** Change in mean quality against the first half of the window ("+11"). */
    val delta: Int? = null,
    /** Most clean reps of this movement in one day. */
    val maxCleanReps: Int? = null,
    /** Best single rep's quality ever measured. */
    val bestRep: Int? = null,
)

data class ProgressData(
    val averageScore: Int?,
    /** Change in mean score against the window before this one. */
    val averageDelta: Int?,
    val repsThisMonth: Int,
    val bestScore: Int?,
    val bestScoreDate: String,
    val trend: List<TrendPoint>,
    val bests: List<PersonalBest>,
    val faults: List<FaultTrend.Row>,
    val history: List<HistoryRow>,
    /**
     * One chart per movement (design 2d). Empty: the screen folds [history]
     * into series so the page keeps working until this is connected.
     */
    val movements: List<MovementSeries> = emptyList(),
    /** The skill path as vertical steps (design 2d's CAMINO DE SKILLS). */
    val path: List<PathStep> = emptyList(),
)

/**
 * Progreso, design 2d.
 *
 * One chart per movement with the athlete's average as a shaded band, so
 * rising or falling is visible at a glance; two records under it; and the
 * skill path as a vertical line of steps marking the next one and what is
 * missing to get there. The calendar is gone: tapping a chart point opens
 * that session's card - human date and note - which opens the session itself.
 * Everything is a roll-up of measured days; a phone with nothing measured
 * gets an empty page that says so rather than a demo chart.
 */
@Composable
fun TrackerProgress(
    data: ProgressData,
    onOpenDay: (String) -> Unit,
    onOpenLadder: () -> Unit,
    onRecord: () -> Unit,
    modifier: Modifier = Modifier,
    onOpenSkills: () -> Unit = {},
) {
    Column(
        modifier
            .fillMaxWidth()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp)
            .padding(top = 8.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text("PROGRESO", style = T.pageTitle)

        // One chart per movement; until the root supplies them, the screen
        // folds the history rows it already receives into series.
        val movements = data.movements.ifEmpty { movementSeriesFrom(data.history) }

        if (movements.isEmpty()) {
            Camino(data.path, onOpenSkills)
            TkCard {
                Text("SIN DATOS TODAVÍA", style = T.sectionTitle)
                Spacer(Modifier.height(6.dp))
                Text(
                    "El progreso se dibuja a partir de series medidas. Filma la primera " +
                        "y esta página empieza a llenarse.",
                    style = T.bodyS,
                )
                Spacer(Modifier.height(16.dp))
                TkPrimaryButton("Grabar un set", onRecord)
            }
            return@Column
        }

        var selectedId by remember { mutableStateOf<String?>(null) }
        val movement = movements.firstOrNull { it.id == selectedId } ?: movements.first()

        if (movements.size > 1) {
            Row(
                Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                movements.forEach { m ->
                    MovementChip(m.label, on = m.id == movement.id) { selectedId = m.id }
                }
            }
        }

        SlideUp(delayMillis = 150) {
            ChartCard(movement, onOpenDay)
        }

        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            BigTile("MÁX. REPS LIMPIAS", movement.maxCleanReps, Modifier.weight(1f))
            BigTile("MEJOR REP", movement.bestRep, Modifier.weight(1f))
        }

        Camino(data.path, onOpenSkills)
    }
}

/**
 * The path to the goal skill: the real vertical path when connected, the
 * teaser card until then. Shown even before any measured set - it is what
 * the first sets are for.
 */
@Composable
private fun Camino(path: List<PathStep>, onOpenSkills: () -> Unit) {
    if (path.isEmpty()) {
        TkCard(accent = true, modifier = Modifier.noRipple(onOpenSkills)) {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Eyebrow("Tu camino")
                    Text("Qué habilidades llevan a la que quieres, y cuál toca ahora",
                        style = T.bodyS, modifier = Modifier.padding(top = 4.dp))
                }
                Text("VER", style = mono(9, 0.05f, Tk.primary))
            }
        }
        return
    }
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text("CAMINO DE SKILLS", style = mono(12, 0.05f, Tk.muted), modifier = Modifier.weight(1f))
        Box(Modifier.heightIn(min = 48.dp), contentAlignment = Alignment.CenterEnd) {
            Text("VER COMPLETO", style = mono(9, 0.05f, Tk.primary),
                modifier = Modifier.noRipple(onOpenSkills))
        }
    }
    Spacer(Modifier.height(2.dp))
    SkillPathSteps(path)
}

@Composable
private fun MovementChip(label: String, on: Boolean, onClick: () -> Unit) {
    Box(
        Modifier
            .heightIn(min = 48.dp)
            .clip(RoundedCornerShape(50))
            .background(if (on) Tk.ink else Tk.surface)
            .border(2.dp, Tk.border, RoundedCornerShape(50))
            .noRipple(onClick)
            .padding(horizontal = 16.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            label.uppercase(),
            style = mono(12, 0.03f, if (on) Tk.onInk else Tk.ink, FontWeight.SemiBold),
            maxLines = 1,
            overflow = TextOverflow.Clip,
        )
    }
}

@Composable
private fun BigTile(label: String, value: Int?, modifier: Modifier = Modifier) {
    TkCard(modifier = modifier, padding = PaddingValues(horizontal = 12.dp, vertical = 10.dp)) {
        Text(label, style = mono(11, 0.05f, Tk.muted))
        Text(value?.toString() ?: "—", style = T.statValue, modifier = Modifier.padding(top = 2.dp))
    }
}

@Composable
private fun ChartCard(movement: MovementSeries, onOpenDay: (String) -> Unit) {
    var selected by remember(movement.id) { mutableStateOf<Int?>(null) }
    TkCard(padding = PaddingValues(12.dp)) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.Bottom,
        ) {
            Text(chartTitle(movement.sessions), style = mono(12, 0.05f, Tk.muted),
                modifier = Modifier.weight(1f))
            movement.delta?.let { d ->
                Text(if (d > 0) "+$d" else "$d",
                    style = display(18, color = if (d >= 0) Tk.teal else Tk.rose))
            }
        }
        Spacer(Modifier.height(8.dp))
        BandChart(movement, selected) { hit -> selected = if (hit == selected) null else hit }
        Row(Modifier.fillMaxWidth().padding(top = 6.dp)) {
            AxisLabel(movement.sessions.firstOrNull()?.date?.let(::monthAbbrev).orEmpty(),
                TextAlign.Start, Modifier.weight(1f))
            AxisLabel("BANDA = TU MEDIA", TextAlign.Center, Modifier.weight(2f))
            AxisLabel(movement.sessions.lastOrNull()?.date?.let(::monthAbbrev).orEmpty(),
                TextAlign.End, Modifier.weight(1f))
        }
        selected?.let { i ->
            movement.sessions.getOrNull(i)?.let { SessionStrip(it, onOpenDay) }
        }
    }
}

@Composable
private fun AxisLabel(text: String, align: TextAlign, modifier: Modifier = Modifier) {
    if (text.isNotBlank()) {
        Text(text, style = mono(11, 0.05f, Tk.muted), textAlign = align, modifier = modifier)
    }
}

/** The tapped session: human date, what was measured, its note, its clip. */
@Composable
private fun SessionStrip(point: SessionPoint, onOpenDay: (String) -> Unit) {
    Column(
        Modifier.fillMaxWidth().padding(top = 8.dp)
            .clip(InnerShape)
            .background(Tk.card)
            .padding(horizontal = 10.dp, vertical = 8.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(point.dateLabel, style = T.rowTitleSmall)
                Text(sessionMeta(point), style = T.bodyS, modifier = Modifier.padding(top = 2.dp))
            }
            Box(Modifier.heightIn(min = 48.dp), contentAlignment = Alignment.CenterEnd) {
                Text("ABRIR SESIÓN", style = mono(9, 0.05f, Tk.primary),
                    modifier = Modifier.noRipple { onOpenDay(point.date) })
            }
        }
        if (point.note.isNotBlank()) {
            Text(point.note, style = T.bodyS, modifier = Modifier.padding(top = 4.dp))
        }
    }
}

private fun sessionMeta(p: SessionPoint): String = when {
    p.reps <= 0 && p.score == null -> "sin repeticiones medidas"
    p.score == null -> "${p.reps} reps · sin puntuar"
    p.reps <= 0 -> "calidad ${p.score}"
    else -> "${p.reps} reps · ${p.score} pts"
}

/**
 * The design's chart: the athlete's average as a shaded band ("BANDA = TU
 * MEDIA"), the quality of every session as a line, one square dot per session
 * in its band's colour. Tapping near a point selects that session; tapping it
 * again lets it go. A session without a measured score gets no dot - nothing
 * to draw - and its card says so instead of a zero.
 */
@Composable
private fun BandChart(movement: MovementSeries, selected: Int?, onTapPoint: (Int) -> Unit) {
    val sessions = movement.sessions
    var ready by remember { mutableStateOf(false) }
    LaunchedEffect(sessions) { ready = true }
    val reveal by animateFloatAsState(
        targetValue = if (ready) 1f else 0f,
        animationSpec = tween(900),
        label = "bandReveal",
    )
    Canvas(
        Modifier
            .fillMaxWidth()
            .height(120.dp)
            .pointerInput(sessions) {
                detectTapGestures { offset ->
                    BandGeometry(sessions, size.width.toFloat(), size.height.toFloat(), density)
                        .nearest(offset.x)?.let(onTapPoint)
                }
            },
    ) {
        val g = BandGeometry(sessions, size.width, size.height, density)

        // The average as a band: five points either side of the mean.
        g.meanY?.let { center ->
            val half = 5f / g.span * g.innerH
            drawRect(
                Tk.line.copy(alpha = 0.6f),
                topLeft = Offset(0f, center - half),
                size = Size(size.width, half * 2),
            )
        }

        if (g.scored.size >= 2) {
            val line = Path()
            g.scored.forEachIndexed { k, (i, v) ->
                if (k == 0) line.moveTo(g.x(i), g.y(v)) else line.lineTo(g.x(i), g.y(v))
            }
            clipRect(left = 0f, top = 0f, right = size.width * reveal, bottom = size.height) {
                drawPath(
                    line, Tk.ink,
                    style = Stroke(2.5.dp.toPx(), cap = StrokeCap.Round, join = StrokeJoin.Round),
                )
            }
        }

        if (reveal >= 1f) {
            val dot = 8.dp.toPx()
            sessions.forEachIndexed { i, s ->
                val v = s.score ?: return@forEachIndexed
                drawRect(
                    scoreInk(s.score),
                    topLeft = Offset(g.x(i) - dot / 2, g.y(v) - dot / 2),
                    size = Size(dot, dot),
                )
                drawRect(
                    Tk.ink, topLeft = Offset(g.x(i) - dot / 2, g.y(v) - dot / 2),
                    size = Size(dot, dot), style = Stroke(1.5.dp.toPx()),
                )
            }
            selected?.let { i ->
                val v = sessions.getOrNull(i)?.score ?: return@let
                val ring = 14.dp.toPx()
                drawRect(
                    Tk.ink,
                    topLeft = Offset(g.x(i) - ring / 2, g.y(v) - ring / 2),
                    size = Size(ring, ring), style = Stroke(1.5.dp.toPx()),
                )
            }
        }
    }
}

/** Geometry of the band chart, shared by drawing and tapping. */
private class BandGeometry(
    val sessions: List<SessionPoint>,
    widthPx: Float,
    heightPx: Float,
    pxPerDp: Float,
) {
    /** (index, score) of the sessions that were actually measured. */
    val scored: List<Pair<Int, Int>> =
        sessions.mapIndexedNotNull { i, s -> s.score?.let { i to it } }

    private val padX = 8f * pxPerDp
    private val padY = 12f * pxPerDp
    private val innerW = (widthPx - padX * 2).coerceAtLeast(1f)
    val innerH = (heightPx - padY * 2).coerceAtLeast(1f)
    private val lo = ((scored.minOfOrNull { it.second } ?: 0) - 5).coerceAtLeast(0).toFloat()
    private val hi = ((scored.maxOfOrNull { it.second } ?: 100) + 5).toFloat()
    val span = (hi - lo).coerceAtLeast(1f)

    /** Where the average sits, in px; null with nothing measured. */
    val meanY: Float? = scored.takeIf { it.isNotEmpty() }?.let {
        padY + innerH - ((it.map { p -> p.second }.average().toFloat() - lo) / span) * innerH
    }

    fun x(i: Int): Float =
        padX + innerW * (if (sessions.size <= 1) 0.5f else i.toFloat() / (sessions.size - 1))

    fun y(v: Int): Float = padY + innerH - ((v - lo) / span) * innerH

    fun nearest(offsetX: Float): Int? = when {
        sessions.isEmpty() -> null
        else -> sessions.indices.minByOrNull { abs(x(it) - offsetX) }
    }
}

/**
 * Bridge until the root connects [ProgressData.movements]: one series per
 * movement from the history rows the screen already receives, so the page
 * shows the athlete's real data and never a demo chart.
 */
internal fun movementSeriesFrom(history: List<HistoryRow>): List<MovementSeries> {
    if (history.isEmpty()) return emptyList()
    return history.groupBy { it.movement }
        .map { (label, rows) ->
            val ordered = rows.sortedBy { it.date }
            val scores = ordered.mapNotNull { it.score }
            val half = scores.size / 2
            val recent = scores.drop(half).takeIf { it.isNotEmpty() }?.average()?.toInt()
            val earlier = scores.take(half).takeIf { it.isNotEmpty() }?.average()?.toInt()
            MovementSeries(
                id = label,
                label = label,
                sessions = ordered.map { SessionPoint(it.date, it.dateLabel, it.score, it.reps) },
                average = scores.takeIf { it.isNotEmpty() }?.average()?.toInt(),
                delta = if (recent != null && earlier != null) recent - earlier else null,
                maxCleanReps = ordered.maxOfOrNull { it.reps }?.takeIf { it > 0 },
                bestRep = scores.maxOrNull(),
            )
        }
        // Most recent movement first: the one being trained leads the chips.
        .sortedByDescending { it.sessions.lastOrNull()?.date.orEmpty() }
}

/** "CALIDAD MEDIA · 8 SEMANAS" - the weeks the sessions really span. */
internal fun chartTitle(sessions: List<SessionPoint>): String {
    val weeks = sessionWeeks(sessions) ?: return "CALIDAD MEDIA"
    return "CALIDAD MEDIA · $weeks ${if (weeks == 1) "SEMANA" else "SEMANAS"}"
}

private fun sessionWeeks(sessions: List<SessionPoint>): Int? {
    val days = sessions.mapNotNull { dayNumber(it.date) }
    if (days.size < 2) return null
    val span = (days.max() - days.min()).toInt() + 1
    return ceil(span / 7.0).toInt().coerceAtLeast(1)
}

private val MONTHS_ES = listOf(
    "ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC",
)

/** "AGO" / "OCT": the real month of an ISO date, empty when it is not one. */
internal fun monthAbbrev(iso: String): String {
    if (iso.length != 10 || iso[4] != '-' || iso[7] != '-') return ""
    val month = iso.substring(5, 7).toIntOrNull() ?: return ""
    return if (month in 1..12) MONTHS_ES[month - 1] else ""
}

/**
 * Days since the epoch for an ISO yyyy-MM-dd (Howard Hinnant's days_from_civil,
 * so no java.time below API 26), or null when the date is not a real one.
 */
internal fun dayNumber(iso: String): Long? {
    val m = Regex("(\\d{4})-(\\d{2})-(\\d{2})").matchEntire(iso.trim()) ?: return null
    val (ys, ms, ds) = m.destructured
    val month = ms.toInt()
    val day = ds.toInt()
    val year = ys.toInt()
    if (month !in 1..12) return null
    val leap = (year % 4 == 0 && year % 100 != 0) || year % 400 == 0
    val daysInMonth = intArrayOf(31, if (leap) 29 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[month - 1]
    if (day !in 1..daysInMonth) return null
    var y = year
    if (month <= 2) y -= 1
    val era = (if (y >= 0) y else y - 399) / 400
    val yoe = y - era * 400
    val mp = if (month > 2) month - 3 else month + 9
    val doy = (153 * mp + 2) / 5 + day - 1
    val doe = yoe * 365 + yoe / 4 - yoe / 100 + doy
    return era * 146097L + doe - 719468L
}
