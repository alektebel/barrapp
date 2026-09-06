package com.barrapp.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.unit.dp
import com.barrapp.ui.theme.Nocturne
import com.barrapp.ui.theme.N

/** Appendix G — arithmetic over your own sessions. It cannot invent a PR,
 *  and it says so when the data won't answer. */
@Composable
fun CoachScreen(
    turns: List<CoachTurn>,
    thinking: Boolean,
    suggestions: List<String>,
    onSend: (String) -> Unit,
    onBackToWeek: () -> Unit,
) {
    var draft by remember { mutableStateOf("") }
    Column(Modifier.fillMaxWidth()) {
        androidx.compose.material3.Text("← Week", style = N.back,
            modifier = Modifier.padding(bottom = 14.dp)
                .then(NoRipple.noRipple(onBackToWeek)))

        androidx.compose.material3.Text("Coach", style = N.pageTitle)
        androidx.compose.material3.Text(
            "Arithmetic over your own sessions. It cannot invent a PR, and it says " +
                "so when the data won't answer.",
            style = N.bodyNote, modifier = Modifier.padding(top = 6.dp),
        )

        androidx.compose.material3.Text("TRY", style = N.eyebrowMuted,
            modifier = Modifier.padding(top = 20.dp, bottom = 9.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(7.dp)) {
            suggestions.take(3).forEach { s ->
                Box(
                    Modifier.weight(1f)
                        .border(1.dp, Nocturne.fgA(0.16f), RoundedCornerShape(8.dp))
                        .padding(horizontal = 11.dp, vertical = 8.dp)
                        .then(NoRipple.noRipple { onSend(s) }),
                ) {
                    androidx.compose.material3.Text(s, style = N.chipTry)
                }
            }
        }

        turns.forEach { t ->
            if (t.fromUser) {
                Row(Modifier.fillMaxWidth().padding(top = 20.dp),
                    horizontalArrangement = Arrangement.End) {
                    Box(
                        // A fraction of the row, capped at the design's width:
                        // a fixed 270dp overflows any phone narrower than 360dp
                        // and never grows with the text.
                        Modifier.fillMaxWidth(0.85f)
                            .widthIn(max = 270.dp)
                            .background(Nocturne.deep,
                                RoundedCornerShape(14.dp, 14.dp, 4.dp, 14.dp))
                            .padding(horizontal = 13.dp, vertical = 10.dp),
                    ) {
                        androidx.compose.material3.Text(t.text, style = N.bubble)
                    }
                }
            } else {
                Row(Modifier.fillMaxWidth().padding(top = 10.dp)) {
                    Column(
                        Modifier.fillMaxWidth(0.9f)
                            .widthIn(max = 290.dp)
                            .background(Nocturne.surface,
                                RoundedCornerShape(14.dp, 14.dp, 14.dp, 4.dp))
                            .border(1.dp, Nocturne.hairline,
                                RoundedCornerShape(14.dp, 14.dp, 14.dp, 4.dp))
                            .padding(horizontal = 13.dp, vertical = 12.dp),
                    ) {
                        androidx.compose.material3.Text("FROM YOUR DATA", style = N.bubbleLabel)
                        androidx.compose.material3.Text(t.text, style = N.bubble,
                            modifier = Modifier.padding(top = 8.dp))
                        if (t.note.isNotBlank()) {
                            androidx.compose.material3.Text(t.note, style = N.bubbleNote,
                                modifier = Modifier.padding(top = 8.dp))
                        }
                    }
                }
            }
        }
        if (thinking) {
            Row(Modifier.fillMaxWidth().padding(top = 10.dp)) {
                androidx.compose.material3.Text("…", style = N.bubble
                    .copy(color = Nocturne.fgA(0.4f)))
            }
        }

        Row(
            Modifier.fillMaxWidth().padding(top = 18.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                Modifier.weight(1f)
                    .heightIn(min = 36.dp)
                    .background(Nocturne.surface, RoundedCornerShape(8.dp))
                    .border(1.dp, Nocturne.fgA(0.16f), RoundedCornerShape(8.dp))
                    .padding(horizontal = 11.dp, vertical = 9.dp),
                contentAlignment = Alignment.CenterStart,
            ) {
                BasicTextField(
                    value = draft,
                    onValueChange = { draft = it },
                    textStyle = N.captionPlain,
                    cursorBrush = SolidColor(Nocturne.accent),
                    decorationBox = { inner ->
                        if (draft.isEmpty()) {
                            androidx.compose.material3.Text("Ask about your training",
                                style = N.input)
                        }
                        inner()
                    },
                    singleLine = true,
                )
            }
            Spacer(Modifier.width(8.dp))
            Box(
                Modifier.size(36.dp)
                    .border(1.dp, Nocturne.accent, RoundedCornerShape(8.dp))
                    .then(NoRipple.noRipple {
                        if (draft.isNotBlank()) {
                            onSend(draft)
                            draft = ""
                        }
                    }),
                contentAlignment = Alignment.Center,
            ) {
                androidx.compose.material3.Text("↑", style = N.send)
            }
        }
    }
}

data class CoachTurn(val fromUser: Boolean, val text: String, val note: String = "")
