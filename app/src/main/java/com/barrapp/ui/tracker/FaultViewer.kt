package com.barrapp.ui.tracker

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBars
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.barrapp.cueEs
import com.barrapp.data.Analysis
import com.barrapp.data.MeasuredFault
import com.barrapp.data.RepRow
import com.barrapp.faultEs
import com.barrapp.movementEs
import com.barrapp.ui.replay.ReplayPlan
import com.barrapp.ui.theme.Tk
import com.barrapp.ui.theme.body
import com.barrapp.ui.theme.display
import com.barrapp.ui.theme.mono
import java.io.File
import java.util.Locale
import kotlin.math.roundToLong
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext

/**
 * The fault viewer (design 3b): each measured fault is a story that opens on
 * the rep's key frame, zooms into the body region that failed and then says
 * what was measured and what to do about it. It advances on its own, pauses
 * from the top, and the sides step back and forward.
 *
 * The phone has no skeleton: only the clip's own frame is shown, enlarged —
 * the mock's drawn bones, angle arcs and green "correct position" need
 * keypoints the server does not send yet (see TIZA_NOTES.md).
 *
 * Everything that decides what appears — the slides built from an [Analysis],
 * the story's wrap-around, the zoom target per body region — is a pure
 * function here so the JVM tests can pin it without a device.
 */

/** One fault, told as one story slide. Built by [faultSlides]. */
data class FaultSlide(
    val rep: Int,            // número de rep (1-based)
    val atS: Double,         // segundo del vídeo del fotograma clave
    val title: String,       // «BALANCEO AL SUBIR» (en mayúsculas)
    val short: String,       // «BALANCEO»
    val value: String,       // «19°»  (valor medido, ya formateado)
    val goal: String,        // «OBJETIVO MENOS DE 8°»
    val why: String,         // explicación humana
    val cue: String,         // instrucción para la próxima serie
    val region: BodyRegion,  // zona a ampliar
)

enum class BodyRegion { UPPER, MIDDLE, LOWER, FULL }

/** Where the zoom lands on the video box: origin fractions and the scale. */
data class ZoomTarget(val x: Float, val y: Float, val scale: Float)

/** The design's story timing: the zoom lands 600 ms in, each slide holds 4 s. */
const val SLIDE_MS = 4_000L
const val ZOOM_DELAY_MS = 600L

/** At most three stories: three things is what carries into the next set. */
const val MAX_SLIDES = 3

/** The design's own `cubic-bezier(.22,1,.36,1)`, used by every Tiza motion. */
val TizaEasing = CubicBezierEasing(0.22f, 1f, 0.36f, 1f)

// ---------------------------------------------------------------------------
// Pure logic, testable without Android
// ---------------------------------------------------------------------------

private val REGION_UPPER = setOf("lockout", "elbow", "chin", "range", "top")
private val REGION_MIDDLE = setOf("hip", "swing", "kip", "sag", "core")
private val REGION_LOWER = setOf("knee", "depth", "foot", "leg")

/** The words of a rule id, snake_case or camelCase: `body_swing` → [body, swing]. */
internal fun faultWords(id: String): List<String> =
    id.replace(Regex("(?<=[a-z0-9])(?=[A-Z])"), "_")
        .lowercase()
        .split(Regex("[^a-z0-9]+"))
        .filter { it.isNotBlank() }

/**
 * The body region a failing rule points at, by the words of its id —
 * lockout/elbow/chin/range/top zoom high, hip/swing/kip/sag/core to the
 * middle, knee/depth/foot/leg low, anything else stays wide.
 */
fun regionFor(errorId: String): BodyRegion {
    val words = faultWords(errorId).toSet()
    return when {
        words.any { it in REGION_UPPER } -> BodyRegion.UPPER
        words.any { it in REGION_MIDDLE } -> BodyRegion.MIDDLE
        words.any { it in REGION_LOWER } -> BodyRegion.LOWER
        else -> BodyRegion.FULL
    }
}

/** The story loops: the slide after [index], wrapping past the end. */
fun nextSlide(index: Int, count: Int): Int =
    if (count <= 0) 0 else (index + 1).mod(count)

/** The story loops: the slide before [index], wrapping past the start. */
fun prevSlide(index: Int, count: Int): Int =
    if (count <= 0) 0 else (index - 1).mod(count)

