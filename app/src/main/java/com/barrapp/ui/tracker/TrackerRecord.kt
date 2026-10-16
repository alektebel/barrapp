package com.barrapp.ui.tracker

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import com.barrapp.ui.theme.T
import com.barrapp.ui.theme.Tk
import com.barrapp.ui.theme.body
import kotlinx.coroutines.launch
import com.barrapp.ui.theme.mono
import com.barrapp.ui.theme.scoreInk
import com.barrapp.ui.theme.scoreLabel

enum class RecordPhase { IDLE, ANALYZING, RESULTS }

/** One rep as the results list draws it. */
data class RepCardItem(
    val label: String,
    val score: Int?,
    val faults: List<String>,
    val times: String,
    /** Set when the rep was measured but withheld from the checks. */
    val blocked: String?,
)

data class ResultsData(
    /** What happened, in the server's (Spanish) words: the report's headline
     *  and narrative, why nothing was counted, and what to film next. Before
     *  these were shown, a clip with 0 reps said "0 reps" and nothing else. */
    val headline: String = "",
    val narrative: String = "",
    val blockers: List<String> = emptyList(),
    val nextSession: String = "",
    /** The three things to improve, most important first (Fixes.kt). */
    val fixes: List<FixItem> = emptyList(),
    val movement: String,
    val setsLabel: String,
    val reps: Int,
    val score: Int?,
    val faults: List<Pair<String, Int>>,
    val repCards: List<RepCardItem>,
    val xp: Int,
    /** Why a counted set could not be judged; null when it was. */
    val unjudged: String? = null,
    /** null when there is no earlier training to compare against. */
    val aboveAverage: Boolean?,
)

data class LastAnalyzed(val movement: String, val meta: String, val score: Int?)

/** One declaration choice — the value is the server's own vocabulary. */
data class Choice(val label: String, val value: String)

val STANDARDS_ES = listOf(
    Choice("Sin declarar", ""),
    Choice("Estricto", "strict"),
    Choice("Kipping", "kipping"),
)

/** The label a stored value wears; the blank choice when it is unknown. */
fun List<Choice>.label(value: String): String =
    (firstOrNull { it.value == value } ?: first()).label

val CAMERAS_ES = listOf(
    Choice("No lo sé", ""),
    Choice("De lado", "SAGITTAL"),
    Choice("De frente", "FRONTAL"),
)

/**
 * Grabar.
 *
 * The mockup's three phases, driven by the real queue rather than a timer: the
 * analysing stages are the stages the work reports, and the results are the
 * measurement the server returned. The mockup's fake 900ms-per-step ticker is
 * gone — a progress animation that finishes before the work does is the one
 * thing this screen must not do.
 */
@Composable
fun TrackerRecord(
    phase: RecordPhase,
    stages: List<String>,
    activeStage: Int,
    results: ResultsData?,
    lastAnalyzed: LastAnalyzed?,
    standard: String,
    camera: String,
    onStandard: (String) -> Unit,
    onCamera: (String) -> Unit,
    onRecord: () -> Unit,
    onPick: () -> Unit,
    onDone: () -> Unit,
    resultJobId: String? = null,
    resultTraceId: String = "",
    currentResultTraceId: String? = null,
    onResultRendered: ((String, String) -> Unit)? = null,
    /** The measurement and the phone's copy of the clip it measured. Both
     *  present: the results lead with the set playing back. */
    replayAnalysis: com.barrapp.data.Analysis? = null,
    replayClip: java.io.File? = null,
    onExpandReplay: (() -> Unit)? = null,
    modifier: Modifier = Modifier,
) {
    LaunchedEffect(phase, results != null, resultJobId, resultTraceId, currentResultTraceId) {
        if (shouldMarkResultRendered(
                phase, results != null, resultJobId, resultTraceId, currentResultTraceId,
            ) && onResultRendered != null
        ) {
            // ResultsPhase has been composed; wait for its first frame before
            // recording the phone-visible endpoint.
            withFrameNanos { }
            resultJobId?.let { onResultRendered(it, resultTraceId) }
        }
    }
    Column(modifier.fillMaxSize()) {
        Column(Modifier.padding(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 8.dp)) {
            Text("BarrApp", style = T.eyebrowWide)
            Text(
                if (phase == RecordPhase.RESULTS) "ANÁLISIS" else "GRABAR SET",
                style = T.pageTitle,
            )
        }
        when (phase) {
            RecordPhase.IDLE -> IdlePhase(lastAnalyzed, onRecord, onPick)
            RecordPhase.ANALYZING -> AnalyzingPhase(stages, activeStage)
            RecordPhase.RESULTS -> results?.let {
                ResultsPhase(it, onDone, replayAnalysis, replayClip, onExpandReplay)
            }
                ?: IdlePhase(lastAnalyzed, onRecord, onPick)
        }
    }
}

