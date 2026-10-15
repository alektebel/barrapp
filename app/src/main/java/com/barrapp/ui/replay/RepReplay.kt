package com.barrapp.ui.replay

import android.net.Uri
import android.provider.Settings
import androidx.annotation.OptIn
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableDoubleStateOf
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.VideoSize
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.AspectRatioFrameLayout
import androidx.media3.ui.PlayerView
import com.barrapp.data.Analysis
import com.barrapp.ui.theme.T
import com.barrapp.ui.theme.Tk
import com.barrapp.ui.theme.bandInk
import com.barrapp.ui.theme.body
import com.barrapp.ui.theme.display
import com.barrapp.ui.theme.mono
import java.io.File
import kotlin.math.abs

/**
 * Lets something outside the replay - "Ver en la rep 4" on a fix - move it.
 * The request carries a serial so asking for the same rep twice still moves.
 */
@Stable
class RepReplayState {
    internal var request by mutableStateOf<Pair<Int, Long>?>(null)
        private set
    private var serial = 0L

    fun showRep(index: Int) {
        request = index to ++serial
    }
}

@Composable
fun rememberRepReplayState(): RepReplayState = remember { RepReplayState() }

/**
 * The set, played back with its measurement on top of it.
 *
 * The counter over the video rises when each rep ends, the rep's verdict
 * appears as it finishes, and the strip underneath is the set drawn to scale:
 * one segment per rep in its band's colour, the turnaround as a dot, a ring
 * over a rep that broke the set's own pattern. With "Sólo reps" on, the rests
 * between reps are skipped - the cut the measurement made, applied while
 * playing, with the file on the phone untouched.
 *
 * Inline it plays once, muted, and stops on the last rep. Full screen adds the
 * guided review, which pauses at each faulted turnaround. With system
 * animations off, nothing starts by itself.
 */
