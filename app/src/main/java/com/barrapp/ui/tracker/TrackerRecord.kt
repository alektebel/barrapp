package com.barrapp.ui.tracker

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.barrapp.repFaults
import com.barrapp.ui.theme.T
import com.barrapp.ui.theme.Tk
import com.barrapp.ui.theme.body
import com.barrapp.ui.theme.display
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
    /** This score minus the athlete's mean for the movement (+4 = four
     *  points over it). Null when there is no mean yet: the results lead
     *  then omits the comparison line instead of inventing one. */
    val vsAverage: Int? = null,
    /** Which set of the day this is ("Serie 2"). Blank when the caller
     *  cannot know; the header then shows only the movement. */
    val seriesLabel: String = "",
    /** When the set was recorded, in human words ("Hoy 18:42"). Blank when
     *  unknown; the header then shows only the rep count. */
    val whenLabel: String = "",
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
    /** Opens the fault viewer on fault [i] (the order of [ResultsData.fixes]).
     *  The viewer itself is FaultViewer.kt; this screen only points at it. */
    onOpenFault: ((Int) -> Unit)? = null,
    onShare: (() -> Unit)? = null,
    onBack: (() -> Unit)? = null,
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
        if (phase == RecordPhase.RESULTS && results != null) {
            // The set names the page (2b): movement · set, and when · how many.
            ResultsHeader(results, onBack)
        } else {
            Column(Modifier.padding(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 8.dp)) {
                Text("BarrApp", style = T.eyebrowWide)
                Text(
                    if (phase == RecordPhase.RESULTS) "ANÁLISIS" else "GRABAR SET",
                    style = T.pageTitle,
                )
            }
        }
        when (phase) {
            RecordPhase.IDLE -> IdlePhase(lastAnalyzed, onRecord, onPick)
            RecordPhase.ANALYZING -> AnalyzingPhase(stages, activeStage)
            RecordPhase.RESULTS -> results?.let {
                ResultsPhase(
                    it, onDone, replayAnalysis, replayClip, onExpandReplay, onOpenFault, onShare,
                )
            }
                ?: IdlePhase(lastAnalyzed, onRecord, onPick)
        }
    }
}

/** «DOMINADA · SERIE 1» — the movement, and where this set sits. */
internal fun resultsHeaderTitle(results: ResultsData): String =
    listOfNotNull(
        results.movement,
        results.seriesLabel.takeIf { it.isNotBlank() },
    ).joinToString(" · ")

/** «HOY 18:42 · 6 REPS» — when it was, and how many reps it counted. */
internal fun resultsHeaderMeta(results: ResultsData): String =
    (listOfNotNull(results.whenLabel.takeIf { it.isNotBlank() }) + "${results.reps} reps")
        .joinToString(" · ")

