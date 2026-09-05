package com.barrapp.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.barrapp.data.DayEntry
import com.barrapp.ui.parts.Eyebrow
import com.barrapp.ui.parts.bandColor
import java.util.Calendar

private val MONTHS = listOf(
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

/**
 * The training month.
 *
 * A day with training is a filled dot in its band colour; a day where nothing
 * was measurable is an outline. That distinction is the whole point of the
 * grid: an empty day and a day you filmed badly are different facts, and a
 * calendar that showed both as blank would hide the one you can act on.
 */
@Composable
fun CalendarPane(
    days: List<DayEntry>,
    selected: String?,
    onSelect: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val today = remember { Calendar.getInstance() }
    var year by remember { mutableStateOf(today.get(Calendar.YEAR)) }
    var month by remember { mutableStateOf(today.get(Calendar.MONTH)) }

    val byDate = remember(days) { days.associateBy { it.date } }
    val cells = remember(year, month) { monthCells(year, month) }
    val monthDays = remember(days, year, month) {
        val prefix = "%04d-%02d".format(year, month + 1)
        days.filter { it.date.startsWith(prefix) }
    }

    Column(modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        Row(
            Modifier.fillMaxWidth().padding(vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            IconButton(onClick = {
                if (month == 0) { month = 11; year -= 1 } else month -= 1
            }) {
                Icon(Icons.AutoMirrored.Filled.KeyboardArrowLeft, "Previous month")
            }
            Text(
                "${MONTHS[month]} $year",
                style = MaterialTheme.typography.titleMedium,
            )
            IconButton(onClick = {
                if (month == 11) { month = 0; year += 1 } else month += 1
            }) {
                Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, "Next month")
            }
        }

        Row(Modifier.fillMaxWidth().padding(bottom = 4.dp)) {
            listOf("M", "T", "W", "T", "F", "S", "S").forEach { d ->
                Text(
                    d,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.weight(1f),
                )
            }
        }

        LazyColumn(
            modifier = Modifier.fillMaxWidth(),
            contentPadding = PaddingValues(bottom = 24.dp),
        ) {
            // The month grid: at most six rows of seven, so plain Rows. A lazy
            // grid here would be a second scrollable inside a scrollable.
            items(cells.chunked(7)) { week ->
                Row(Modifier.fillMaxWidth()) {
                    week.forEach { cell ->
                        Box(Modifier.weight(1f)) {
                            if (cell == null) {
                                Box(Modifier.fillMaxWidth().aspectRatio(1f))
                            } else {
                                val date = "%04d-%02d-%02d".format(year, month + 1, cell)
                                DayCell(
                                    day = cell,
                                    entry = byDate[date],
                                    selected = date == selected,
                                    isToday = date == todayString(today),
                                    onClick = { onSelect(date) },
                                )
                            }
                        }
                    }
                    // Pad the last week so its cells keep the same width.
                    repeat(7 - week.size) { Box(Modifier.weight(1f)) }
                }
            }

            item {
                Spacer(Modifier.height(18.dp))
                HorizontalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f))
                Spacer(Modifier.height(14.dp))
                Eyebrow("This month")
                Spacer(Modifier.height(8.dp))
            }

            if (monthDays.isEmpty()) {
                item {
                    Text(
                        "Nothing recorded in ${MONTHS[month]}.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            } else {
                items(monthDays) { entry ->
                    DayRow(entry, entry.date == selected) { onSelect(entry.date) }
                }
            }
        }
    }
}

@Composable
private fun DayCell(
    day: Int,
    entry: DayEntry?,
    selected: Boolean,
    isToday: Boolean,
    onClick: () -> Unit,
) {
    // A held day has no score, so its band is "unmeasured" - but it is not
    // unmeasured, it is measured in seconds. Painted in the grey the bands use
    // for "nothing came out of this" it read exactly like a failed clip, which
    // is the one thing the hold work exists to stop. The accent says
    // "measured, not scored"; no score band can say that.
    val colour = entry?.let {
        if (it.heldOnly) MaterialTheme.colorScheme.primary else bandColor(it.band)
    }
    Box(
        Modifier
            .aspectRatio(1f)
            .padding(2.dp)
            .clip(RoundedCornerShape(10.dp))
            .then(
                if (selected) Modifier.background(MaterialTheme.colorScheme.primary.copy(alpha = 0.12f))
                else Modifier
            )
            .then(
                if (selected) Modifier.border(
                    1.dp, MaterialTheme.colorScheme.primary, RoundedCornerShape(10.dp)
                ) else Modifier
            )
            .clickable(enabled = entry != null || isToday, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                day.toString(),
                fontFamily = FontFamily.Monospace,
                fontWeight = if (isToday) FontWeight.Bold else FontWeight.Normal,
                style = MaterialTheme.typography.bodySmall,
                color = when {
                    entry != null -> MaterialTheme.colorScheme.onSurface
                    isToday -> MaterialTheme.colorScheme.primary
                    else -> MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.55f)
                },
            )
            Spacer(Modifier.height(3.dp))
            when {
                entry == null -> Spacer(Modifier.size(6.dp))
                entry.measured -> Box(
                    Modifier.size(6.dp).clip(CircleShape).background(colour!!)
                )
                // A timed hold: measured, by duration, with no score. A filled
                // dot in the unscored colour - not an outline, because
                // something did come out of that day.
                entry.heldOnly -> Box(
                    Modifier.size(6.dp).clip(CircleShape).background(colour!!)
                )
                // Filmed, but nothing came out of it. An outline, not a blank:
                // "you trained and it did not record" is actionable, "nothing
                // here" is not.
                else -> Box(
                    Modifier
                        .size(6.dp)
                        .clip(CircleShape)
                        .border(1.dp, MaterialTheme.colorScheme.onSurfaceVariant, CircleShape)
                )
            }
        }
    }
}