/** Where a region's zoom pivots and how far it pushes in. */
fun zoomTarget(region: BodyRegion): ZoomTarget = when (region) {
    BodyRegion.UPPER -> ZoomTarget(0.5f, 0.18f, 1.6f)
    BodyRegion.MIDDLE -> ZoomTarget(0.5f, 0.45f, 1.6f)
    BodyRegion.LOWER -> ZoomTarget(0.5f, 0.82f, 1.6f)
    BodyRegion.FULL -> ZoomTarget(0.5f, 0.5f, 1.2f)
}

/** A measured number the way the slides say it: 19°, 0.45 torsos, 76 %. */
internal fun fmtValue(v: Double, unit: String): String {
    val n = when {
        // A whole number never carries ".0" — «19», not «19.0».
        kotlin.math.abs(v - v.roundToLong()) < 0.005 -> v.roundToLong().toString()
        else -> String.format(Locale.US, "%.2f", v).trimEnd('0').trimEnd('.')
    }
    return n + unitSuffix(unit)
}

/** The measured unit, compact: `deg` → °, `% of reach` → %, `torso` → torsos. */
internal fun unitSuffix(unit: String): String = when (unit.trim().lowercase()) {
    "", "none" -> ""
    "deg", "degree", "degrees" -> "°"
    "%", "percent", "pct", "% of reach" -> "%"
    "torso", "torsos" -> " torsos"
    else -> " " + unit.trim()
}

/**
 * The standard the athlete is aiming at, in the design's words
 * («OBJETIVO MENOS DE 8°»). The comparison says which way: a rule that fires
 * below its threshold (a lockout at 76 % of a 85 % minimum) wants the value
 * UP; one that fires above it (a swing of 19° against an 8° limit) wants it
 * DOWN. No threshold lives here — it is the server's own number.
 */
internal fun goalText(threshold: Double, comparison: String, unit: String): String =
    if (comparison.startsWith("<")) "OBJETIVO MÁS DE ${fmtValue(threshold, unit)}"
    else "OBJETIVO MENOS DE ${fmtValue(threshold, unit)}"

private val SHORT_STOPWORDS = setOf(
    "sin", "de", "del", "la", "el", "los", "las", "en", "y", "a", "con", "por",
    "para", "al", "un", "una", "o", "u", "muy", "demasiado",
)

/** «Sin bloqueo arriba» → «BLOQUEO»: the one word a header can hold. */
internal fun shortFault(titleEs: String): String =
    titleEs.split(Regex("\\s+"))
        .firstOrNull { it.isNotBlank() && it.lowercase() !in SHORT_STOPWORDS }
        ?.uppercase() ?: titleEs.uppercase()

/**
 * Why the fault fired, from what was actually measured — the app holds no
 * per-fault prose, so the sentence says the number and the limit and stops
 * there. Never invents a cause.
 */
internal fun faultWhy(
    name: String,
    value: Double?,
    threshold: Double,
    comparison: String,
    unit: String,
    rep: Int,
): String {
    val title = faultEs(name)
    val v = value ?: return "$title, medido en la rep $rep."
    return if (comparison.startsWith("<"))
        "$title: ${fmtValue(v, unit)} frente al mínimo de ${fmtValue(threshold, unit)}."
    else
        "$title: ${fmtValue(v, unit)} frente al máximo de ${fmtValue(threshold, unit)}."
}

/** Where a rep's key moment is: its turnaround, or where the rep starts. */
internal fun repMoment(rep: RepRow): Double =
    rep.turnS.takeIf { it > 0.0 } ?: rep.startS

/**
 * Where to open the clip for a measured fault: the middle of the phase
 * window the server sent, or the rep's turnaround when it shipped none.
 */
internal fun faultMoment(rep: RepRow, f: MeasuredFault): Double {
    val iv = f.intervalS
    if (iv.size >= 2 && iv[0].isFinite() && iv[1].isFinite() && iv[1] >= iv[0] && iv[1] > 0.0) {
        return (iv[0] + iv[1]) / 2.0
    }
    return repMoment(rep)
}

/** A cue for a fault the Spanish table does not know yet, so the line is never blank. */
internal const val FALLBACK_CUE = "Lleva la corrección a la próxima serie."

/**
 * The fault stories of a set, worst first, at most [MAX_SLIDES].
 *
 * Every fired fault of every rep is a candidate; faults that fired more than
 * once collapse into their worst rep (the one the athlete should look at),
 * ranked by how far past the threshold they went — the same normalised
 * exceedance the server ranks [Analysis.topFixes] by.
 */
