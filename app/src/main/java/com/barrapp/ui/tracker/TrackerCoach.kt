package com.barrapp.ui.tracker

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.BasicTextField
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
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.barrapp.Drill
import com.barrapp.ui.theme.T
import com.barrapp.ui.theme.Tk
import com.barrapp.ui.theme.body
import com.barrapp.ui.theme.mono

/** One technique rule, as the app measured it over the recent window.
 *
 *  No longer rendered on this screen: the COACH tab is now the conversation
 *  of design 2e. The class stays because the data layer still builds it. */
data class CoachRule(
    val id: String,
    val title: String,
    val phase: String,
    /** "Corregir" / "Progresando" / "Correcto" / "Sin juzgar" */
    val verdict: String,
    val verdictInk: Color,
    val description: String,
    val cue: String,
)

/** A fault the coach is working on, with the evidence behind it.
 *
 *  No longer rendered on this screen: see [CoachRule]. */
data class CoachFocus(
    val fault: String,
    val cue: String,
    val drill: Drill?,
    val repsAffected: Int,
    /** How much it fell against the previous window; null with nothing to
     *  compare against. */
    val improvementPct: Int?,
    val improving: Boolean,
)

/**
 * The proof behind a coach claim: a rep of a concrete session the athlete can
 * open. The video is the evidence — every answer points at one.
 */
data class CoachProof(
    /** Human label, e.g. "Rep 2 de ago vs rep 2 de hoy". */
    val label: String,
    /** ISO date of the session the proof opens; blank when unknown. */
    val sessionDate: String = "",
    /** 1-based rep inside that session; 0 opens the session itself. */
    val repIndex: Int = 0,
)

/** One exchange in the coach conversation, oldest first. */
data class CoachMessage(
    val fromUser: Boolean,
    val text: String,
    /** The clip/rep that backs this answer, when it has one. */
    val proof: CoachProof? = null,
)

data class CoachData(
    val movement: String,
    val sessions: Int,
    val focus: CoachFocus?,
    val secondary: CoachFocus?,
    val rules: List<CoachRule>,
    val drills: List<Drill>,
    val totalMinutes: Int,
    /** Plain statement about the last session when it could not be scored. */
    val notice: String? = null,
    /** "Movimiento · fecha" of the scored session the rules and focus come from.
     *  No longer rendered: the 2e header names the number of sessions. */
    val basisLabel: String? = null,
    /** "Movimiento · fecha" of the scored session the rules and focus come from. */
    val rulesLabel: String = "",
    /** The conversation so far, oldest first. */
    val conversation: List<CoachMessage> = emptyList(),
    /** True while the coach is working on the last question. */
    val thinking: Boolean = false,
    /** Questions offered as chips, taken from the last session. */
    val suggestions: List<String> = emptyList(),
)

/**
 * Coach — design 2e: the tab IS the conversation.
 *
 * Header "COACH · RESPONDE CON TUS DATOS · N SESIONES", the exchange as ink
 * bubbles (the athlete) and white bordered cards (the coach), a PRUEBA row
 * under every answer that carries one, suggested questions as chips above the
 * field, and the field with its orange send arrow.
 *
 * The design's rule B2 is structural here: a question is never left without a
 * visible answer. While the coach works the REVISANDO bubble stands in; if an
 * answer never arrives (crash, dropped store) a human error card with
 * "Reintentar" takes its place, so the last question is always answered by
 * something.
 *
 * What this port renders less than the mockup: its answers carry bold spans
 * ("de 58 a 69") which plain-string answers from the coach cannot mark, and
 * the PRUEBA rows only appear once the answer pipeline attaches the
 * session/rep evidence it points at.
 */