@OptIn(UnstableApi::class)
@Composable
fun RepReplay(
    analysis: Analysis,
    clip: File,
    modifier: Modifier = Modifier,
    state: RepReplayState = rememberRepReplayState(),
    fullScreen: Boolean = false,
    onExpand: (() -> Unit)? = null,
) {
    val context = LocalContext.current
    val haptics = LocalHapticFeedback.current
    val reduceMotion = remember {
        runCatching {
            Settings.Global.getFloat(context.contentResolver,
                Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f
        }.getOrDefault(false)
    }

    var clipDurationS by remember(clip) { mutableDoubleStateOf(analysis.durationS) }
    val plan = remember(analysis, clipDurationS) { ReplayPlan.from(analysis, clipDurationS) }
    var aspect by remember(clip) { mutableFloatStateOf(9f / 16f) }
    var positionS by remember(clip) { mutableDoubleStateOf(plan.windowStart) }
    var playing by remember(clip) { mutableStateOf(false) }
    var ended by remember(clip) { mutableStateOf(false) }
    var failed by remember(clip) { mutableStateOf(false) }
    var compact by remember(plan) { mutableStateOf(plan.compactByDefault) }
    var guided by remember { mutableStateOf(fullScreen) }
    var reviewed by remember(clip) { mutableStateOf(emptySet<Int>()) }
    var lastDone by remember(clip) { mutableIntStateOf(0) }

    val player = remember(clip) {
        ExoPlayer.Builder(context).build().apply {
            setMediaItem(MediaItem.fromUri(Uri.fromFile(clip)))
            volume = if (fullScreen) 1f else 0f
            repeatMode = Player.REPEAT_MODE_OFF
            prepare()
            seekTo((plan.windowStart * 1000).toLong())
            playWhenReady = !reduceMotion
        }
    }
    DisposableEffect(player) {
        val listener = object : Player.Listener {
            override fun onVideoSizeChanged(videoSize: VideoSize) {
                if (videoSize.width > 0 && videoSize.height > 0) {
                    aspect = videoSize.width * videoSize.pixelWidthHeightRatio / videoSize.height
                }
            }
            override fun onPlaybackStateChanged(state: Int) {
                if (state == Player.STATE_READY && player.duration > 0) {
                    clipDurationS = player.duration / 1000.0
                }
            }
            override fun onIsPlayingChanged(isPlaying: Boolean) { playing = isPlaying }
            override fun onPlayerError(error: PlaybackException) { failed = true }
        }
        player.addListener(listener)
        onDispose {
            player.removeListener(listener)
            player.release()
        }
    }
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner, player) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_PAUSE) player.pause()
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    fun seek(t: Double) {
        val c = plan.clamp(t)
        player.seekTo((c * 1000).toLong())
        positionS = c
        ended = false
        reviewed = plan.reviewedBy(c - 0.01)
        lastDone = plan.repsDoneBy(c)
    }

    fun restart() {
        seek(plan.windowStart)
        reviewed = emptySet()
        player.play()
    }

    fun togglePlay() {
        when {
            player.isPlaying -> player.pause()
            ended || positionS >= plan.windowEnd - 0.05 -> restart()
            else -> player.play()
        }
    }

    // External "show me rep N": land on its turnaround and hold there.
    LaunchedEffect(state.request) {
        val (index, _) = state.request ?: return@LaunchedEffect
        val rep = plan.reps.firstOrNull { it.index == index } ?: return@LaunchedEffect
        player.pause()
        seek(rep.moment)
        reviewed = reviewed + rep.index
    }

    // One read of the position per frame: the counter and the verdict move
    // with the picture, not up to 80 ms behind it.
    LaunchedEffect(player, plan, compact, guided) {
        while (true) {
            withFrameNanos { }
            val t = player.currentPosition / 1000.0
            positionS = t
            if (!player.isPlaying) continue
            if (t >= plan.windowEnd) {
                player.pause()
                seek(plan.windowEnd)
                ended = true
                continue
            }
            if (compact) {
                val jump = plan.compactJump(t)
                if (jump != null) {
                    if (jump.isNaN()) {
                        player.pause()
                        ended = true
                    } else {
                        player.seekTo((jump * 1000).toLong())
                    }
                    continue
                }
            }
            val stop = if (guided) plan.guidedStop(t, reviewed) else null
            if (stop != null) {
                player.pause()
                player.seekTo((stop.moment * 1000).toLong())
                reviewed = reviewed + stop.index
                continue
            }
            val done = plan.repsDoneBy(t)
            if (done > lastDone) {
                haptics.performHapticFeedback(HapticFeedbackType.TextHandleMove)
            }
            lastDone = done
        }
    }

    val done = plan.repsDoneBy(positionS)
    val verdict = plan.verdictAt(positionS)
        ?: if (!playing) plan.activeRepAt(positionS)?.takeIf { it.index in reviewed } else null

    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        BoxWithConstraints(
            Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(16.dp))
                .background(Color.Black),
            contentAlignment = Alignment.Center,
        ) {
            val maxH = if (fullScreen) maxWidth * 1.5f else maxWidth * 1.1f
            val h = (maxWidth / aspect.coerceIn(0.4f, 2.4f)).coerceAtMost(maxH)
            Box(
                Modifier
                    .fillMaxWidth()
                    .height(h)
                    .pointerInput(player) { detectTapGestures { togglePlay() } }
                    .semantics {
                        role = Role.Button
                        contentDescription = if (playing) "Pausar el vídeo" else "Reproducir el vídeo"
                    },
            ) {
                AndroidView(
                    factory = { ctx ->
                        PlayerView(ctx).apply {
                            useController = false
                            resizeMode = AspectRatioFrameLayout.RESIZE_MODE_FIT
                            setShutterBackgroundColor(android.graphics.Color.BLACK)
                            this.player = player
                        }
                    },
                    modifier = Modifier.fillMaxSize(),
                )
                // A scrim under the counter: text never sits on a bare frame.
                Box(
                    Modifier
                        .fillMaxWidth()
                        .height(96.dp)
                        .background(Brush.verticalGradient(listOf(Color.Black.copy(alpha = 0.65f), Color.Transparent))),
                )
                Box(
                    Modifier
                        .align(Alignment.BottomCenter)
                        .fillMaxWidth()
                        .height(88.dp)
                        .background(Brush.verticalGradient(listOf(Color.Transparent, Color.Black.copy(alpha = 0.6f)))),
                )
                RepCounter(done, plan.total, Modifier.align(Alignment.TopStart).padding(14.dp))
                if (onExpand != null) {
                    ExpandButton(onExpand, Modifier.align(Alignment.TopEnd).padding(6.dp))
                }
                if (!playing && !failed) {
                    PlayGlyph(ended, Modifier.align(Alignment.Center))
                }
                Box(
                    Modifier
                        .align(Alignment.BottomCenter)
                        .padding(bottom = 14.dp, start = 14.dp, end = 14.dp)
                        .semantics { liveRegion = LiveRegionMode.Polite },
                ) {
                    // The last verdict stays drawn while it fades, so the
                    // pill does not empty itself on the way out.
                    var shown by remember { mutableStateOf<ReplayRep?>(null) }
                    if (verdict != null) shown = verdict
                    val alpha by androidx.compose.animation.core.animateFloatAsState(
                        if (verdict != null) 1f else 0f, label = "verdict",
                    )
                    shown?.takeIf { alpha > 0.01f }?.let {
                        Box(Modifier.alpha(alpha)) { VerdictPill(it) }
                    }
                }
                if (failed) {
                    Text(
                        "Este vídeo no se puede reproducir en este teléfono.",
                        style = body(13, Color.White),
                        modifier = Modifier.align(Alignment.Center).padding(24.dp),
                    )
                }
            }
        }

        RepStrip(plan, positionS, onSeek = { seek(it) })

        Row(
            Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                "${clock(positionS - plan.windowStart)} / ${clock(plan.windowEnd - plan.windowStart)}",
                style = mono(11, 0f, Tk.muted),
            )
            Spacer(Modifier.weight(1f))
            ToggleRow("Sólo reps", compact, { compact = it },
                "Saltar los descansos entre repeticiones")
            if (fullScreen) {
                ToggleRow("Guiada", guided, { guided = it; reviewed = plan.reviewedBy(positionS - 0.01) },
                    "Pausar en cada repetición con un fallo")
            }
        }
        consistencyLine(analysis)?.let {
            Text(it, style = mono(10, 0.02f, if (analysis.consistencyBand == "irregular") Tk.amber else Tk.muted))
        }
    }
}