fun faultSlides(a: Analysis): List<FaultSlide> {
    data class Fired(val repIndex: Int, val fault: MeasuredFault, val excess: Double)
    val candidates = a.reps.flatMapIndexed { i, rep ->
        rep.faults.filter { it.name.isNotBlank() }.map { Fired(i, it, ReplayPlan.exceedance(it)) }
    }
    return candidates
        .groupBy { it.fault.errorId.ifBlank { it.fault.name } }
        .map { (_, same) -> same.maxBy { it.excess } }
        .sortedByDescending { it.excess }
        .take(MAX_SLIDES)
        .map { c ->
            val f = c.fault
            val title = faultEs(f.name)
            FaultSlide(
                rep = c.repIndex + 1,
                atS = faultMoment(a.reps[c.repIndex], f),
                title = title.uppercase(),
                short = shortFault(title),
                value = f.value?.let { fmtValue(it, f.unit) } ?: "—",
                goal = goalText(f.threshold, f.comparison, f.unit),
                why = faultWhy(f.name, f.value, f.threshold, f.comparison, f.unit, c.repIndex + 1),
                cue = cueEs(f.name) ?: FALLBACK_CUE,
                region = regionFor(f.errorId.ifBlank { f.name }),
            )
        }
}

/** «0:14»: a video second as the design writes it. */
internal fun clockLabel(s: Double): String {
    val t = s.coerceAtLeast(0.0).toInt()
    return "%d:%02d".format(t / 60, t % 60)
}

/**
 * The clip's frame at [atS], decoded off the main thread and released.
 *
 * While a frame is being decoded the previous one stays on screen, so the
 * story never flashes an empty box between slides; a frame the phone cannot
 * read (or a null clip) returns null and the screen falls back to a dark box
 * with the rep and the time.
 */
@Composable
internal fun keyFrame(clip: File?, atS: Double): ImageBitmap? {
    // (loaded second, frame): the second tag tells a stale frame from a
    // genuine "could not read this one".
    var loaded by remember(clip) { mutableStateOf<Pair<Double, ImageBitmap?>?>(null) }
    LaunchedEffect(clip, atS) {
        if (clip == null) {
            loaded = null
            return@LaunchedEffect
        }
        val bmp = withContext(Dispatchers.IO) {
            runCatching {
                val r = android.media.MediaMetadataRetriever()
                try {
                    r.setDataSource(clip.absolutePath)
                    val us = (atS * 1_000_000).toLong().coerceAtLeast(0L)
                    r.getFrameAtTime(us, android.media.MediaMetadataRetriever.OPTION_CLOSEST)
                        ?.asImageBitmap()
                } finally {
                    runCatching { r.release() }
                }
            }.getOrNull()
        }
        loaded = atS to bmp
    }
    val state = loaded ?: return null
    return state.second
}

// ---------------------------------------------------------------------------
// The screen
// ---------------------------------------------------------------------------

/**
 * The fault viewer, full screen on [Tk.ink]. [startIndex] opens the story on
 * one fault; [exercise] names the movement in the header («· DOMINADA») when
 * the caller has it. [onClose] leaves the viewer; [onPlayRep] hands the
 * current slide to the series replay at half speed.
 */