@Composable
fun TrackerCoach(
    data: CoachData,
    onAskCoach: () -> Unit,
    onRecord: () -> Unit,
    modifier: Modifier = Modifier,
    /** Sends a question. Default bridges to the chat sheet the previous
     *  design used; wire it to the coach ask entry point instead. */
    onSend: (String) -> Unit = { onAskCoach() },
    /** Opens the session/rep a PRUEBA row points at. */
    onOpenProof: (CoachProof) -> Unit = {},
) {
    var draft by remember { mutableStateOf("") }
    val scroll = rememberScrollState()

    // The latest turn is always on view: follow the conversation down as it
    // grows and when the REVISANDO bubble appears at its end.
    LaunchedEffect(data.conversation.size, data.thinking) {
        scroll.animateScrollTo(scroll.maxValue)
    }

    Column(modifier.fillMaxSize().imePadding()) {
        Column(
            Modifier.fillMaxWidth()
                .padding(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 10.dp),
        ) {
            Text("COACH", style = T.pageTitle)
            Text(
                sessionsSubtitle(data.sessions),
                style = mono(11, 0.05f, Tk.muted),
                modifier = Modifier.padding(top = 2.dp),
            )
        }
        Box(Modifier.fillMaxWidth().height(2.dp).background(Tk.border))

        Column(
            Modifier
                .weight(1f)
                .fillMaxWidth()
                .verticalScroll(scroll)
                .padding(start = 16.dp, end = 16.dp, top = 14.dp, bottom = 12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            data.notice?.let { notice -> NoticeCard(notice) }
            if (data.conversation.isEmpty()) {
                IntroCard(hasSessions = data.sessions > 0, onRecord = onRecord)
            }
            data.conversation.forEach { turn ->
                if (turn.fromUser) UserBubble(turn.text) else CoachAnswer(turn, onOpenProof)
            }
            if (data.thinking) {
                ThinkingBubble(data.sessions)
            } else {
                // No thinking and no answer: the question fell through. Say so
                // and offer the way back instead of leaving it hanging.
                data.conversation.lastOrNull()
                    ?.takeIf { it.fromUser }
                    ?.let { last -> RetryCard(onRetry = { onSend(last.text) }) }
            }
        }

        val chips = suggestionChips(data)
        if (chips.isNotEmpty()) {
            @OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
            FlowRow(
                Modifier.fillMaxWidth()
                    .padding(start = 16.dp, end = 16.dp, bottom = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                chips.forEach { question ->
                    SuggestionChip(question) { onSend(question) }
                }
            }
        }

        Row(
            Modifier.fillMaxWidth()
                .padding(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 10.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            AskField(draft = draft, onDraft = { draft = it }, modifier = Modifier.weight(1f))
            SendButton(enabled = draft.isNotBlank()) {
                onSend(draft.trim())
                draft = ""
            }
        }
    }
}

// ---- the conversation ------------------------------------------------------

@Composable
private fun UserBubble(text: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
        // Capped, not fixed: a short question stays a short bubble and a long
        // one wraps inside the design's 78%.
        Box(
            Modifier
                .widthIn(max = 280.dp)
                .clip(CardShape)
                .background(Tk.ink)
                .padding(horizontal = 12.dp, vertical = 10.dp),
        ) {
            Text(text, style = body(15, Tk.onInk, 1.4f))
        }
    }
}

@Composable
private fun CoachAnswer(turn: CoachMessage, onOpenProof: (CoachProof) -> Unit) {
    Column(
        Modifier.widthIn(max = 320.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        TkCard(padding = PaddingValues(12.dp)) {
            Text(turn.text, style = body(15, Tk.ink, 1.45f))
        }
        turn.proof?.takeIf { it.label.isNotBlank() }?.let { proof ->
            ProofRow(proof, onOpenProof)
        }
    }
}

/** "PRUEBA · Rep 2 de ago vs rep 2 de hoy": the answer's evidence, one tap
 *  from the clip it came from. */
@Composable
private fun ProofRow(proof: CoachProof, onOpen: (CoachProof) -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .clip(CardShape)
            .background(Tk.surface)
            .border(2.dp, Tk.border, CardShape)
            .noRipple { onOpen(proof) }
            .padding(8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Box(
            Modifier
                .size(56.dp)
                .clip(InnerShape)
                .background(Tk.dark),
            contentAlignment = Alignment.Center,
        ) {
            // The design's play mark (M3 1.5v11l9-5.5z) on the video ground.
            Canvas(
                Modifier
                    .size(16.dp)
                    .semantics { contentDescription = "Reproducir la prueba en vídeo" },
            ) {
                val s = size.width / 14f
                drawPath(
                    Path().apply {
                        moveTo(3f * s, 1.5f * s)
                        lineTo(3f * s, 12.5f * s)
                        lineTo(12f * s, 7f * s)
                        close()
                    },
                    Tk.onInk,
                )
            }
        }
        Column(Modifier.weight(1f)) {
            Text("PRUEBA", style = mono(11, 0.05f, Tk.muted))
            Text(proof.label, style = body(14, Tk.ink, 1.3f, FontWeight.SemiBold))
        }
    }
}

/** The design's rule B2: the coach is never silent — this stands in for the
 *  answer while it is being worked out. */
@Composable
private fun ThinkingBubble(sessions: Int) {
    Row(
        Modifier
            .widthIn(max = 320.dp)
            .clip(CardShape)
            .background(Tk.surface)
            .border(2.dp, Tk.border, CardShape)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        repeat(3) { i -> ThinkingDot(delayMillis = i * 150) }
        Spacer(Modifier.size(6.dp))
        Text(revisandoLabel(sessions), style = mono(12, 0.05f, Tk.muted))
    }
}

/** The design's `dotPulse`: 1s in-out, each dot a step behind the last. */
@Composable
private fun ThinkingDot(delayMillis: Int) {
    val transition = rememberInfiniteTransition(label = "thinking")
    val alpha by transition.animateFloat(
        initialValue = 1f,
        targetValue = 0.2f,
        animationSpec = infiniteRepeatable(
            tween(500, delayMillis = delayMillis, easing = LinearEasing),
            RepeatMode.Reverse,
        ),
        label = "dot",
    )
    Box(Modifier.size(8.dp).alpha(alpha).background(Tk.ink, CircleShape))
}

/** The answer never came: human words and one way out, never a hanging
 *  question (the design's "nunca una pregunta sin respuesta visible"). */
@Composable
private fun RetryCard(onRetry: () -> Unit) {
    TkCard {
        Eyebrow("Sin respuesta")
        Spacer(Modifier.height(6.dp))
        Text(
            "Ahora mismo no he podido leer tus sesiones para contestar. " +
                "Revisa tu conexión y vuelve a intentarlo.",
            style = body(15, Tk.ink, 1.45f),
        )
        Spacer(Modifier.height(12.dp))
        TkSecondaryButton("Reintentar", onRetry)
    }
}

/** The empty conversation. No invented numbers: what the coach is for, and,
 *  with nothing filmed yet, the way to give it something to read. */
@Composable
private fun IntroCard(hasSessions: Boolean, onRecord: () -> Unit) {
    TkCard {
        Eyebrow("Tu coach")
        Spacer(Modifier.height(6.dp))
        Text(
            "Pregúntame lo que quieras sobre tus series. Contesto con lo que se ha " +
                "medido en tus vídeos: repeticiones, puntuaciones y fallos. Nada de opiniones.",
            style = body(15, Tk.ink, 1.45f),
        )
        if (!hasSessions) {
            Spacer(Modifier.height(16.dp))
            TkPrimaryButton("Grabar una serie", onRecord)
        }
    }
}

/** A session that could not be scored, said in the coach's own voice. */
@Composable
private fun NoticeCard(notice: String) {
    TkCard {
        Eyebrow("Sin puntuar")
        Spacer(Modifier.height(6.dp))
        Text(notice, style = body(15, Tk.ink, 1.45f))
    }
}

// ---- the chips and the field -----------------------------------------------

/** The chips above the field: the ones the last session suggests when the
 *  data brings them, otherwise generic ones named after what the screen does
 *  know (the movement of the last scored session). None with zero sessions. */
private fun suggestionChips(data: CoachData): List<String> {
    if (data.suggestions.isNotEmpty()) return data.suggestions
    if (data.sessions <= 0) return emptyList()
    return buildList {
        if (data.movement.isNotBlank()) add("¿Estoy mejorando en ${data.movement}?")
        add("¿Qué mostró realmente mi última sesión?")
        add("¿Por qué algunas repeticiones no tienen puntuación?")
    }
}

/** A visual 36dp pill the design draws, with the 48dp tap target around it. */
@Composable
private fun SuggestionChip(question: String, onAsk: () -> Unit) {
    Box(
        Modifier
            .heightIn(min = 48.dp)
            .noRipple(onAsk),
        contentAlignment = Alignment.Center,
    ) {
        Row(
            Modifier
                .heightIn(min = 36.dp)
                .clip(CircleShape)
                .background(Tk.bg)
                .border(2.dp, Tk.border, CircleShape)
                .padding(horizontal = 12.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(question, style = body(13, Tk.ink, 1.25f, FontWeight.SemiBold))
        }
    }
}

@Composable
private fun AskField(draft: String, onDraft: (String) -> Unit, modifier: Modifier = Modifier) {
    val focusRequester = remember { FocusRequester() }
    // The whole bordered area is the tap target, as in the chat sheet.
    Box(
        modifier
            .heightIn(min = 48.dp)
            .clip(InnerShape)
            .background(Tk.surface)
            .border(2.dp, Tk.border, InnerShape)
            .focusRequester(focusRequester)
            .noRipple { focusRequester.requestFocus() }
            .padding(horizontal = 12.dp, vertical = 13.dp),
        contentAlignment = Alignment.CenterStart,
    ) {
        BasicTextField(
            value = draft,
            onValueChange = onDraft,
            textStyle = body(15, Tk.ink, 1.3f),
            cursorBrush = SolidColor(Tk.primary),
            modifier = Modifier.fillMaxWidth(),
            decorationBox = { inner ->
                if (draft.isEmpty()) {
                    Text("Pregunta sobre tus series…", style = body(15, Tk.muted, 1.3f))
                }
                inner()
            },
            singleLine = true,
        )
    }
}

/** The design's orange send arrow, 48dp, ink border, 12dp corners. */
@Composable
private fun SendButton(enabled: Boolean, onSend: () -> Unit) {
    Box(
        Modifier
            .size(48.dp)
            .clip(InnerShape)
            .background(if (enabled) Tk.primary else Tk.locked)
            .border(2.dp, Tk.border, InnerShape)
            .semantics(mergeDescendants = true) { contentDescription = "Enviar pregunta" }
            .noRipple { if (enabled) onSend() },
        contentAlignment = Alignment.Center,
    ) {
        Text("↑", style = mono(18, 0f, if (enabled) Tk.ink else Tk.muted, FontWeight.SemiBold))
    }
}

// ---- labels ----------------------------------------------------------------

/** The design's header line, with the real number of sessions. */
private fun sessionsSubtitle(sessions: Int): String = when {
    sessions > 1 -> "RESPONDE CON TUS DATOS · $sessions SESIONES"
    sessions == 1 -> "RESPONDE CON TUS DATOS · 1 SESIÓN"
    else -> "RESPONDE CON TUS DATOS"
}

private fun revisandoLabel(sessions: Int): String = when {
    sessions > 1 -> "REVISANDO $sessions SESIONES"
    sessions == 1 -> "REVISANDO 1 SESIÓN"
    else -> "REVISANDO TUS SESIONES"
}
