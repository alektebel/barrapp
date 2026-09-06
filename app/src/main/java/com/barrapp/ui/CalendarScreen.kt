package com.barrapp.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.border
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import com.barrapp.ui.theme.Nocturne
import com.barrapp.ui.theme.N

/** Appendix C — a filled day is a measured day, painted the colour of its
 *  technique; a dashed day is one filmed where nothing came out. */
@Composable
fun CalendarScreen(
    month: String,
    year: String,
    days: List<CalDay>,
    summaryMeasured: String,
    summaryReps: String,
    rows: List<CalRow>,
    onOpenDay: (Int) -> Unit,
) {
    Column(Modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.Bottom) {
            androidx.compose.material3.Text(month, style = N.pageTitle)
            Spacer(Modifier.width(10.dp))
            androidx.compose.material3.Text(year, style = N.pageTitleMuted)
            Spacer(Modifier.weight(1f))
            MonthArrow("‹")
            Spacer(Modifier.width(6.dp))
            MonthArrow("›")
        }
        androidx.compose.material3.Text(
            "A filled day is a measured day, painted the colour of its technique. " +
                "A dashed day is one you filmed where nothing came out.",
            style = N.bodyNote, modifier = Modifier.padding(top = 6.dp),
        )

        // 7 columns, gap 5, Monday first; leading blanks follow the month
        Row(Modifier.fillMaxWidth().padding(top = 16.dp),
            horizontalArrangement = Arrangement.spacedBy(5.dp)) {
            listOf("M", "T", "W", "T", "F", "S", "S").forEach {
                androidx.compose.material3.Text(
                    it, style = N.eyebrowMuted.copy(color = Nocturne.fgA(0.4f)),
                    modifier = Modifier.weight(1f).fillMaxWidth(),
                    textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                )
            }
        }
        // One Row per week. A month is 28-31 cells; laying them all in one Row
        // with weight(1f) shrank every cell to a fifth of its share and turned
        // the calendar into a strip of unreadable squares. The blanks belong to
        // the first week only - they are the days of the previous month.
        val blanks = days.firstOrNull()?.leadingBlanks ?: 0
        val firstWeek = minOf(7 - blanks, days.size)
        var cursor = 0
        while (cursor < days.size) {
            val inWeek = if (cursor == 0) firstWeek else minOf(7, days.size - cursor)
            Row(Modifier.fillMaxWidth().padding(top = 5.dp),
                horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                if (cursor == 0) {
                    repeat(blanks) {
                        Spacer(Modifier.weight(1f).aspectRatio(1f))
                    }
                }
                repeat(inWeek) {
                    DayCell(days[cursor + it], Modifier.weight(1f), onOpenDay)
                }
            }
            cursor += inWeek
        }

        NocturneDivider(Modifier.padding(vertical = 20.dp))

        Row(verticalAlignment = Alignment.Bottom) {
            androidx.compose.material3.Text(summaryMeasured.uppercase(), style = N.eyebrowMuted)
            Spacer(Modifier.weight(1f))
            androidx.compose.material3.Text(summaryReps, style = N.sessionMeta
                .copy(color = Nocturne.fgA(0.45f)))
        }
        rows.forEachIndexed { i, row ->
            Row(
                Modifier.fillMaxWidth().padding(top = if (i == 0) 10.dp else 7.dp)
                    .background(Nocturne.surface, RoundedCornerShape(8.dp))
                    .padding(horizontal = 12.dp, vertical = 11.dp)
                    .then(if (row.clickable) NoRipple.noRipple({ onOpenDay(row.day) })
                          else Modifier),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(Modifier.width(3.dp).height(30.dp)
                    .background(row.color, RoundedCornerShape(2.dp)))
                Spacer(Modifier.width(11.dp))
                Column(Modifier.weight(1f)) {
                    androidx.compose.material3.Text(row.title, style = N.listTitle)
                    androidx.compose.material3.Text(row.subtitle, style = N.listSub)
                }
                androidx.compose.material3.Text(
                    row.score, style = N.listScore.copy(color = row.scoreColor),
                )
            }
        }
    }
}

@Composable
private fun MonthArrow(glyph: String) {
    Box(
        Modifier.size(26.dp)
            .border0(1.dp, Nocturne.fgA(0.16f), RoundedCornerShape(8.dp)),
        contentAlignment = Alignment.Center,
    ) {
        androidx.compose.material3.Text(glyph, style = N.monthCell
            .copy(color = Nocturne.fgA(0.6f)))
    }
}

@Composable
private fun DayCell(d: CalDay, modifier: Modifier, onOpenDay: (Int) -> Unit) {
    val shape = RoundedCornerShape(8.dp)
    Box(
        modifier.aspectRatio(1f),
        contentAlignment = Alignment.Center,
    ) {
        when (d.kind) {
            CalKind.PLAIN -> Box(
                Modifier.fillMaxWidth().aspectRatio(1f)
                    .border0(0.dp, Color.Transparent, shape),
                contentAlignment = Alignment.Center,
            ) {
                androidx.compose.material3.Text("${d.n}", style = N.cellDay)
            }
            CalKind.DASHED -> Box(
                Modifier.fillMaxWidth().aspectRatio(1f),
                contentAlignment = Alignment.Center,
            ) {
                Canvas(Modifier.fillMaxWidth().aspectRatio(1f)) {
                    drawRoundRect(
                        Nocturne.nothing, cornerRadius = CornerRadius(8.dp.toPx()),
                        style = Stroke(1.dp.toPx(),
                            pathEffect = PathEffect.dashPathEffect(floatArrayOf(5f, 4f))),
                    )
                }
                androidx.compose.material3.Text("${d.n}", style = N.cellDay
                    .copy(color = Nocturne.fgA(0.5f)))
            }
            CalKind.MEASURED, CalKind.TODAY -> Box(
                Modifier.fillMaxWidth().aspectRatio(1f)
                    .background(d.color.copy(alpha = 0.22f), shape)
                    .then(if (d.kind == CalKind.TODAY)
                        Modifier.border0(2.dp, Nocturne.accent.copy(alpha = 0.55f), shape)
                    else Modifier)
                    .then(NoRipple.noRipple({ onOpenDay(d.n) })),
                contentAlignment = Alignment.Center,
            ) {
                Canvas(Modifier.fillMaxWidth().aspectRatio(1f)) {
                    drawRoundRect(
                        d.color.copy(alpha = 0.5f),
                        cornerRadius = CornerRadius(8.dp.toPx()),
                        style = Stroke(1.dp.toPx()),
                    )
                }
                androidx.compose.material3.Text("${d.n}", style = N.cellDayMeasured
                    .copy(fontWeight = if (d.bold) androidx.compose.ui.text.font.FontWeight.SemiBold
                          else androidx.compose.ui.text.font.FontWeight.Medium))
            }
        }
    }
}

private fun Modifier.border0(width: androidx.compose.ui.unit.Dp, color: Color, shape: androidx.compose.ui.graphics.Shape): Modifier =
    this.then(androidx.compose.ui.Modifier.border(width, color, shape))

enum class CalKind { PLAIN, DASHED, MEASURED, TODAY }

data class CalDay(
    val n: Int,
    val kind: CalKind,
    val color: Color = Color.Transparent,
    val leadingBlanks: Int = 0,
    val bold: Boolean = false,
)

data class CalRow(
    val title: String,
    val subtitle: String,
    val score: String,
    val color: Color,
    val scoreColor: Color,
    val clickable: Boolean,
    val day: Int,
)
