package com.barrapp.ui.tracker

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
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
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.barrapp.FaultTrend
import com.barrapp.ui.theme.T
import com.barrapp.ui.theme.Tk
import com.barrapp.ui.theme.mono
import com.barrapp.ui.theme.scoreInk

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
)

/**
 * Progreso.
 *
 * Everything on this page is a roll-up of measured days: the trend line is the
 * day scores in date order, the fault bars are the fault ledger's last four
 * weeks against the four before, and the records are the best days actually
 * recorded. A phone with nothing measured gets an empty page that says so
 * rather than a demo chart.
 */
@Composable
fun TrackerProgress(
    data: ProgressData,
    onOpenDay: (String) -> Unit,
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
        Column {
            Text("BarrApp", style = T.eyebrowWide)
            Text("PROGRESO", style = T.pageTitle)
        }

        if (data.history.isEmpty()) {
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

        StatTiles(
            tiles = listOf(
                Triple(
                    data.averageScore?.toString() ?: "—",
                    "Calidad media",
                    data.averageDelta?.let { if (it >= 0) "+$it" else "$it" } ?: "primera ventana",
                ),
                Triple("${data.repsThisMonth}", "Reps este mes", "medidas"),
                Triple(
                    data.bestScore?.toString() ?: "—",
                    "Mejor día",
                    data.bestScoreDate.ifBlank { "—" },
                ),
            ),
            tint = { i ->
                if (i == 0 && (data.averageDelta ?: 0) < 0) Tk.rose else Tk.teal
            },
        )

        if (data.trend.size >= 2) {
            SlideUp(delayMillis = 200) {
                TkCard {
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Column {
                            Eyebrow("Calidad · ${data.trend.size} días medidos")
                            Text("TENDENCIA DE TÉCNICA", style = T.sectionTitle,
                                modifier = Modifier.padding(top = 2.dp))
                        }
                        Column(horizontalAlignment = Alignment.End) {
                            Text(
                                data.averageScore?.toString() ?: "—",
                                style = T.cardHeadline.copy(color = scoreInk(data.averageScore)),
                            )
                            data.averageDelta?.let { d ->
                                Text(
                                    (if (d >= 0) "↑ +$d pts" else "↓ $d pts"),
                                    style = mono(8, 0.05f, if (d >= 0) Tk.teal else Tk.rose),
                                )
                            }
                        }
                    }
                    Spacer(Modifier.height(16.dp))
                    TrendChart(data.trend)
                }
            }
        }

        if (data.bests.isNotEmpty()) {
            SlideUp(delayMillis = 300) {
                TkCard {
                    Eyebrow("Récords personales")
                    Spacer(Modifier.height(12.dp))
                    data.bests.forEachIndexed { i, pb ->
                        Row(
                            Modifier.fillMaxWidth().padding(vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Column(Modifier.weight(1f)) {
                                Text(pb.movement.uppercase(), style = T.rowTitle)
                                Text(pb.metric, style = T.bodyS)
                            }
                            Column(horizontalAlignment = Alignment.End) {
                                Row(verticalAlignment = Alignment.Bottom) {
                                    Text(pb.value, style = T.cardHeadline.copy(color = Tk.primaryLight))
                                    if (pb.unit.isNotBlank()) {
                                        Text(
                                            " ${pb.unit}",
                                            style = com.barrapp.ui.theme.display(
                                                14, androidx.compose.ui.text.font.FontWeight.Bold,
                                                1f, 0f, Tk.muted,
                                            ),
                                        )
                                    }
                                }
                                Text(pb.date, style = T.eyebrowTiny)
                            }
                        }
                        if (i < data.bests.size - 1) {
                            Box(Modifier.fillMaxWidth().height(1.dp).background(Tk.border))
                        }
                    }
                }
            }
        }

        if (data.faults.isNotEmpty()) {
            SlideUp(delayMillis = 400) {
                TkCard {
                    Row(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Eyebrow("Errores · últimas 4 semanas")
                        val improving = data.faults.count { it.improving }
                        Text(
                            if (improving > data.faults.size / 2) "↓ mejorando" else "seguimiento",
                            style = mono(9, 0.05f,
                                if (improving > data.faults.size / 2) Tk.teal else Tk.muted),
                        )
                    }
                    Spacer(Modifier.height(16.dp))
                    val max = data.faults.maxOf { it.count }
                    data.faults.forEach { row -> FaultBar(row, max) }
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "Cada barra cuenta reps medidas, no sensaciones. Sigue filmando " +
                            "para que la comparación tenga con qué compararse.",
                        style = T.noteNine,
                    )
                }
            }
        }

        SlideUp(delayMillis = 500) {
            TkCard {
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Eyebrow("Historial")
                    Text(
                        "VER ESCALERA",
                        style = mono(9, 0.05f, Tk.primary),
                        modifier = Modifier.noRipple(onOpenLadder),
                    )
                }
                Spacer(Modifier.height(12.dp))
                data.history.forEachIndexed { i, row ->
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .noRipple { onOpenDay(row.date) }
                            .padding(vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        Box(
                            Modifier
                                .size(32.dp)
                                .clip(ChipShape)
                                .background(Tk.primaryA(0.12f)),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text("${row.reps}", style = T.rowTitleSmall.copy(color = Tk.primaryLight))
                        }
                        Column(Modifier.weight(1f)) {
                            Text(row.movement.uppercase(), style = T.rowTitleSmall)
                            Text(
                                "${row.dateLabel} · ${row.clips} " +
                                    if (row.clips == 1) "clip" else "clips",
                                style = T.noteTiny,
                            )
                        }
                        Column(horizontalAlignment = Alignment.End) {
                            Text(
                                row.score?.toString() ?: "—",
                                style = com.barrapp.ui.theme.display(
                                    20, androidx.compose.ui.text.font.FontWeight.Black, 1f, 0f,
                                    scoreInk(row.score),
                                ),
                            )
                            Text("pts", style = T.eyebrowTiny)
                        }
                    }
                    if (i < data.history.size - 1) {
                        Box(Modifier.fillMaxWidth().height(1.dp).background(Tk.border))
                    }
                }
            }
        }
    }
}