@Composable
private fun RepCounter(done: Int, total: Int, modifier: Modifier) {
    Row(
        modifier.semantics(mergeDescendants = true) {
            contentDescription = "$done de $total repeticiones"
        },
        verticalAlignment = Alignment.Bottom,
    ) {
        Text("$done", style = display(44, FontWeight.Black, 1f).copy(color = Color.White))
        Text(
            " / $total",
            style = mono(13, 0f, Color.White.copy(alpha = 0.75f)),
            modifier = Modifier.padding(bottom = 6.dp),
        )
    }
}

@Composable
private fun VerdictPill(rep: ReplayRep) {
    val (label, ink) = when {
        !rep.measured -> "sin medir" to Tk.muted
        rep.fault != null -> rep.fault to Tk.amber
        else -> "limpia" to Tk.teal
    }
    Row(
        Modifier
            .clip(RoundedCornerShape(12.dp))
            .background(Color.Black.copy(alpha = 0.72f))
            .border(1.dp, ink.copy(alpha = 0.6f), RoundedCornerShape(12.dp))
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Box(Modifier.size(8.dp).clip(CircleShape).background(ink))
        Text("Rep ${rep.number}", style = mono(12, 0.04f, Color.White))
        Text(label, style = body(14, Color.White, weight = FontWeight.SemiBold))
        if (rep.outlier) {
            Text("· distinta al resto", style = body(12, Color.White.copy(alpha = 0.75f)))
        }
    }
}

/**
 * The set to scale: the window is the strip, each rep a segment in its band's
 * colour, the playhead a white line. Tapping anywhere lands on the nearest
 * rep's turnaround; screen readers get one action per rep instead.
 */
@Composable
private fun RepStrip(plan: ReplayPlan, positionS: Double, onSeek: (Double) -> Unit) {
    val span = (plan.windowEnd - plan.windowStart).coerceAtLeast(0.01)
    fun x(t: Double, w: Float) = ((t - plan.windowStart) / span).toFloat().coerceIn(0f, 1f) * w
    Canvas(
        Modifier
            .fillMaxWidth()
            .height(48.dp)
            .pointerInput(plan) {
                detectTapGestures { offset ->
                    val t = plan.windowStart + offset.x / size.width * span
                    val nearest = plan.reps.minByOrNull { abs(it.moment - t) }
                    onSeek(nearest?.takeIf { t in it.startS - 0.5..it.endS + 0.5 }?.moment ?: t)
                }
            }
            .semantics {
                contentDescription = "Línea de tiempo de la serie, ${plan.total} repeticiones"
                stateDescription = "Rep ${plan.activeRepAt(positionS)?.number ?: plan.repsDoneBy(positionS)}"
                customActions = plan.reps.map { rep ->
                    CustomAccessibilityAction(
                        "Ir a la rep ${rep.number}" + (rep.fault?.let { ", $it" } ?: ""),
                    ) { onSeek(rep.moment); true }
                }
            },
    ) {
        val mid = size.height / 2
        val barH = 14.dp.toPx()
        drawRoundRect(
            Tk.border, topLeft = Offset(0f, mid - 2.dp.toPx()),
            size = Size(size.width, 4.dp.toPx()), cornerRadius = CornerRadius(2.dp.toPx()),
        )
        plan.reps.forEach { rep ->
            val a = x(rep.startS, size.width)
            val b = x(rep.endS, size.width)
            val ink = if (!rep.measured) Tk.muted else bandInk(rep.band)
            val past = rep.endS <= positionS
            drawRoundRect(
                ink.copy(alpha = if (past) 1f else 0.45f),
                topLeft = Offset(a + 1.dp.toPx(), mid - barH / 2),
                size = Size((b - a - 2.dp.toPx()).coerceAtLeast(2.dp.toPx()), barH),
                cornerRadius = CornerRadius(4.dp.toPx()),
            )
            if (rep.fault != null) {
                drawCircle(Tk.amber, radius = 3.dp.toPx(), center = Offset(x(rep.moment, size.width), mid))
            }
            if (rep.outlier) {
                drawCircle(
                    Color.White.copy(alpha = 0.85f), radius = 4.dp.toPx(),
                    center = Offset((a + b) / 2, mid - barH / 2 - 7.dp.toPx()),
                    style = Stroke(1.5.dp.toPx()),
                )
            }
        }
        val px = x(positionS, size.width)
        drawLine(Color.White, Offset(px, 4.dp.toPx()), Offset(px, size.height - 4.dp.toPx()),
            strokeWidth = 2.dp.toPx(), cap = StrokeCap.Round)
    }
}