@Composable
private fun ResultsHeader(results: ResultsData, onBack: (() -> Unit)?) {
    Row(
        Modifier
            .fillMaxWidth()
            .padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (onBack != null) {
            Box(
                Modifier
                    .size(44.dp)
                    .clip(InnerShape)
                    .background(Tk.surface)
                    .border(2.dp, Tk.border, InnerShape)
                    .clickable(onClick = onBack)
                    .semantics { contentDescription = "Volver" },
                contentAlignment = Alignment.Center,
            ) {
                Text("←", style = display(18, color = Tk.ink))
            }
        }
        Column {
            Text(resultsHeaderTitle(results).uppercase(), style = display(20, FontWeight.Black, 1f))
            Text(resultsHeaderMeta(results).uppercase(), style = mono(11, 0.05f, Tk.muted))
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
                    // The screen's one main action, so it wears the hard shadow.
                    .hardShadow(CircleShape)
                    .clip(CircleShape)
                    .background(Tk.primary)
                    .border(2.dp, Tk.border, CircleShape)
                    .noRipple(onRecord)
                    .semantics {
                        role = Role.Button
                        contentDescription = "Grabar un set"
                    },
                contentAlignment = Alignment.Center,
            ) {
                Box(
                    Modifier.size(40.dp).clip(CircleShape).background(Tk.onInk.copy(alpha = 0.25f)),
                    contentAlignment = Alignment.Center,
                ) {
                    Box(Modifier.size(20.dp).clip(CircleShape).background(Tk.onInk))
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
                    .background(Tk.surface)
                    .border(2.dp, Tk.border, CircleShape),
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

/** One bar of the set's timeline: a rep drawn to its score. */
internal data class RepBar(
    /** 0-based, the index the replay and the fault viewer speak in. */
    val index: Int,
    /** null = sin medir: grey, "—", never a zero. */
    val score: Int?,
    val faulted: Boolean,
    /** Where the clip lands when the bar is tapped; null when unknown. */
    val startS: Double?,
)

/** The timeline's data, from the measurement when there is one, else from
 *  the pre-drawn cards an older result already carries. */
internal fun repBars(
    analysis: com.barrapp.data.Analysis?,
    cards: List<RepCardItem>,
): List<RepBar> = when {
    analysis != null && analysis.reps.isNotEmpty() -> analysis.reps.mapIndexed { i, rep ->
        RepBar(i, rep.score, repFaults(rep).isNotEmpty(), rep.startS)
    }
    else -> cards.mapIndexed { i, card ->
        RepBar(i, card.score, card.faults.isNotEmpty(), null)
    }
}

/** «0:14» — minutes:seconds, the clip's clock. */
internal fun clockMmSs(seconds: Double): String {
    val t = seconds.coerceAtLeast(0.0).toInt()
    return "%d:%02d".format(t / 60, t % 60)
}

/** «LÍNEA DE TIEMPO · 0:24», or just «LÍNEA DE TIEMPO» when the length is unknown. */
internal fun timelineLabel(analysis: com.barrapp.data.Analysis?): String {
    val d = analysis?.durationS ?: 0.0
    return if (d > 0.0) "Línea de tiempo · ${clockMmSs(d)}" else "Línea de tiempo"
}

/** «VER VÍDEO COMPLETO · 0:24». */
internal fun fullClipLabel(analysis: com.barrapp.data.Analysis?): String {
    val d = analysis?.durationS ?: 0.0
    return if (d > 0.0) "Ver vídeo completo · ${clockMmSs(d)}" else "Ver vídeo completo"
}

/** «En las reps 4, 5 y 6.» — where the measured faults fall; null when none. */
internal fun faultRepsSentence(repsWithFaults: List<Int>): String? {
    if (repsWithFaults.isEmpty()) return null
    val nums = repsWithFaults.sorted()
    return if (nums.size == 1) "En la rep ${nums.first()}."
    else "En las reps " + nums.dropLast(1).joinToString(", ") + " y ${nums.last()}."
}

/** «Las 3 primeras están limpias.» — said only when the measurement says it:
 *  the leading run of scored, fault-free reps before the first fault. */
internal fun leadingCleanSentence(bars: List<RepBar>): String? {
    val clean = bars.takeWhile { it.score != null && !it.faulted }.size
    val rest = bars.drop(clean)
    if (clean == 0 || rest.isEmpty() || rest.none { it.faulted }) return null
    return if (clean == 1) "La primera está limpia." else "Las $clean primeras están limpias."
}

/**
 * «+4 respecto a tu media de dominada» — the comparison with the athlete's
 * own mean. Omits the line when there is no mean: the first measurement has
 * nothing to compare against, and inventing a baseline is the one thing this
 * screen must not do. Falls back to the qualitative comparison while the
 * numeric one is not wired.
 */
internal fun versusAverageLine(delta: Int?, aboveAverage: Boolean?, movement: String): String? {
    val base = movement.trim().lowercase().ifBlank { "este movimiento" }
    return when {
        delta == null && aboveAverage == null -> null
        delta != null && delta > 0 -> "+$delta respecto a tu media de $base"
        delta != null && delta < 0 -> "$delta respecto a tu media de $base"
        delta != null -> "En tu media de $base"
        aboveAverage == true -> "Por encima de tu media de $base"
        else -> "Algo por debajo de tu media de $base"
    }
}

/** One tap into the fault viewer: a fault and the rep that shows it. */
internal data class FaultThumb(
    val title: String,
    /** 1-based; null when no single rep stands for it. */
    val repNumber: Int?,
    /** The rep's moment in the clip, «0:14»; null when unknown. */
    val timeLabel: String?,
    /** The index the viewer is opened on. */
    val openIndex: Int,
)

/**
 * The thumbnails under «FALLOS DETECTADOS»: one per ranked fix (the faults
 * the screen already ranks), each with the rep that demonstrates it. When no
 * fixes came, the fault list itself stands in — without a rep to point at.
 */
internal fun faultThumbs(
    results: ResultsData,
    analysis: com.barrapp.data.Analysis?,
): List<FaultThumb> {
    val items: List<Pair<String, Int?>> = when {
        results.fixes.isNotEmpty() -> results.fixes.map { it.title to it.repIndex }
        else -> results.faults.take(3).map { it.first to null }
    }
    return items.take(3).mapIndexed { i, (title, repIndex) ->
        FaultThumb(
            title = title,
            repNumber = repIndex?.plus(1),
            timeLabel = repIndex?.let { idx ->
                analysis?.reps?.getOrNull(idx)?.startS?.let(::clockMmSs)
            },
            openIndex = i,
        )
    }
}

@Composable
private fun ResultsPhase(
    results: ResultsData,
    onDone: () -> Unit,
    analysis: com.barrapp.data.Analysis? = null,
    clip: java.io.File? = null,
    onExpandReplay: (() -> Unit)? = null,
    onOpenFault: ((Int) -> Unit)? = null,
    onShare: (() -> Unit)? = null,
) {
    val scroll = rememberScrollState()
    val scope = androidx.compose.runtime.rememberCoroutineScope()
    val replay = com.barrapp.ui.replay.rememberRepReplayState()
    // The set itself comes first: the counter rising rep by rep over the
    // video is the result, the cards below explain it.
    val playable = analysis != null && clip != null && results.reps > 0 &&
        analysis.reps.any { it.endS > it.startS }
    var selectedRep by rememberSaveable { mutableIntStateOf(-1) }
    val showRep: (Int) -> Unit = { index ->
        selectedRep = index
        if (playable) {
            // The state lands on the rep's turnaround and holds there; the
            // scroll brings the clip back into view.
            replay.showRep(index)
            scope.launch { scroll.animateScrollTo(0) }
        }
    }
    val bars = repBars(analysis, results.repCards)

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

        if (results.reps > 0 && bars.isNotEmpty()) {
            SlideUp {
                Column {
                    Text(timelineLabel(analysis), style = mono(11, 0.05f, Tk.muted))
                    Spacer(Modifier.height(8.dp))
                    RepTimeline(bars, selectedRep, playable, showRep)
                    bars.getOrNull(selectedRep)?.let { RepSelectionLine(it) }
                }
            }
        }

        if (results.reps > 0) {
            SlideUp(delayMillis = 40) { ScoreBlock(results) }
        }

        // 3a: the faults lead — how many, where they fall, and the way into
        // each one. A set measured clean says so instead, and asks nothing.
        if (results.reps > 0 && results.unjudged == null) {
            SlideUp(delayMillis = 80) { FaultsBlock(results, bars, analysis, onOpenFault) }
            if (results.faults.isNotEmpty() && playable && onExpandReplay != null) {
                SlideUp(delayMillis = 100) {
                    TkSecondaryButton(fullClipLabel(analysis), onExpandReplay)
                }
            }
        }

        // Short by default (docs/UX-PLAN.md): what to fix, in order. A set
        // with nothing counted says why instead. Everything else is one tap away.
        if (results.reps > 0) {
            SlideUp(delayMillis = 120) {
                FixesCard(
                    results.fixes,
                    onShowRep = if (playable) showRep else null,
                    unjudged = results.unjudged,
                    selectedRep = selectedRep.takeIf { it >= 0 },
                )
            }
        } else if (results.headline.isNotBlank() || results.blockers.isNotEmpty()) {
            SlideUp(delayMillis = 60) { WhatHappened(results) }
        }

        var detail by rememberSaveable { mutableStateOf(false) }
        if (results.reps > 0) {
            TkSecondaryButton(if (detail) "Ocultar detalle" else "Ver detalle", { detail = !detail })
        }
        if (detail && results.reps > 0 &&
            (results.headline.isNotBlank() || results.narrative.isNotBlank())) {
            WhatHappened(results)
        }

        if (detail) {
            results.repCards.forEachIndexed { i, rep ->
                SlideUp(delayMillis = 200 + i * 60) { RepCard(rep) }
            }
        }

        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            if (onShare != null) {
                TkSecondaryButton("Compartir", onShare, Modifier.weight(1f))
            }
            TkPrimaryButton(
                if (results.reps > 0) "Siguiente serie" else "Volver al inicio",
                onDone,
                Modifier.weight(if (onShare != null) 2f else 1f),
            )
        }
    }
}

/**
 * The set's timeline (2b, 3a): one bar per rep, its height the rep's score,
 * its colour the band's, the selected rep inked. Faulted reps carry the
 * orange dot of 3a, so where the faults fall is readable at a glance.
 * Unmeasured reps are grey stubs with «—»: counted, never judged.
 */
@Composable
private fun RepTimeline(
    bars: List<RepBar>,
    selectedRep: Int,
    playable: Boolean,
    onSelect: (Int) -> Unit,
) {
    Row(
        Modifier.fillMaxWidth().heightIn(min = 48.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        bars.forEachIndexed { i, bar ->
            val selected = i == selectedRep
            val shape = RoundedCornerShape(10.dp)
            Column(
                Modifier
                    .weight(1f)
                    .then(if (playable) Modifier.clickable { onSelect(i) } else Modifier)
                    .semantics {
                        contentDescription = "Rep ${i + 1}, " + when {
                            bar.score == null -> "sin medir"
                            bar.faulted -> "puntuación ${bar.score}, con fallo"
                            else -> "puntuación ${bar.score}, limpia"
                        }
                        if (playable) role = Role.Button
                    }
                    .padding(vertical = 2.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                // The 3a dot lives above the bar, in its own lane, so bars
                // keep bottom-aligned whether they carry one or not.
                Box(Modifier.height(14.dp), contentAlignment = Alignment.BottomCenter) {
                    if (bar.faulted) {
                        Box(
                            Modifier
                                .size(12.dp)
                                .clip(CircleShape)
                                .background(Tk.primary)
                                .border(2.dp, Tk.border, CircleShape),
                        )
                    }
                }
                Spacer(Modifier.height(2.dp))
                Box(
                    Modifier
                        .fillMaxWidth()
                        .height(barHeight(bar.score))
                        .clip(shape)
                        .background(if (bar.score == null) Tk.locked else scoreInk(bar.score))
                        .then(if (selected) Modifier.border(2.dp, Tk.border, shape) else Modifier),
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    bar.score?.toString() ?: "—",
                    style = mono(
                        11, 0f,
                        if (selected) Tk.ink else Tk.muted,
                        if (selected) FontWeight.SemiBold else FontWeight.Normal,
                    ),
                )
            }
        }
    }
}

/** A rep's bar: its score to scale, a stub when nothing was measured. */
private fun barHeight(score: Int?): Dp =
    if (score == null) 6.dp
    else (score.coerceIn(0, 100) * 0.44f).dp.coerceAtLeast(6.dp)

/** «REP 4 · 0:14   59 · INESTABLE» — what a tap on the timeline picked. */
@Composable
private fun RepSelectionLine(bar: RepBar) {
    Row(
        Modifier
            .fillMaxWidth()
            .padding(top = 8.dp)
            .semantics { liveRegion = LiveRegionMode.Polite },
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text(
            "REP ${bar.index + 1}" + (bar.startS?.let { " · ${clockMmSs(it)}" } ?: ""),
            style = mono(12, 0f, Tk.ink, FontWeight.SemiBold),
        )
        Text(
            if (bar.score == null) "Sin medir"
            else "${bar.score} · ${scoreLabel(bar.score).uppercase()}",
            style = mono(12, 0f, scoreInk(bar.score), FontWeight.SemiBold),
        )
    }
}

/** The note (2b): the score, its band's word, and the comparison with the
 *  athlete's own mean — or nothing, when there is no mean to compare to. */
@Composable
private fun ScoreBlock(results: ResultsData) {
    Row(
        Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text(
            results.score?.toString() ?: "—",
            style = display(
                52, FontWeight.Black, 0.9f,
                color = if (results.score == null) Tk.muted else Tk.ink,
            ),
        )
        Column {
            Text(
                scoreLabel(results.score).uppercase(),
                style = display(17, FontWeight.Black, 1f, color = scoreInk(results.score)),
            )
            versusAverageLine(results.vsAverage, results.aboveAverage, results.movement)?.let {
                Text(
                    it,
                    style = body(13, Tk.darkLine),
                    modifier = Modifier.padding(top = 2.dp),
                )
            }
        }
    }
}

/**
 * The faults, first (3a): an orange card because looking at them is the
 * action this screen asks for — the number, where they fall, a thumbnail
 * per fault, and the way into the viewer. Without faults: a quiet white
 * card saying the series is clean, and no button.
 */
@Composable
private fun FaultsBlock(
    results: ResultsData,
    bars: List<RepBar>,
    analysis: com.barrapp.data.Analysis?,
    onOpenFault: ((Int) -> Unit)?,
) {
    if (results.faults.isEmpty()) {
        TkCard {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Box(Modifier.size(8.dp).clip(CircleShape).background(Tk.teal))
                Text("Serie limpia", style = T.rowTitle)
            }
            Text(
                "Ningún fallo medido en esta serie.",
                style = T.bodyInk,
                modifier = Modifier.padding(top = 6.dp),
            )
        }
        return
    }
    TkCard(accent = true) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text("${results.faults.size}", style = display(46, FontWeight.Black, 0.9f, color = Tk.ink))
            Text("FALLOS DETECTADOS", style = display(20, FontWeight.Black, 1.05f, color = Tk.ink))
        }
        val sentence = listOfNotNull(
            faultRepsSentence(bars.filter { it.faulted }.map { it.index + 1 }),
            leadingCleanSentence(bars),
        ).joinToString(" ")
        if (sentence.isNotBlank()) {
            Text(
                sentence,
                style = body(14, Tk.ink, 1.4f),
                modifier = Modifier.padding(top = 8.dp),
            )
        }
        Spacer(Modifier.height(12.dp))
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            faultThumbs(results, analysis).forEach { thumb ->
                Box(Modifier.weight(1f)) {
                    FaultThumbCard(thumb, onOpenFault?.let { open -> { open(thumb.openIndex) } })
                }
            }
        }
        Spacer(Modifier.height(12.dp))
        // No hard shadow of its own: the card carries it already.
        TkPrimaryButton("Revisar fallos", { onOpenFault?.invoke(0) }, shadow = false)
    }
}

