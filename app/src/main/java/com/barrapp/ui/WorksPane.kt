package com.barrapp.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.barrapp.data.Work
import com.barrapp.data.WorkStore
import com.barrapp.ui.parts.Eyebrow
import com.barrapp.ui.parts.Panel
import com.barrapp.ui.parts.Pill
import com.barrapp.ui.parts.bandColor
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * The works in progress, where the sessions have not reached yet.
 *
 * Every clip on its way shows as a row that says where it is - sending,
 * queued, measuring, and the server's own stage in between - and, when a
 * work went wrong, why, with the log one tap away. Nothing here blocks the
 * rest of the app: the queue runs, the calendar keeps working.
 */
@Composable
fun WorksSection(
    works: List<Work>,
    onOpenLog: (String) -> Unit,
    onRetry: (String) -> Unit,
    onDismiss: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    if (works.isEmpty()) return
    com.barrapp.ui.parts.Panel(modifier.padding(horizontal = 20.dp, vertical = 10.dp)) {
        Eyebrow("In the works")
        Spacer(Modifier.height(8.dp))
        works.forEach { work -> WorkRow(work, onOpenLog, onRetry, onDismiss) }
    }
}

@Composable
private fun WorkRow(
    work: Work,
    onOpenLog: (String) -> Unit,
    onRetry: (String) -> Unit,
    onDismiss: (String) -> Unit,
) {
    val stamp = rememberStamp()
    Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (work.active) {
                CircularProgressIndicator(Modifier.size(14.dp), strokeWidth = 2.dp)
                Spacer(Modifier.size(10.dp))
            } else {
                Spacer(Modifier.size(24.dp))
            }
            Column(Modifier.weight(1f).clickable(enabled = work.log.isNotEmpty()) {
                onOpenLog(work.id)
            }) {
                Text(
                    work.exercise.ifBlank {
                        "Clip · " + stamp.format(Date(work.createdAt))
                    },
                    style = MaterialTheme.typography.bodyMedium,
                )
                Text(
                    work.line,
                    style = MaterialTheme.typography.bodySmall,
                    color = when {
                        work.status == WorkStore.STATUS_FAILED ->
                            MaterialTheme.colorScheme.error
                        else -> MaterialTheme.colorScheme.onSurfaceVariant
                    },
                )
            }
            Pill(
                when (work.status) {
                    WorkStore.STATUS_FAILED -> "failed"
                    WorkStore.STATUS_SENDING -> "sending"
                    WorkStore.STATUS_QUEUED -> "queued"
                    WorkStore.STATUS_MEASURING -> "measuring"
                    WorkStore.STATUS_DONE -> "done"
                    else -> "waiting"
                },
                color = when {
                    work.status == WorkStore.STATUS_FAILED ->
                        MaterialTheme.colorScheme.error
                    work.active -> bandColor("solid")
                    else -> MaterialTheme.colorScheme.onSurfaceVariant
                },
            )
        }
        if (work.status == WorkStore.STATUS_FAILED) {
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                TextButton(onClick = { onRetry(work.id) }) { Text("Retry") }
                if (work.log.isNotEmpty()) {
                    TextButton(onClick = { onOpenLog(work.id) }) { Text("Log") }
                }
                TextButton(onClick = { onDismiss(work.id) }) { Text("Dismiss") }
            }
        }
    }
}

@Composable
private fun rememberStamp(): SimpleDateFormat =
    remember { SimpleDateFormat("HH:mm", Locale.UK) }

/**
 * One work's own log, oldest first: the story of a clip from the queue to the
 * server and back. When the work failed, the top of the screen says what it
 * was doing when it went wrong and why - so "where did the processing go
 * wrong" has an answer on this screen, in order, with times.
 */
@Composable
fun WorkLogScreen(
    work: Work?,
    onBack: () -> Unit,
    onRetry: (String) -> Unit,
    onDismiss: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val stamp = remember { SimpleDateFormat("MM-dd HH:mm:ss", Locale.UK) }

    LazyColumn(
        modifier = modifier.fillMaxWidth(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClick = onBack) { Text("Back") }
                Spacer(Modifier.size(6.dp))
                Text("Work log", style = MaterialTheme.typography.titleMedium)
            }
        }
        if (work == null) {
            item {
                Text("This work is no longer in the queue.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        } else {
            item {
                Panel {
                    Eyebrow("Clip · " + stamp.format(Date(work.createdAt)))
                    Spacer(Modifier.height(6.dp))
                    Text(work.exercise.ifBlank { "still unmeasured" },
                        style = MaterialTheme.typography.bodyMedium)
                    Spacer(Modifier.height(4.dp))
                    Text(
                        listOfNotNull(
                            work.jobId.takeIf { it.isNotBlank() }?.let { "job $it" },
                            work.traceId.takeIf { it.isNotBlank() }?.let { "trace $it" },
                        ).joinToString("  ·  ").ifBlank { "no job reached the server" },
                        fontFamily = FontFamily.Monospace,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    if (work.status == WorkStore.STATUS_FAILED) {
                        Spacer(Modifier.height(10.dp))
                        Text(
                            "Failed: ${work.error ?: "unknown reason"}",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.error,
                        )
                        Text(
                            "The log below ends at the step that went wrong.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Spacer(Modifier.height(6.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                            TextButton(onClick = { onRetry(work.id) }) { Text("Retry") }
                            TextButton(onClick = { onDismiss(work.id) }) { Text("Dismiss") }
                            TextButton(onClick = {
                                val text = buildString {
                                    appendLine("barrapp work ${work.id} — ${work.status}")
                                    work.jobId.takeIf { it.isNotBlank() }
                                        ?.let { appendLine("job $it") }
                                    work.traceId.takeIf { it.isNotBlank() }
                                        ?.let { appendLine("trace $it") }
                                    work.log.forEach { e ->
                                        appendLine(stamp.format(Date(e.at)) + "  " +
                                            e.level.name.padEnd(5) + "  " + e.message)
                                    }
                                }
                                val cm = context.getSystemService(
                                    android.content.Context.CLIPBOARD_SERVICE)
                                    as? android.content.ClipboardManager
                                cm?.setPrimaryClip(android.content.ClipData.newPlainText(
                                    "barrapp work log", text))
                            }) { Text("Copy log") }
                        }
                    }
                }
            }
            item { Eyebrow("What happened, in order") }
            items(work.log) { e ->
                Panel(padding = PaddingValues(12.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(stamp.format(Date(e.at)),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Spacer(Modifier.weight(1f))
                        Pill(e.level.name.lowercase(), color = when (e.level) {
                            WorkStore.Level.ERROR -> MaterialTheme.colorScheme.error
                            WorkStore.Level.WARN ->
                                com.barrapp.ui.theme.LocalBandColors.current.shaky
                            WorkStore.Level.INFO -> MaterialTheme.colorScheme.onSurfaceVariant
                        })
                    }
                    Spacer(Modifier.height(4.dp))
                    Text(e.message, style = MaterialTheme.typography.bodyMedium)
                }
            }
            if (work.log.isEmpty()) {
                item {
                    Text("Nothing logged for this work.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}