@Composable
private fun ToggleRow(label: String, checked: Boolean, onChange: (Boolean) -> Unit, description: String) {
    Row(
        Modifier.semantics(mergeDescendants = true) {
            contentDescription = description
        },
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(label, style = T.bodyInk)
        Switch(
            checked = checked,
            onCheckedChange = onChange,
            colors = SwitchDefaults.colors(
                checkedTrackColor = Tk.primary,
                checkedThumbColor = Color.White,
                uncheckedTrackColor = Tk.card,
                uncheckedThumbColor = Tk.muted,
                uncheckedBorderColor = Tk.border,
            ),
        )
    }
}

/** Play, or replay once the set has ended - drawn, not a glyph. */
@Composable
private fun PlayGlyph(ended: Boolean, modifier: Modifier) {
    Box(
        modifier.size(64.dp).clip(CircleShape).background(Color.Black.copy(alpha = 0.55f))
            .border(1.5.dp, Color.White.copy(alpha = 0.7f), CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        Canvas(Modifier.size(24.dp)) {
            if (ended) {
                drawArc(Color.White, -60f, 300f, false,
                    style = Stroke(2.5.dp.toPx(), cap = StrokeCap.Round))
                val tip = Offset(size.width * 0.75f, size.height * 0.07f)
                drawPath(Path().apply {
                    moveTo(tip.x - 6.dp.toPx(), tip.y - 3.dp.toPx())
                    lineTo(tip.x + 2.dp.toPx(), tip.y + 2.dp.toPx())
                    lineTo(tip.x - 5.dp.toPx(), tip.y + 7.dp.toPx())
                    close()
                }, Color.White)
            } else {
                drawPath(Path().apply {
                    moveTo(size.width * 0.28f, size.height * 0.15f)
                    lineTo(size.width * 0.88f, size.height * 0.5f)
                    lineTo(size.width * 0.28f, size.height * 0.85f)
                    close()
                }, Color.White)
            }
        }
    }
}

@Composable
private fun ExpandButton(onClick: () -> Unit, modifier: Modifier) {
    Box(
        modifier
            .sizeIn(minWidth = 48.dp, minHeight = 48.dp)
            .pointerInput(onClick) { detectTapGestures { onClick() } }
            .semantics {
                role = Role.Button
                contentDescription = "Ver a pantalla completa"
            },
        contentAlignment = Alignment.Center,
    ) {
        Canvas(Modifier.size(18.dp)) {
            val s = 2.dp.toPx()
            val l = size.width * 0.38f
            val w = size.width
            listOf(
                Offset(0f, 0f) to Pair(Offset(l, 0f), Offset(0f, l)),
                Offset(w, 0f) to Pair(Offset(w - l, 0f), Offset(w, l)),
                Offset(0f, w) to Pair(Offset(l, w), Offset(0f, w - l)),
                Offset(w, w) to Pair(Offset(w - l, w), Offset(w, w - l)),
            ).forEach { (corner, ends) ->
                drawLine(Color.White, corner, ends.first, s, StrokeCap.Round)
                drawLine(Color.White, corner, ends.second, s, StrokeCap.Round)
            }
        }
    }
}

private fun clock(s: Double): String {
    val total = s.coerceAtLeast(0.0).toInt()
    return "%d:%02d".format(total / 60, total % 60)
}