/**
 * The design's area chart: a dashed grid, a gradient fill, a 2.5px line and a
 * dot on every measured day, wiped in left to right over 1.2s.
 */
@Composable
private fun TrendChart(points: List<TrendPoint>) {
    var ready by remember { mutableStateOf(false) }
    LaunchedEffect(points) { ready = true }
    val reveal by animateFloatAsState(
        targetValue = if (ready) 1f else 0f,
        animationSpec = tween(1200),
        label = "trend",
    )
    val labels = listOf(0, points.size / 2, points.size - 1).distinct()
    Column {
        Canvas(Modifier.fillMaxWidth().height(110.dp)) {
            val padY = 10.dp.toPx()
            val padX = 6.dp.toPx()
            val innerW = size.width - padX * 2
            val innerH = size.height - padY * 2
            val lo = (points.minOf { it.score } - 5).coerceAtLeast(0)
            val hi = points.maxOf { it.score } + 5
            val span = (hi - lo).coerceAtLeast(1)
            fun px(i: Int) = padX + innerW * (i.toFloat() / (points.size - 1).coerceAtLeast(1))
            fun py(v: Int) = padY + innerH - ((v - lo).toFloat() / span) * innerH

            // grid — 3 dashed rules, the design's 25/50/75
            listOf(0.25f, 0.5f, 0.75f).forEach { t ->
                val y = padY + innerH * t
                var x = padX
                val on = 3.dp.toPx()
                val gap = 4.dp.toPx()
                while (x < size.width - padX) {
                    drawLine(Tk.border, Offset(x, y),
                        Offset(minOf(x + on, size.width - padX), y), 1.dp.toPx())
                    x += on + gap
                }
            }

            val line = Path().apply {
                points.forEachIndexed { i, p ->
                    if (i == 0) moveTo(px(i), py(p.score)) else lineTo(px(i), py(p.score))
                }
            }
            val area = Path().apply {
                addPath(line)
                lineTo(px(points.size - 1), size.height - padY)
                lineTo(px(0), size.height - padY)
                close()
            }
            clipRect(left = 0f, top = 0f, right = padX + innerW * reveal, bottom = size.height) {
                drawPath(
                    area,
                    Brush.verticalGradient(
                        listOf(Tk.primaryA(0.35f), Tk.primaryA(0.02f)),
                        startY = padY, endY = size.height - padY,
                    ),
                )
                drawPath(
                    line, Tk.primary,
                    style = Stroke(2.5.dp.toPx(), cap = StrokeCap.Round, join = StrokeJoin.Round),
                )
            }
            if (reveal >= 1f) {
                points.forEachIndexed { i, p ->
                    drawCircle(Tk.primaryLight, 3.dp.toPx(), Offset(px(i), py(p.score)))
                }
            }
        }
        Row(Modifier.fillMaxWidth().padding(top = 4.dp)) {
            labels.forEachIndexed { n, i ->
                Text(
                    points[i].label,
                    style = mono(8, 0.05f),
                    modifier = Modifier.weight(1f),
                    textAlign = when (n) {
                        0 -> TextAlign.Start
                        labels.size - 1 -> TextAlign.End
                        else -> TextAlign.Center
                    },
                )
            }
        }
    }
}

@Composable
private fun FaultBar(row: FaultTrend.Row, max: Int) {
    val ink = when {
        row.improving -> Tk.teal
        row.delta > 0 -> Tk.amber
        else -> Tk.primary
    }
    Column(Modifier.fillMaxWidth().padding(bottom = 12.dp)) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(com.barrapp.faultEs(row.fault), style = T.bodyInk, modifier = Modifier.weight(1f))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    when {
                        row.previous == 0 -> "primera ventana"
                        row.delta < 0 -> "↓ ${-row.delta} reps"
                        row.delta > 0 -> "↑ ${row.delta} reps"
                        else -> "igual"
                    },
                    style = mono(9, 0.05f, ink),
                )
                Text("${row.count}", style = mono(9, 0.05f))
            }
        }
        Spacer(Modifier.height(6.dp))
        Meter(
            fraction = row.count.toFloat() / max.coerceAtLeast(1),
            color = ink,
            height = 6.dp,
        )
    }
}
