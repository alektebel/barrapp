package com.barrapp.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.barrapp.data.ChatTurn
import com.barrapp.data.Goals
import com.barrapp.ui.parts.Eyebrow

/**
 * The objectives intake: a short conversation that sets up the profile and a
 * goal, instead of a form. One question at a time, from the model, so someone
 * new to the app is asked about what they actually want rather than made to
 * pick from a fixed list they have not seen yet.
 */
@Composable
fun ObjectivesChatScreen(
    turns: List<ChatTurn>,
    thinking: Boolean,
    goals: Goals?,
    onSend: (String) -> Unit,
    onDone: () -> Unit,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var draft by remember { mutableStateOf("") }
    val listState = rememberLazyListState()

    LaunchedEffect(turns.size, thinking) {
        val last = turns.size - 1 + (if (thinking) 1 else 0)
        if (last >= 0) listState.animateScrollToItem(last)
    }

    Column(modifier.fillMaxSize().imePadding()) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TextButton(onClick = onBack) { Text("Back") }
            Spacer(Modifier.size(6.dp))
            Column(Modifier.weight(1f)) {
                Text("Objectives", style = MaterialTheme.typography.titleMedium)
                Text(
                    "A short chat to set your goal and how often you train.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f))

        LazyColumn(
            state = listState,
            modifier = Modifier.weight(1f).fillMaxWidth(),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            if (turns.isEmpty() && !thinking) {
                item {
                    Text(
                        "Starting the conversation…",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            itemsIndexed(turns) { _, turn -> ObjectiveBubble(turn) }
            if (thinking) {
                item {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        CircularProgressIndicator(Modifier.size(14.dp), strokeWidth = 2.dp)
                        Text(
                            "Thinking…",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
            if (goals != null && goals.goal.isNotBlank()) {
                item {
                    Column {
                        Eyebrow("Captured")
                        Spacer(Modifier.height(6.dp))
                        Text(
                            "Goal: ${goals.goal}" +
                                (goals.focusExercise
                                    .takeIf { it.isNotBlank() && it != "unknown" }
                                    ?.let { "\nFocus: ${it.replace('_', ' ')}" } ?: ""),
                            style = MaterialTheme.typography.bodyMedium,
                        )
                        Spacer(Modifier.height(14.dp))
                        Button(onClick = onDone, modifier = Modifier.fillMaxWidth()) {
                            Text("Done — start training")
                        }
                    }
                }
            }
        }

        HorizontalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f))
        Row(
            Modifier.fillMaxWidth().padding(12.dp),
            verticalAlignment = Alignment.Bottom,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            OutlinedTextField(
                value = draft,
                onValueChange = { draft = it },
                placeholder = { Text("Tell me what you want") },
                shape = RoundedCornerShape(14.dp),
                maxLines = 4,
                modifier = Modifier.weight(1f),
            )
            TextButton(
                onClick = {
                    val text = draft.trim()
                    if (text.isNotEmpty()) {
                        onSend(text)
                        draft = ""
                    }
                },
                enabled = draft.isNotBlank() && !thinking,
            ) {
                Text("Send", style = MaterialTheme.typography.labelLarge,
                    fontWeight = FontWeight.SemiBold)
            }
        }
    }
}

@Composable
private fun ObjectiveBubble(turn: ChatTurn) {
    val mine = turn.fromUser
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start,
    ) {
        Column(
            Modifier
                .widthIn(max = 460.dp)
                .clip(
                    RoundedCornerShape(
                        topStart = 16.dp, topEnd = 16.dp,
                        bottomStart = if (mine) 16.dp else 4.dp,
                        bottomEnd = if (mine) 4.dp else 16.dp,
                    )
                )
                .background(
                    if (mine) MaterialTheme.colorScheme.primary.copy(alpha = 0.14f)
                    else MaterialTheme.colorScheme.surfaceVariant
                )
                .padding(horizontal = 14.dp, vertical = 10.dp)
        ) {
            if (!mine) {
                Eyebrow("barrapp")
                Spacer(Modifier.height(6.dp))
            }
            Text(turn.text, style = MaterialTheme.typography.bodyMedium)
        }
    }
}