@Composable
private fun DayRow(entry: DayEntry, selected: Boolean, onClick: () -> Unit) {
    val colour = if (entry.heldOnly) MaterialTheme.colorScheme.primary
    else bandColor(entry.band)
    Row(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(10.dp))
            .then(
                if (selected) Modifier.background(MaterialTheme.colorScheme.primary.copy(alpha = 0.08f))
                else Modifier
            )
            .clickable(onClick = onClick)
            .padding(horizontal = 10.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Box(Modifier.size(8.dp).clip(CircleShape).background(colour))
        Column(Modifier.weight(1f)) {
            Text(
                entry.exerciseLabel.ifBlank { entry.exercise.replace('_', ' ') },
                style = MaterialTheme.typography.titleSmall,
            )
            Text(
                (if (entry.heldOnly) "held ${entry.holdS.toInt()} s"
                else "${entry.reps} rep${if (entry.reps == 1) "" else "s"}") +
                    " · ${entry.date.takeLast(5)}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Text(
            entry.score?.toString() ?: if (entry.heldOnly) "${entry.holdS.toInt()}s" else "—",
            fontFamily = FontFamily.Monospace,
            fontWeight = FontWeight.SemiBold,
            style = MaterialTheme.typography.titleMedium,
            color = if (entry.measured || entry.heldOnly) colour
            else MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/** Cells for a month grid, Monday first, with leading blanks as nulls. */
private fun monthCells(year: Int, month: Int): List<Int?> {
    val cal = Calendar.getInstance()
    cal.clear()
    cal.set(year, month, 1)
    // Calendar.DAY_OF_WEEK is 1=Sunday; shift so Monday is 0.
    val lead = (cal.get(Calendar.DAY_OF_WEEK) + 5) % 7
    val length = cal.getActualMaximum(Calendar.DAY_OF_MONTH)
    return List(lead) { null } + (1..length).toList()
}

private fun todayString(cal: Calendar): String = "%04d-%02d-%02d".format(
    cal.get(Calendar.YEAR), cal.get(Calendar.MONTH) + 1, cal.get(Calendar.DAY_OF_MONTH)
)