@Composable
private fun IdlePhase(
    lastAnalyzed: LastAnalyzed?,
    onRecord: () -> Unit,
    onPick: () -> Unit,
) {
    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp)
            .padding(bottom = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(Modifier.height(20.dp))
        Box(contentAlignment = Alignment.Center) {
            PulseRing(Modifier.size(140.dp))
            Box(
                Modifier
                    .size(112.dp)
                    .clip(CircleShape)
                    .background(Brush.linearGradient(listOf(Tk.primary, Tk.primaryLight)))
                    .noRipple(onRecord),
                contentAlignment = Alignment.Center,
            ) {
                Box(
                    Modifier.size(40.dp).clip(CircleShape).background(Color.White.copy(alpha = 0.2f)),
                    contentAlignment = Alignment.Center,
                ) {
                    Box(Modifier.size(20.dp).clip(CircleShape).background(Color.White))
                }
            }
        }
        Spacer(Modifier.height(24.dp))
        Text("GRABAR UN SET", style = T.sectionTitle)
        Spacer(Modifier.height(4.dp))
        Text(
            "Coloca el teléfono de lado, pulsa grabar y empieza tu serie.",
            style = T.bodyS,
            textAlign = androidx.compose.ui.text.style.TextAlign.Center,
            modifier = Modifier.width(220.dp),
        )
        Spacer(Modifier.height(24.dp))

        Row(
            Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Box(Modifier.weight(1f).height(1.dp).background(Tk.border))
            Text("O", style = mono(10))
            Box(Modifier.weight(1f).height(1.dp).background(Tk.border))
        }
        Spacer(Modifier.height(20.dp))
        TkSecondaryButton("Subir vídeo", onPick)

        // Nothing to declare before a set: the server reads the camera angle
        // and the movement from the clip, and checks that depend on a
        // standard nobody declared are marked as such, never assumed.
        Spacer(Modifier.height(28.dp))
        TkCard {
            Eyebrow("Última sesión analizada")
            Spacer(Modifier.height(8.dp))
            if (lastAnalyzed == null) {
                Text("Todavía ninguna", style = T.rowTitle)
                Text(
                    "El primer clip que midas aparecerá aquí.",
                    style = T.bodyS, modifier = Modifier.padding(top = 2.dp),
                )
            } else {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(lastAnalyzed.movement.uppercase(), style = T.rowTitle)
                        Text(lastAnalyzed.meta, style = T.bodyS)
                    }
                    Text(
                        lastAnalyzed.score?.toString() ?: "—",
                        style = T.cardHeadline.copy(color = scoreInk(lastAnalyzed.score)),
                    )
                }
            }
        }
    }
}

