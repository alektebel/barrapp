package com.barrapp.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.barrapp.Progression
import com.barrapp.data.DayEntry
import com.barrapp.ui.parts.Eyebrow
import com.barrapp.ui.parts.Panel
import com.barrapp.ui.parts.Pill
import com.barrapp.ui.parts.bandColor
import kotlin.math.abs

/**
 * Progress, and the two honest ways to show it.
 *
 * The headline is **reps you can actually measure per session**, not the score.
 * That is deliberate and it is the most useful number this app has: the whole
 * measurement rests on having enough clean reps in a session to tell your
 * rep-to-rep variation from a real change, and until that count is up, no
 * comparison between sessions means anything. It is also the number entirely
 * within your control - it is a filming and volume decision, not a strength one.
 *
 * The score trend is shown underneath, greyed until there is enough behind it,
 * with the gap to the floor stated in plain words rather than implied by a
 * flat line.
 */
@Composable
fun InsightPane(
    days: List<DayEntry>,
    repTarget: Int,
    weeklyNote: String?,
    onOpenCoach: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val measured = days.filter { it.measured }.sortedBy { it.date }
    val readySessions = days.count { it.reps >= MIN_REPS_FOR_COMPARISON }
    val progression = Progression.focus(days)

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        // The progression verdict goes first because it is the decision the
        // athlete came for. Everything below it is supporting evidence.
        if (progression?.step != null) {
            item { ProgressionCard(progression) }
        }

        item { DayByDayPanel(days) }
        item { PromotionReadinessPanel(days) }

        item {
            Panel {
                Eyebrow("Sesiones comparables")
                Spacer(Modifier.height(10.dp))
                Row(verticalAlignment = Alignment.Bottom) {
                    Text(
                        readySessions.toString(),
                        fontFamily = FontFamily.Monospace,
                        fontWeight = FontWeight.SemiBold,
                        style = MaterialTheme.typography.displaySmall,
                        color = MaterialTheme.colorScheme.primary,
                    )
                    Spacer(Modifier.size(8.dp))
                    Text(
                        "de ${days.size} registradas",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(bottom = 5.dp),
                    )
                }
                Spacer(Modifier.height(10.dp))
                Text(
                    if (readySessions >= 2)
                        "Dos sesiones de $MIN_REPS_FOR_COMPARISON o más repeticiones es lo que hace " +
                            "falta para distinguir un cambio real de tu variación normal " +
                            "entre repeticiones. Ya lo tienes."
                    else
                        "Una sesión necesita $MIN_REPS_FOR_COMPARISON repeticiones medidas para que " +
                            "su mediana signifique algo, y dos sesiones así antes de poder " +
                            "comparar nada. Apunta a $repTarget repeticiones en una serie.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (days.isNotEmpty()) {
                    Spacer(Modifier.height(16.dp))
                    RepsPerSession(days.sortedBy { it.date }, repTarget)
                }
            }
        }

        item {
            Panel {
                Eyebrow("Puntuación de la sesión")
                Spacer(Modifier.height(4.dp))
                if (measured.size < 2) {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "Hacen falta dos sesiones medidas para que una línea aquí signifique algo.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    val first = measured.first().score ?: 0
                    val last = measured.last().score ?: 0
                    val delta = last - first
                    Spacer(Modifier.height(10.dp))
                    Row(verticalAlignment = Alignment.Bottom) {
                        Text(
                            last.toString(),
                            fontFamily = FontFamily.Monospace,
                            fontWeight = FontWeight.SemiBold,
                            style = MaterialTheme.typography.displaySmall,
                            color = bandColor(measured.last().band),
                        )
                        Spacer(Modifier.size(10.dp))
                        Pill(
                            if (delta == 0) "igual"
                            else "${if (delta > 0) "+" else "−"}${abs(delta)} desde el ${measured.first().date.takeLast(5)}",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Spacer(Modifier.height(14.dp))
                    ScoreTrend(measured)
                    Spacer(Modifier.height(12.dp))
                    Text(
                        "Una puntuación base a partir del recorrido, el control de la bajada y los " +
                            "atascos. No es una nota de técnica, y una diferencia de este " +
                            "tamaño no se ha contrastado con tu propia variación.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        item {
            Panel {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Eyebrow("Resumen semanal", modifier = Modifier.weight(1f))
                    if (weeklyNote != null) {
                        Box(
                            Modifier.size(7.dp).clip(CircleShape)
                                .background(MaterialTheme.colorScheme.primary)
                        )
                    }
                }
                Spacer(Modifier.height(10.dp))
                Text(
                    weeklyNote ?: "Tu primer resumen semanal llega cuando haya una semana de " +
                        "entrenamiento detrás. Recibirás una notificación.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (weeklyNote != null) MaterialTheme.colorScheme.onSurface
                    else MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(16.dp))
                HorizontalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f))
                Spacer(Modifier.height(14.dp))
                FilledTonalButton(onClick = onOpenCoach, modifier = Modifier.fillMaxWidth()) {
                    Text("Pregunta sobre tu entrenamiento")
                }
            }
        }
    }
}

const val MIN_REPS_FOR_COMPARISON = 3

/**
 * Reps per session as bars, with the comparison floor drawn across them.
 *
 * The floor line is the point: a bar under it is a session that cannot take
 * part in any comparison, and seeing three of those in a row says more than a
 * paragraph would.
 */
@Composable
private fun RepsPerSession(days: List<DayEntry>, target: Int) {
    val shown = days.takeLast(12)
    if (shown.isEmpty()) return
    val ceiling = maxOf(shown.maxOf { it.reps }, target, MIN_REPS_FOR_COMPARISON) + 1
    val primary = MaterialTheme.colorScheme.primary
    val outline = MaterialTheme.colorScheme.outline
    val dim = MaterialTheme.colorScheme.onSurfaceVariant

    Column {
        Canvas(Modifier.fillMaxWidth().height(76.dp)) {
            // Pixels, not dp - see RepTrace in parts/Parts.kt.
            val hair = 1.dp.toPx()
            val dashOn = 3.dp.toPx()
            val dashGap = 4.dp.toPx()
            val radius = 3.dp.toPx()
            val minBar = 3.dp.toPx()
            val slot = size.width / shown.size
            val barW = minOf(slot * 0.55f, 18.dp.toPx())
            val floorY = size.height - (MIN_REPS_FOR_COMPARISON.toFloat() / ceiling) * size.height

            var x = 0f
            while (x < size.width) {
                drawLine(
                    color = dim.copy(alpha = 0.55f),
                    start = Offset(x, floorY),
                    end = Offset(minOf(x + dashOn, size.width), floorY),
                    strokeWidth = hair,
                )
                x += dashOn + dashGap
            }
            shown.forEachIndexed { i, day ->
                // A minimum height for any non-zero session. One high-volume day
                // otherwise flattens a 1-rep day to nothing, and "I did one rep"
                // and "I did none" are the two facts this chart exists to
                // separate. The scale stays linear - a bar chart that bends its
                // axis to look tidy is lying about the ratio it is drawing.
                val raw = (day.reps.toFloat() / ceiling) * size.height
                val h = if (day.reps > 0) maxOf(raw, minBar) else 0f
                val left = i * slot + (slot - barW) / 2f
                drawRoundRect(
                    color = if (day.reps >= MIN_REPS_FOR_COMPARISON) primary
                    else outline,
                    topLeft = Offset(left, size.height - h),
                    size = Size(barW, h),
                    cornerRadius = CornerRadius(radius, radius),
                )
            }
        }
        Spacer(Modifier.height(6.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(
                shown.first().date.takeLast(5),
                style = MaterialTheme.typography.labelSmall,
                color = dim,
            )
            Text(
                "mínimo $MIN_REPS_FOR_COMPARISON reps",
                style = MaterialTheme.typography.labelSmall,
                color = dim,
            )
            Text(
                shown.last().date.takeLast(5),
                style = MaterialTheme.typography.labelSmall,
                color = dim,
            )
        }
    }
}

/** Score over the measured sessions, with each session as a point. Points and
 *  not just a line, so the sample size cannot be mistaken for a smooth trend. */
@Composable
private fun ScoreTrend(measured: List<DayEntry>) {
    val colour = MaterialTheme.colorScheme.primary
    val dim = MaterialTheme.colorScheme.outline
    Canvas(Modifier.fillMaxWidth().height(72.dp)) {
        // Pixels, not dp - see RepTrace in parts/Parts.kt.
        val hair = 1.dp.toPx()
        val line = 2.dp.toPx()
        val dot = 3.dp.toPx()
        val edge = 6.dp.toPx()
        val scores = measured.map { (it.score ?: 0).toFloat() }
        val lo = minOf(scores.min() - 6f, 100f)
        val hi = maxOf(scores.max() + 6f, lo + 1f)
        val pad = edge
        fun y(v: Float) = size.height - pad - (v - lo) / (hi - lo) * (size.height - 2 * pad)
        fun x(i: Int) =
            if (scores.size == 1) size.width / 2f
            else i.toFloat() / (scores.size - 1) * (size.width - 2 * edge) + edge

        drawLine(
            color = dim.copy(alpha = 0.5f),
            start = Offset(0f, size.height - pad),
            end = Offset(size.width, size.height - pad),
            strokeWidth = hair,
        )
        val path = Path().apply {
            moveTo(x(0), y(scores[0]))
            for (i in 1 until scores.size) lineTo(x(i), y(scores[i]))
        }
        drawPath(path, colour, style = Stroke(width = line, cap = StrokeCap.Round))
        scores.forEachIndexed { i, v ->
            drawCircle(colour, radius = dot, center = Offset(x(i), y(v)))
        }
    }
}


/**
 * The progression verdict.
 *
 * Structured so the parts cannot be confused with each other, because that
 * distinction is the product: the **standard** is a published convention, the
 * **evidence** is measured, and only the evidence carries a trace. An app that
 * blurs the two is asking to be believed rather than checked.
 */
/**
 * What each training day was expected to deliver, and whether it did.
 *
 * The expectation is not invented per day: it is the movement's published
 * standard, and it does not move until the standard is cleared. A day either
 * cleared it - enough verified reps at the quality bar - or it did not, and
 * the gap is named. Days whose movement is not on the ladder are shown too,
 * honestly unjudged: barra has nothing to referee them against.
 */
@Composable
private fun DayByDayPanel(days: List<DayEntry>) {
    val recent = days.sortedByDescending { it.date }.take(14)
    Panel {
        Eyebrow("Día a día")
        Spacer(Modifier.height(8.dp))
        if (recent.isEmpty()) {
            Text(
                "Aún no hay sesiones. La marca aparece cuando se mida algo.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            return@Panel
        }
        Text(
            "Un día supera la marca con suficientes repeticiones verificadas a la calidad " +
                "que pide el estándar. La marca no se mueve hasta que se supera el estándar.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(12.dp))
        recent.forEach { day ->
            val judged = dayJudgements(day)
            if (judged.isEmpty()) {
                Row(
                    Modifier.fillMaxWidth().padding(vertical = 5.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        day.date,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.weight(1f),
                    )
                    Pill("fuera de la escalera", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            } else {
                judged.forEach { j -> JudgedDayRow(day.date, j) }
            }
        }
    }
}

private data class DayJudgement(
    val movement: String,
    val label: String,
    val verified: Int,
    val score: Int?,
    val step: Progression.Step?,
) {
    val cleared: Boolean
        get() = step != null && verified >= step.reps && (score ?: 0) >= step.quality
    val shortfall: Int
        get() = step?.let { (step.reps - verified).coerceAtLeast(0) } ?: 0
}

/** Per movement, what the day delivered against the standard. Days recorded
 *  before the per-movement breakdown existed are judged at day level, which
 *  is the best evidence they carry. */
private fun dayJudgements(day: DayEntry): List<DayJudgement> {
    if (day.byMovement.isEmpty()) {
        val step = Progression.LADDER[day.exercise] ?: return emptyList()
        return listOf(DayJudgement(day.exercise, day.exerciseLabel.ifBlank { day.exercise },
            day.reps, day.score, step))
    }
    return day.byMovement.values.mapNotNull { m ->
        val step = Progression.LADDER[m.exercise] ?: return@mapNotNull null
        DayJudgement(m.exercise, m.label.ifBlank { m.exercise }, m.verified, m.score, step)
    }
}

@Composable
private fun JudgedDayRow(date: String, j: DayJudgement) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(
                j.label.replaceFirstChar { it.uppercase() },
                style = MaterialTheme.typography.bodyMedium,
            )
            Text(
                "$date · ${j.verified} verificadas con ${j.score ?: "—"}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (j.cleared) {
            Pill("marca superada", color = MaterialTheme.colorScheme.primary)
        } else if (j.step != null) {
            Pill(
                if (j.shortfall > 0) "faltan ${j.shortfall} rep${if (j.shortfall == 1) "" else "s"}"
                else "por debajo de la marca",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/**
 * Where each trained movement stands for promotion, at a glance.
 *
 * The full verdict for the movement you actually train sits above; these are
 * the other ladders, so "ready or not" is never hidden behind a pane. A
 * movement earns its step on the required number of separate qualifying days.
 */
@Composable
private fun PromotionReadinessPanel(days: List<DayEntry>) {
    val verdicts = Progression.LADDER.keys
        .map { Progression.assess(it, days) }
        .filter { it.bestReps > 0 }
        .sortedByDescending { it.bestReps }
    if (verdicts.isEmpty()) return
    Panel {
        Eyebrow("¿Listo para subir de nivel?")
        Spacer(Modifier.height(10.dp))
        verdicts.forEachIndexed { i, v ->
            val step = v.step ?: return@forEachIndexed
            if (i > 0) {
                Spacer(Modifier.height(10.dp))
                HorizontalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = 0.3f))
                Spacer(Modifier.height(10.dp))
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(
                        v.label.replaceFirstChar { it.uppercase() },
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Text(
                        v.headline,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Pill(
                    if (v.ready) "listo: ${step.towardsLabel}"
                    else "${v.qualifyingDays.size} de ${step.days} días",
                    color = if (v.ready) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (!v.ready && v.missing.isNotBlank()) {
                Spacer(Modifier.height(4.dp))
                Text(
                    v.missing,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.primary,
                )
            }
        }
    }
}

@Composable
private fun ProgressionCard(v: Progression.Verdict) {
    val step = v.step ?: return
    Panel {
        Eyebrow(if (v.ready) "Conseguido" else "En camino a")
        Spacer(Modifier.height(8.dp))
        Text(
            step.towardsLabel,
            style = MaterialTheme.typography.headlineMedium,
            color = if (v.ready) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.onSurface,
        )
        Spacer(Modifier.height(4.dp))
        Text(
            "desde ${v.label.lowercase()}",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        Spacer(Modifier.height(14.dp))
        Row(verticalAlignment = Alignment.Bottom) {
            Text(
                v.bestReps.toString(),
                fontFamily = FontFamily.Monospace,
                fontWeight = FontWeight.SemiBold,
                style = MaterialTheme.typography.displaySmall,
                color = if (v.bestReps >= step.reps) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.onSurface,
            )
            Spacer(Modifier.size(8.dp))
            Text(
                "de ${step.reps} repeticiones verificadas",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(bottom = 5.dp),
            )
        }
        Spacer(Modifier.height(4.dp))
        Text(
            "Verificada significa que barra midió la repetición, no que la hicieras. " +
                "Una repetición que no pudo medir no cuenta ni a favor ni en contra.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        Spacer(Modifier.height(14.dp))
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        Spacer(Modifier.height(12.dp))

        Eyebrow("El estándar")
        Spacer(Modifier.height(6.dp))
        Text(v.standard, style = MaterialTheme.typography.bodyMedium)
        Spacer(Modifier.height(4.dp))
        Text(
            "Una convención, no una medición. Está escrita para que puedas " +
                "discrepar de ella.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        Spacer(Modifier.height(12.dp))
        Eyebrow("Tu evidencia")
        Spacer(Modifier.height(6.dp))
        Text(v.evidence, style = MaterialTheme.typography.bodyMedium)

        if (v.missing.isNotBlank()) {
            Spacer(Modifier.height(10.dp))
            Text(
                v.missing,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.primary,
            )
        }
        if (v.ready && !step.targetMeasurable) {
            Spacer(Modifier.height(10.dp))
            Text(
                step.note,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
