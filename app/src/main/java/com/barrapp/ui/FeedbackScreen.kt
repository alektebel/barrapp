package com.barrapp.ui

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.barrapp.ui.parts.Eyebrow
import com.barrapp.ui.parts.Panel

/**
 * The screen a user reaches when something looked wrong and "Copy report"
 * alone does not say it. The message is the only required field; a clip is
 * optional and travels the same presigned path an upload takes, so a wrong
 * measurement arrives with the pixels that produced it.
 *
 * Sent lands on a plain confirmation - no "we value your feedback" copy, just
 * what happened and what happens next.
 */
@Composable
fun FeedbackScreen(
    busy: Boolean,
    sent: Boolean,
    error: String?,
    onSend: (String, Uri?) -> Unit,
    onReset: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var message by remember { mutableStateOf("") }
    var video by remember { mutableStateOf<Uri?>(null) }
    val hadVideo = remember { mutableStateOf(false) }

    val picker = rememberLauncherForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri -> if (uri != null) video = uri }

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            TextButton(onClick = onBack) { Text("Back") }
        }

        if (sent) {
            item {
                Panel {
                    Eyebrow("Sent")
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "Your feedback is on the server." +
                            if (hadVideo.value) " The clip is with it." else "",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Spacer(Modifier.height(10.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Button(onClick = {
                            message = ""
                            video = null
                            hadVideo.value = false
                            onReset()
                        }) { Text("Send more") }
                        OutlinedButton(onClick = onBack) { Text("Done") }
                    }
                }
            }
        } else {
            item {
                Panel {
                    Eyebrow("What went wrong?")
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "A number that looked wrong, a screen that did nothing, anything. " +
                            "The last measurement's trace id is attached automatically, so " +
                            "\"the score is nonsense\" is something that can be replayed.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(12.dp))
                    OutlinedTextField(
                        value = message,
                        onValueChange = { message = it },
                        modifier = Modifier.fillMaxWidth(),
                        minLines = 4,
                        placeholder = { Text("Tell us what happened") },
                    )
                    Spacer(Modifier.height(12.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        OutlinedButton(
                            onClick = { picker.launch("video/*") },
                            modifier = Modifier.weight(1f),
                        ) { Text(if (video == null) "Attach a video" else "Replace video") }
                        if (video != null) {
                            OutlinedButton(
                                onClick = { video = null },
                                modifier = Modifier.weight(1f),
                            ) { Text("Remove video") }
                        }
                    }
                    if (video != null) {
                        Spacer(Modifier.height(6.dp))
                        Text(
                            "A clip is attached. It uploads after the message, and is " +
                                "deleted from the server after 30 days like every clip.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }

            error?.let { text ->
                item {
                    Panel {
                        Text(
                            text,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                    }
                }
            }

            item {
                Button(
                    onClick = {
                        hadVideo.value = video != null
                        onSend(message, video)
                    },
                    enabled = !busy && message.isNotBlank(),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(if (busy) "Sending…" else "Send")
                }
            }
        }
    }
}
