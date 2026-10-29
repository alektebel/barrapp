package com.barrapp.ui.tracker

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.barrapp.data.DayEntry
import com.barrapp.data.JobSummary
import com.barrapp.movementEs
import com.barrapp.shortDateEs
import com.barrapp.ui.theme.T
import com.barrapp.ui.theme.Tk
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

/**
 * Un día de entrenamiento: su nota y, debajo, cada sesión grabada ese día con
 * la suya. Tocar una sesión abre su resultado.
 *
 * Una sesión sin nota se enseña como tal, con el motivo en claro ("sin medir"),
 * y no cuenta en la nota del día: que barra no pudiera leer un clip no es que
 * lo hicieras mal.
 */
@Composable
fun DaySheet(
    day: DayEntry,
    unseen: Set<String>,
    onOpenSession: (String) -> Unit,
    onClose: () -> Unit,
) {
    Eyebrow("Día")
    Text(shortDateEs(day.date), style = T.pageTitle, modifier = Modifier.padding(top = 4.dp))

    TkCard(Modifier.padding(top = 14.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            ScoreRing(day.score, size = 72.dp)
            Spacer(Modifier.width(16.dp))
            Column {
                Text(
                    if (day.measured) "Nota del día" else "Día sin nota",
                    style = T.rowTitle,
                )
                Text(
                    dayLine(day),
                    style = T.bodyS,
                    modifier = Modifier.padding(top = 4.dp),
                )
            }
        }
    }

    Eyebrow("Sesiones", modifier = Modifier.padding(top = 22.dp, bottom = 8.dp))
    val sessions = daySessions(day)
    if (sessions.isEmpty()) {
        Text("No hay sesiones guardadas este día.", style = T.bodyS)
    }
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        sessions.forEach { s ->
            TkCard(
                Modifier.noRipple { onOpenSession(s.jobId) },
                padding = androidx.compose.foundation.layout.PaddingValues(12.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    ScoreRing(s.sessionScore ?: s.score, size = 48.dp, stroke = 4.dp)
                    Spacer(Modifier.width(14.dp))
                    Column(Modifier.weight(1f)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(movementEs(s.exercise, s.label), style = T.rowTitle)
                            if (s.jobId in unseen) {
                                Spacer(Modifier.width(8.dp))
                                Text("NUEVO", style = T.eyebrowAccent, color = Tk.primary)
                            }
                        }
                        Text(sessionLine(s), style = T.bodyS, modifier = Modifier.padding(top = 3.dp))
                    }
                    Text("›", style = T.sectionTitle, color = Tk.muted)
                }
            }
        }
    }
    TkSecondaryButton("Volver", onClose, modifier = Modifier.padding(top = 20.dp))
    Spacer(Modifier.height(8.dp))
}

/** Las sesiones del día, la más reciente primero. Un día guardado antes de que
 *  se conservara la lista tiene, como mucho, su última sesión. */
internal fun daySessions(day: DayEntry): List<JobSummary> {
    val listed = day.sessions.ifEmpty { listOfNotNull(day.last) }
    return if (listed.all { it.at.isNotBlank() }) listed.sortedByDescending { it.at }
    else listed.reversed()
}

private fun dayLine(day: DayEntry): String {
    val sessions = day.sessions.size.takeIf { it > 0 } ?: day.jobIds.size
    val parts = mutableListOf("$sessions ${if (sessions == 1) "sesión" else "sesiones"}")
    parts += "${day.reps} reps"
    if (day.measured) parts += "${day.verifiedReps} medidas"
    return parts.joinToString(" · ")
}

private fun sessionLine(s: JobSummary): String {
    val parts = mutableListOf<String>()
    localTime(s.at)?.let { parts += it }
    parts += "${s.reps} ${if (s.reps == 1) "rep" else "reps"}"
    if (s.sessionScore == null && s.score == null) parts += "sin medir"
    return parts.joinToString(" · ")
}

/** "18:42" en la hora del teléfono, a partir de la marca UTC del servidor. */
internal fun localTime(at: String): String? {
    if (at.length < 19) return null
    return runCatching {
        val parse = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US)
            .apply { timeZone = TimeZone.getTimeZone("UTC") }
        val out = SimpleDateFormat("HH:mm", Locale.US)
        out.format(parse.parse(at.substring(0, 19))!!)
    }.getOrNull()
}