@Composable
fun FaultViewer(
    faults: List<FaultSlide>,
    startIndex: Int,
    clip: File?,
    onClose: () -> Unit,
    onPlayRep: (FaultSlide) -> Unit = {},
    exercise: String = "",
) {
    val count = faults.size
    if (count == 0) {
        EmptyFaults(onClose)
        return
    }
    var index by remember(faults) { mutableStateOf(startIndex.coerceIn(0, count - 1)) }
    var playing by remember(faults) { mutableStateOf(true) }
    var zoomed by remember(faults) { mutableStateOf(false) }
    val slide = faults[index.coerceIn(0, count - 1)]

    // The zoom lands 600 ms after each slide arrives, on the failing region.
    LaunchedEffect(faults, index) {
        zoomed = false
        delay(ZOOM_DELAY_MS)
        zoomed = true
    }
    // The story advances on its own: 4 s per slide while playing. Pausing
    // holds the fraction; coming back resumes it — a new slide restarts it.
    val progress = remember(faults) { Animatable(0f) }
    var timerSlide by remember(faults) { mutableIntStateOf(-1) }
    LaunchedEffect(playing, faults, index) {
        if (count < 2) return@LaunchedEffect
        if (timerSlide != index) {
            progress.snapTo(0f)
            timerSlide = index
        }
        if (!playing) return@LaunchedEffect
        val remainMs = (SLIDE_MS * (1f - progress.value)).toLong().coerceIn(1L, SLIDE_MS)
        progress.animateTo(1f, tween(remainMs.toInt(), easing = LinearEasing))
        index = nextSlide(index, count)
    }

    Column(
        Modifier
            .fillMaxSize()
            .background(Tk.ink)
            .windowInsetsPadding(WindowInsets.systemBars),
    ) {
        // One progress bar per fault; the current one fills as time runs.
        Row(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 14.dp)
                .padding(top = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            repeat(count) { i ->
                Box(
                    Modifier
                        .weight(1f)
                        .height(4.dp)
                        .clip(RoundedCornerShape(2.dp))
                        .background(Tk.onInk.copy(alpha = 0.25f)),
                ) {
                    val fraction = when {
                        i < index -> 1f
                        i == index -> if (count < 2) 1f else progress.value
                        else -> 0f
                    }
                    Box(
                        Modifier
                            .fillMaxWidth(fraction)
                            .fillMaxHeight()
                            .background(Tk.onInk),
                    )
                }
            }
        }

        // Tapping the top pauses and resumes the story (the buttons win when
        // they are the ones touched).
        Row(
            Modifier
                .fillMaxWidth()
                .clickable { playing = !playing }
                .padding(horizontal = 14.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Column(Modifier.weight(1f)) {
                Text(
                    headerLabel(count, index, exercise),
                    style = mono(11, 0.05f, Tk.faint),
                )
                Text(
                    slide.title,
                    style = display(18, color = Tk.onInk, line = 1.05f),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.padding(top = 2.dp),
                )
            }
            ViewerIconButton("✕", "Cerrar el visor de fallos", onClick = onClose)
            ViewerIconButton(
                if (playing) "II" else "▶",
                if (playing) "Pausar el visor de fallos" else "Reanudar el visor de fallos",
            ) { playing = !playing }
        }

        // The frame, zooming into the failing region 600 ms in.
        val target = zoomTarget(slide.region)
        val scale by animateFloatAsState(
            if (zoomed) target.scale else 1f,
            tween(800, easing = TizaEasing),
            label = "zoom",
        )
        Box(
            Modifier
                .padding(horizontal = 8.dp)
                .fillMaxWidth()
                .weight(1f)
                .clip(CardShape)
                .background(Tk.dark),
        ) {
            Box(
                Modifier
                    .fillMaxSize()
                    .graphicsLayer {
                        scaleX = scale
                        scaleY = scale
                        transformOrigin = TransformOrigin(target.x, target.y)
                    },
            ) {
                val frame = keyFrame(clip, slide.atS)
                if (frame != null) {
                    Image(
                        frame,
                        contentDescription = "Fotograma de la rep ${slide.rep} en ${clockLabel(slide.atS)}",
                        contentScale = ContentScale.Crop,
                        modifier = Modifier.fillMaxSize(),
                    )
                } else {
                    FrameFallback(slide.rep, slide.atS)
                }
            }
            // The story is stepped through by touching the sides.
            Row(Modifier.fillMaxSize()) {
                Box(
                    Modifier
                        .weight(0.3f)
                        .fillMaxHeight()
                        .noRipple { index = prevSlide(index, count) }
                        .semantics { role = Role.Button; contentDescription = "Fallo anterior" },
                )
                Box(Modifier.weight(0.4f).fillMaxHeight())
                Box(
                    Modifier
                        .weight(0.3f)
                        .fillMaxHeight()
                        .noRipple { index = nextSlide(index, count) }
                        .semantics { role = Role.Button; contentDescription = "Fallo siguiente" },
                )
            }
            Text(
                "REP ${slide.rep} · ${clockLabel(slide.atS)}",
                style = mono(11, 0f, Tk.onInk, FontWeight.SemiBold),
                modifier = Modifier
                    .align(Alignment.TopStart)
                    .padding(10.dp)
                    .clip(RoundedCornerShape(6.dp))
                    .background(Tk.ink.copy(alpha = 0.75f))
                    .padding(horizontal = 8.dp, vertical = 5.dp),
            )
            Text(
                String.format(Locale.US, "ZOOM %.1f×", target.scale),
                style = mono(11, 0f, Tk.onInk),
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .padding(10.dp)
                    .clip(RoundedCornerShape(6.dp))
                    .background(Tk.ink.copy(alpha = 0.75f))
                    .padding(horizontal = 8.dp, vertical = 5.dp)
                    .graphicsLayer { alpha = if (zoomed) 1f else 0f },
            )
            // The measurement lands after the zoom, over the frame.
            val shown by animateFloatAsState(if (zoomed) 1f else 0f, tween(400, delayMillis = 200), label = "valueCard")
            Column(
                Modifier
                    .align(Alignment.BottomStart)
                    .padding(10.dp)
                    .graphicsLayer {
                        alpha = shown
                        translationY = (1f - shown) * 10.dp.toPx()
                    }
                    .clip(InnerShape)
                    .background(Tk.primary)
                    .border(2.dp, Tk.ink, InnerShape)
                    .padding(horizontal = 12.dp, vertical = 10.dp),
            ) {
                Text(slide.value, style = display(26, color = Tk.ink))
                Text(
                    slide.goal,
                    style = mono(10, 0f, Tk.ink, FontWeight.SemiBold),
                    modifier = Modifier.padding(top = 2.dp),
                )
            }
        }

        // Why it fired, and what to do in the next set.
        Column(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp)
                .padding(top = 14.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Text(slide.why, style = body(15, Tk.onInk, 1.45f))
            Row(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.Top,
            ) {
                Text(
                    "PRÓXIMA SERIE",
                    style = mono(11, 0.05f, Tk.teal, FontWeight.SemiBold),
                )
                Text(
                    slide.cue,
                    style = body(14, Tk.onInk.copy(alpha = 0.85f), 1.4f),
                    modifier = Modifier.weight(1f),
                )
            }
        }

        Row(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp)
                .padding(top = 10.dp, bottom = 22.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            ViewerIconButton("←", "Fallo anterior", size = 52.dp) {
                index = prevSlide(index, count)
            }
            Box(
                Modifier
                    .weight(1f)
                    .heightIn(min = 52.dp)
                    .clip(InnerShape)
                    .background(Tk.onInk)
                    .clickable { onPlayRep(slide) }
                    .padding(horizontal = 8.dp, vertical = 15.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    "VER LA REP A 0.5×",
                    style = display(14, tracking = 0.03f, color = Tk.ink),
                )
            }
            Box(
                Modifier
                    .size(52.dp)
                    .clip(InnerShape)
                    .background(Tk.primary)
                    .clickable { index = nextSlide(index, count) }
                    .semantics { role = Role.Button; contentDescription = "Fallo siguiente" },
                contentAlignment = Alignment.Center,
            ) {
                Text("→", style = display(16, color = Tk.ink))
            }
        }
    }
}

/** «FALLO 1 DE 3 · DOMINADA» — the movement joins when the caller has it. */
internal fun headerLabel(count: Int, index: Int, exercise: String): String {
    val base = "FALLO ${index + 1} DE $count"
    if (exercise.isBlank()) return base
    return "$base · ${movementEs(exercise).uppercase()}"
}

/** Nothing to tell: the set measured clean, and the viewer says so instead of opening empty. */
@Composable
private fun EmptyFaults(onClose: () -> Unit) {
    Column(
        Modifier
            .fillMaxSize()
            .background(Tk.ink)
            .windowInsetsPadding(WindowInsets.systemBars)
            .padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            "NADA QUE CORREGIR",
            style = display(20, color = Tk.onInk),
        )
        Text(
            "La serie salió limpia en lo medido: no hay fallos que ver.",
            style = body(14, Tk.onInk.copy(alpha = 0.85f), 1.45f),
            modifier = Modifier.padding(top = 8.dp),
        )
        Box(
            Modifier
                .padding(top = 20.dp)
                .clip(InnerShape)
                .background(Tk.onInk)
                .clickable(onClick = onClose)
                .padding(horizontal = 24.dp, vertical = 14.dp),
        ) {
            Text("CERRAR", style = display(14, color = Tk.ink))
        }
    }
}

/** The frame the phone could not read: the rep and the time, never a crash. */
@Composable
private fun FrameFallback(rep: Int, atS: Double) {
    Column(
        Modifier.fillMaxSize(),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("REP $rep", style = display(22, color = Tk.onInk))
        Text(
            clockLabel(atS),
            style = mono(11, 0.05f, Tk.faint),
            modifier = Modifier.padding(top = 4.dp),
        )
    }
}

/** The viewer's square controls: 48dp of touch, paper border on ink. */
@Composable
private fun ViewerIconButton(
    glyph: String,
    description: String,
    modifier: Modifier = Modifier,
    size: Dp = 48.dp,
    onClick: () -> Unit,
) {
    Box(
        modifier
            .size(size)
            .clip(InnerShape)
            .background(Tk.ink)
            .border(2.dp, Tk.onInk, InnerShape)
            .clickable(onClick = onClick)
            .semantics { role = Role.Button; contentDescription = description },
        contentAlignment = Alignment.Center,
    ) {
        Text(glyph, style = mono(13, 0f, Tk.onInk, FontWeight.SemiBold))
    }
}