@Composable
private fun AnalyzingPhase(stages: List<String>, activeStage: Int) {
    Column(
        Modifier.fillMaxSize().padding(horizontal = 32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Box(contentAlignment = Alignment.Center) {
            PulseRing(Modifier.size(112.dp))
            PulseRing(Modifier.size(128.dp), stroke = 1.dp, delayMillis = 300)
            Box(
                Modifier
                    .size(96.dp)
                    .clip(CircleShape)
                    .background(Tk.primaryA(0.1f))
                    .border(2.dp, Tk.primaryA(0.3f), CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                Canvas(Modifier.size(40.dp)) { drawCamera() }
            }
        }
        Spacer(Modifier.height(32.dp))
        Text("ANALIZANDO", style = T.eyebrowAccent)
        Spacer(Modifier.height(8.dp))
        Text(
            stages.getOrElse(activeStage) { stages.lastOrNull().orEmpty() }.uppercase(),
            style = T.cardHeadline,
            textAlign = androidx.compose.ui.text.style.TextAlign.Center,
        )
        Spacer(Modifier.height(8.dp))
        Text(
            "Puedes salir de la app: te avisamos cuando esté. Después verás tu serie " +
                "con cada repetición marcada.",
            style = T.noteTiny,
            textAlign = androidx.compose.ui.text.style.TextAlign.Center,
        )
        Spacer(Modifier.height(24.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            stages.indices.forEach { i ->
                Box(
                    Modifier
                        .width(if (i <= activeStage) 20.dp else 6.dp)
                        .height(4.dp)
                        .clip(RoundedCornerShape(2.dp))
                        .background(if (i <= activeStage) Tk.primary else Tk.border),
                )
            }
        }
    }
}

@Composable
internal fun WhatHappened(results: ResultsData) {
    TkCard {
        Eyebrow("Qué ha pasado")
        if (results.headline.isNotBlank()) {
            Text(results.headline, style = T.cardHeadline, modifier = Modifier.padding(top = 8.dp))
        }
        if (results.narrative.isNotBlank()) {
            Text(results.narrative, style = T.bodyS, modifier = Modifier.padding(top = 6.dp))
        }
        if (results.blockers.isNotEmpty()) {
            Text(
                if (results.reps == 0) "Por qué no se contó nada" else "Notas",
                style = mono(10, 0.05f, Tk.amber),
                modifier = Modifier.padding(top = 12.dp),
            )
            results.blockers.forEach { b ->
                Row(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Box(Modifier.padding(top = 7.dp).size(5.dp).clip(CircleShape).background(Tk.amber))
                    Text(b, style = T.bodyInk)
                }
            }
        }
        if (results.nextSession.isNotBlank()) {
            Text("Para la próxima", style = mono(10, 0.05f, Tk.primary), modifier = Modifier.padding(top = 12.dp))
            Text(results.nextSession, style = T.bodyS, modifier = Modifier.padding(top = 4.dp))
        }
    }
}

@Composable
private fun ResultsPhase(
    results: ResultsData,
    onDone: () -> Unit,
    analysis: com.barrapp.data.Analysis? = null,
    clip: java.io.File? = null,
    onExpandReplay: (() -> Unit)? = null,
) {
    val scroll = rememberScrollState()
    val scope = androidx.compose.runtime.rememberCoroutineScope()
    val replay = com.barrapp.ui.replay.rememberRepReplayState()
    // The set itself comes first: the counter rising rep by rep over the
    // video is the result, the cards below explain it.
    val playable = analysis != null && clip != null && results.reps > 0 &&
        analysis.reps.any { it.endS > it.startS }
    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(scroll)
            .padding(horizontal = 16.dp)
            .padding(bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        if (playable) {
            com.barrapp.ui.replay.RepReplay(
                analysis = analysis!!,
                clip = clip!!,
                state = replay,
                onExpand = onExpandReplay,
            )
        }
        SlideUp {
            TkCard(accent = true) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    ScoreRing(results.score, size = 72.dp, stroke = 6.dp)
                    Spacer(Modifier.width(16.dp))
                    Column {
                        Eyebrow("Movimiento", style = mono(10, 0.05f, Tk.primary))
                        Text(results.movement.uppercase(), style = T.cardHeadline)
                        Text(
                            "${results.setsLabel} · ${results.reps} reps en total",
                            style = T.bodyS,
                        )
                        Text(
                            scoreLabel(results.score) + when (results.aboveAverage) {
                                true -> " — por encima de tu media"
                                false -> " — algo por debajo de tu media"
                                null -> " — tu primera medición"
                            },
                            style = mono(10, 0.05f, scoreInk(results.score)),
                            modifier = Modifier.padding(top = 4.dp),
                        )
                    }
                }
            }
        }

        // Short by default (docs/UX-PLAN.md): what to fix, in order. A set
        // with nothing counted says why instead. Everything else is one tap away.
        if (results.reps > 0) {
            SlideUp(delayMillis = 60) {
                FixesCard(
                    results.fixes,
                    unjudged = results.unjudged,
                    onShowRep = if (playable) { index ->
                        replay.showRep(index)
                        scope.launch { scroll.animateScrollTo(0) }
                    } else null,
                )
            }
        } else if (results.headline.isNotBlank() || results.blockers.isNotEmpty()) {
            SlideUp(delayMillis = 60) { WhatHappened(results) }
        }

        var detail by androidx.compose.runtime.saveable.rememberSaveable {
            androidx.compose.runtime.mutableStateOf(false)
        }
        if (results.reps > 0) {
            TkSecondaryButton(if (detail) "Ocultar detalle" else "Ver detalle", { detail = !detail })
        }
        if (detail && results.reps > 0 &&
            (results.headline.isNotBlank() || results.narrative.isNotBlank())) {
            WhatHappened(results)
        }

        if (detail && results.faults.isNotEmpty()) {
            SlideUp(delayMillis = 100) {
                TkCard {
                    Eyebrow("Errores detectados")
                    Spacer(Modifier.height(12.dp))
                    results.faults.forEach { (fault, count) ->
                        Row(
                            Modifier.fillMaxWidth().padding(bottom = 8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(12.dp),
                        ) {
                            Box(Modifier.size(6.dp).clip(CircleShape).background(Tk.amber))
                            Text(fault, style = T.bodyInk, modifier = Modifier.weight(1f))
                            Text("$count reps", style = mono(9, 0.05f, Tk.amber))
                        }
                    }
                }
            }
        }

        if (detail) {
            results.repCards.forEachIndexed { i, rep ->
                SlideUp(delayMillis = 200 + i * 60) { RepCard(rep) }
            }
        }

        TkPrimaryButton(
            if (results.xp > 0) "Guardar sesión (+${results.xp} XP)" else "Volver al inicio",
            onDone,
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun RepCard(rep: RepCardItem) {
    Row(
        Modifier
            .fillMaxWidth()
            .clip(InnerShape)
            .background(Tk.card)
            .border(1.dp, Tk.border, InnerShape)
            .padding(12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        ScoreRing(rep.score, size = 48.dp, stroke = 4.dp)
        Column(Modifier.weight(1f)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(rep.label.uppercase(), style = T.eyebrowNine)
                Text(scoreLabel(rep.score), style = mono(9, 0.05f, scoreInk(rep.score)))
                Text(rep.times, style = mono(9, 0f, Tk.faint))
            }
            Spacer(Modifier.height(4.dp))
            when {
                rep.blocked != null -> Text(rep.blocked, style = body(10, Tk.muted))
                rep.faults.isEmpty() && rep.score != null -> Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Box(Modifier.size(6.dp).clip(CircleShape).background(Tk.teal))
                    Text("Rep limpia", style = body(10, Tk.teal))
                }
                rep.faults.isEmpty() -> Text(
                    "Sin medir — la pose no se pudo leer en esta rep.",
                    style = body(10, Tk.muted),
                )
                else -> FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(4.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    rep.faults.forEach { FaultChip(it) }
                }
            }
        }
    }
}

/** The camera the analysing screen pulses behind. */
private fun androidx.compose.ui.graphics.drawscope.DrawScope.drawCamera() {
    val s = size.width / 40f
    drawRoundRect(
        color = Tk.primary,
        topLeft = Offset(4f * s, 12f * s),
        size = Size(32f * s, 22f * s),
        cornerRadius = androidx.compose.ui.geometry.CornerRadius(3f * s, 3f * s),
        style = Stroke(2f * s),
    )
    drawLine(Tk.primaryA(0.4f), Offset(4f * s, 17f * s), Offset(36f * s, 17f * s), 1.5f * s)
    drawCircle(Tk.primaryA(0.3f), 5f * s, Offset(20f * s, 25f * s))
    drawCircle(Tk.primaryLight, 5f * s, Offset(20f * s, 25f * s), style = Stroke(1.5f * s))
    drawCircle(Tk.primaryLight, 2f * s, Offset(20f * s, 25f * s))
}