/** The 3a thumbnail: the rep's moment on the clip's dark, its number, and
 *  the fault's name. Opens the fault viewer on this fault. */
@Composable
private fun FaultThumbCard(thumb: FaultThumb, onOpen: (() -> Unit)?) {
    val shape = RoundedCornerShape(10.dp)
    Column(
        Modifier
            .then(if (onOpen != null) Modifier.clickable(onClick = onOpen) else Modifier)
            .semantics(mergeDescendants = true) {
                if (onOpen != null) role = Role.Button
                contentDescription = buildString {
                    append("Ver en el vídeo")
                    thumb.repNumber?.let { append(", rep $it") }
                    append(": ${thumb.title}")
                }
            }
            .padding(vertical = 2.dp),
    ) {
        Box(
            Modifier
                .fillMaxWidth()
                .height(92.dp)
                .clip(shape)
                .background(Tk.dark)
                .border(2.dp, Tk.border, shape),
        ) {
            thumb.timeLabel?.let {
                Text(
                    it,
                    style = mono(10, 0f, Tk.ink, FontWeight.SemiBold),
                    modifier = Modifier
                        .align(Alignment.TopStart)
                        .padding(6.dp)
                        .clip(RoundedCornerShape(4.dp))
                        .background(Tk.bg)
                        .padding(horizontal = 5.dp, vertical = 2.dp),
                )
            }
            Canvas(Modifier.size(20.dp).align(Alignment.Center)) {
                val w = size.width
                val h = size.height
                drawPath(
                    Path().apply {
                        moveTo(w * 0.22f, h * 0.08f)
                        lineTo(w * 0.85f, h * 0.5f)
                        lineTo(w * 0.22f, h * 0.92f)
                        close()
                    },
                    Tk.primary,
                )
            }
        }
        if (thumb.repNumber != null) {
            Text(
                "REP ${thumb.repNumber}",
                style = mono(11, 0f, Tk.ink, FontWeight.SemiBold),
                modifier = Modifier.padding(top = 5.dp),
            )
        }
        Text(
            thumb.title,
            style = mono(11, 0f, Tk.ink, FontWeight.SemiBold, 1.2f),
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
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
