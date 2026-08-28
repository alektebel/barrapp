package com.barrapp.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import com.barrapp.data.Analysis
import com.barrapp.data.EventLog
import com.barrapp.ui.parts.Eyebrow
import com.barrapp.ui.parts.Panel
import com.barrapp.ui.parts.Pill
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Everything needed to debug a wrong number, in one place.
 *
 * The thing that matters here is the **trace id**. Every measurement the server
 * makes writes a full decision chain to disk under that id, so a session that
 * looks wrong stops being a description and becomes a command:
 *
 *     barra explain --replay <id>
 *
 * Under it, the provenance of the build that produced the number - because a
 * score that moved because the build moved is not a score that moved because
 * the athlete did - and the event log, which is where the failures nobody was
 * watching end up.
 *
 * Copy report puts the lot on the clipboard, with the device id and no personal
 * data: enough to reproduce, nothing that identifies anyone.
 */
@Composable
fun DiagnosticsScreen(
    events: List<EventLog.Event>,
    latest: Analysis?,
    deviceId: String,
    apiBase: String,
    report: () -> String,
    onClear: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val stamp = remember { SimpleDateFormat("MM-dd HH:mm:ss", Locale.UK) }

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClick = onBack) { Text("Back") }
                Spacer(Modifier.size(6.dp))
                Text("Diagnostics", style = MaterialTheme.typography.titleMedium)
            }
        }

        if (latest != null && latest.traceId.isNotBlank()) {
            item {
                Panel {
                    Eyebrow("Last measurement")
                    Spacer(Modifier.height(8.dp))
                    Text(
                        latest.traceId,
                        fontFamily = FontFamily.Monospace,
                        style = MaterialTheme.typography.titleMedium,
                    )
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "The server saved the whole decision chain under this id — every " +
                            "candidate rep it found, every one it rejected, and the number " +
                            "behind each choice.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "barra explain --replay ${latest.traceId}",
                        fontFamily = FontFamily.Monospace,
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(MaterialTheme.shapes.small)
                            .background(MaterialTheme.colorScheme.surfaceVariant)
                            .padding(10.dp),
                    )
                    latest.provenance?.let { p ->
                        Spacer(Modifier.height(12.dp))
                        HorizontalDivider(
                            color = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f)
                        )
                        Spacer(Modifier.height(10.dp))
                        Eyebrow("Produced by")
                        Spacer(Modifier.height(6.dp))
                        Text(
                            p.summary,
                            fontFamily = FontFamily.Monospace,
                            style = MaterialTheme.typography.bodySmall,
                        )
                        Text(
                            "Code version, commit, and the hash of the pose model. A number " +
                                "that changed because one of these changed is not a number " +
                                "that changed because you did.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(top = 6.dp),
                        )
                    }
                }
            }
        }

        item {
            Panel {
                Eyebrow("This device")
                Spacer(Modifier.height(8.dp))
                LabelledValue("device id", deviceId)
                LabelledValue("server", apiBase)
                LabelledValue("events kept", "${events.size} of ${EventLog.LIMIT}")
            }
        }

        item {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedButton(
                    onClick = { copyToClipboard(context, report()) },
                    modifier = Modifier.weight(1f),
                ) { Text("Copy report") }
                OutlinedButton(onClick = onClear) { Text("Clear log") }
            }
        }

        item { Eyebrow("Event log") }

        if (events.isEmpty()) {
            item {
                Text(
                    "Nothing logged yet. Uploads, failures and timeouts land here — " +
                        "including the ones that happen while the app is closed.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        items(events) { e ->
            Panel(padding = PaddingValues(12.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Dot(levelColour(e.level))
                    Spacer(Modifier.size(8.dp))
                    Text(
                        stamp.format(Date(e.at)),
                        fontFamily = FontFamily.Monospace,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.weight(1f))
                    Pill(e.level.name, levelColour(e.level))
                }
                Spacer(Modifier.height(6.dp))
                Text(e.line, style = MaterialTheme.typography.bodyMedium)
                if (e.traceId.isNotBlank() || e.jobId.isNotBlank()) {
                    Spacer(Modifier.height(4.dp))
                    Text(
                        listOfNotNull(
                            e.traceId.takeIf { it.isNotBlank() }?.let { "trace $it" },
                            e.jobId.takeIf { it.isNotBlank() }?.let { "job $it" },
                        ).joinToString("  ·  "),
                        fontFamily = FontFamily.Monospace,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}

@Composable
private fun LabelledValue(label: String, value: String) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 3.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            label,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(value, fontFamily = FontFamily.Monospace,
            style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun Dot(colour: Color) {
    Box(Modifier.size(8.dp).clip(CircleShape).background(colour))
}

@Composable
private fun levelColour(level: EventLog.Level) = when (level) {
    EventLog.Level.ERROR -> MaterialTheme.colorScheme.error
    EventLog.Level.WARN -> com.barrapp.ui.theme.LocalBandColors.current.shaky
    EventLog.Level.INFO -> MaterialTheme.colorScheme.onSurfaceVariant
}

private fun copyToClipboard(context: Context, text: String) {
    val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
    cm?.setPrimaryClip(ClipData.newPlainText("barrapp diagnostics", text))
}
