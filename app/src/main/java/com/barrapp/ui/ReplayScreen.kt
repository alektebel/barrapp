package com.barrapp.ui

import android.widget.VideoView
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import com.barrapp.data.Analysis
import com.barrapp.data.RepRow
import com.barrapp.improvementCues
import com.barrapp.repFault
import com.barrapp.ui.parts.Eyebrow
import com.barrapp.ui.parts.Pill
import com.barrapp.ui.parts.bandColor
import kotlinx.coroutines.delay

/**
 * The clip, again, with the measurement over it.
 *
 * The phone kept its copy of the clip when it was uploaded; the server's copy
 * expires. This screen plays that copy and lays the measured reps on top of
 * it: each rep is a span on the timeline, the turning point - where the pull
 * became the lowering - is the dot in the middle of it, and every rep is a
 * comment that says what the numbers found. Tapping a comment or the timeline
 * moves the video to that moment, so feedback lands on the movement it
 * describes rather than beside it.
 *
 * The comments are the measured facts, restated at the time they happened.
 * Nothing here invents a judgement the server did not make.
 */
@Composable
fun ReplayScreen(
    analysis: Analysis?,
    clip: java.io.File?,
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TextButton(onClick = onBack) { Text("Back") }
            Spacer(Modifier.size(6.dp))
            Column(Modifier.weight(1f)) {
                Text("Replay", style = MaterialTheme.typography.titleMedium)
                Text(
                    analysis?.detected?.label?.replace('_', ' ')
                        ?: analysis?.exercise?.replace('_', ' ')
                        ?: "your clip",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outline.copy(alpha = 0.5f))

        when {
            clip == null -> Missing("This phone no longer has a copy of the clip.", onBack)
            analysis == null || analysis.reps.none { it.endS > 0 } ->
                Missing("This session has no measured reps to mark.", onBack)

            else -> ReplayBody(analysis, clip)
        }
    }
}

@Composable
private fun Missing(message: String, onBack: () -> Unit) {
    Column(
        Modifier.fillMaxSize().padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text(message, style = MaterialTheme.typography.bodyLarge)
        Spacer(Modifier.height(14.dp))
        TextButton(onClick = onBack) { Text("Back to the session") }
    }
}

@Composable
private fun ReplayBody(analysis: Analysis, clip: java.io.File) {
    val context = LocalContext.current
    val reps = analysis.reps.filter { it.endS > 0 }

    var durationS by remember { mutableFloatStateOf(0f) }
    var positionS by remember { mutableFloatStateOf(0f) }
    var playing by remember { mutableStateOf(false) }
    var activeRep by remember { mutableIntStateOf(-1) }

    val videoView = remember {
        VideoView(context).apply {
            setVideoPath(clip.absolutePath)
            setOnPreparedListener { mp ->
                durationS = mp.duration / 1000f
                start()
            }
        }
    }
    DisposableEffect(Unit) { onDispose { videoView.stopPlayback() } }

    // Playback position is polled rather than observed: VideoView offers no
    // callback per frame, and 200ms is finer than the eye follows here.
    LaunchedEffect(videoView) {
        while (true) {
            positionS = videoView.currentPosition / 1000f
            playing = videoView.isPlaying
            activeRep = reps.indexOfFirst { positionS >= it.startS && positionS <= it.endS }
            delay(200)
        }
    }

    fun seek(t: Double) {
        videoView.seekTo((t * 1000).toInt())
        if (!videoView.isPlaying) videoView.start()
    }

    Column(Modifier.fillMaxSize()) {
        // The video, with the fault said over it while the faulting rep is on
        // screen - "Momentum" while the swing happens, "Not locking out" as
        // the top is shorted. Clean reps say nothing.
        Box {
            AndroidView(
                factory = { videoView },
                modifier = Modifier.fillMaxWidth().height(240.dp),
            )
            val fault = reps.getOrNull(activeRep)?.let { repFault(it) }
            if (fault != null) {
                Text(
                    fault.uppercase(),
                    style = MaterialTheme.typography.labelLarge,
                    color = Color.White,
                    modifier = Modifier
                        .align(Alignment.TopCenter)
                        .padding(top = 12.dp)
                        .clip(RoundedCornerShape(50))
                        .background(Color.Black.copy(alpha = 0.65f))
                        .padding(horizontal = 14.dp, vertical = 6.dp),
                )
            }
        }

        Timeline(
            reps = reps,
            durationS = if (durationS > 0) durationS
                else analysis.durationS.toFloat().takeIf { it > 0 } ?: 1f,
            positionS = positionS,
            activeRep = activeRep,
            onSeek = { t -> seek(t.toDouble()) },
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
        )

        // What to take into the next set: at most three, because that is what
        // carries. The per-rep comments below are for when one is wanted.
        improvementCues(analysis).forEachIndexed { i, cue ->
            Text(
                "${i + 1}.  $cue",
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 2.dp),
            )
        }
        if (improvementCues(analysis).isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
        }

        Eyebrow(
            if (playing) "Playing · ${"%.1f".format(positionS)}s"
            else "Paused · ${"%.1f".format(positionS)}s",
            modifier = Modifier.padding(horizontal = 20.dp),
        )

        val listState = rememberLazyListState()
        LaunchedEffect(activeRep) {
            if (activeRep >= 0) listState.animateScrollToItem(activeRep)
        }
        LazyColumn(
            state = listState,
            modifier = Modifier.weight(1f).fillMaxWidth(),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            itemsIndexed(reps) { i, rep ->
                RepComment(
                    rep = rep,
                    index = i,
                    active = i == activeRep,
                    onClick = { seek(rep.turnS.takeIf { it > 0 } ?: rep.startS) },
                )
            }
        }
    }
}

/** The measured set, drawn on one line: a span per rep, a dot at each turning
 *  point, and the playhead over the moment being watched. Tap to seek. */
@Composable
private fun Timeline(
    reps: List<RepRow>,
    durationS: Float,
    positionS: Float,
    activeRep: Int,
    onSeek: (Float) -> Unit,
    modifier: Modifier = Modifier,
) {
    // Colours are composable reads, so they are captured before the draw
    // lambda - which runs on every frame and is not a composable context.
    val spanColors = reps.map { bandColor(it.band) }
    val playhead = MaterialTheme.colorScheme.primary
    Canvas(
        modifier
            .height(46.dp)
            .pointerInput(durationS) {
                detectTapGestures { offset ->
                    onSeek((offset.x / size.width).coerceIn(0f, 1f) * durationS)
                }
            },
    ) {
        val h = size.height
        val spanTop = h * 0.30f
        val spanBottom = h * 0.62f

        // the unmeasured rest of the clip, so a rep is visibly a part of it
        drawRoundRect(
            color = Color.Gray.copy(alpha = 0.25f),
            topLeft = androidx.compose.ui.geometry.Offset(0f, spanTop),
            size = androidx.compose.ui.geometry.Size(size.width, spanBottom - spanTop),
            cornerRadius = androidx.compose.ui.geometry.CornerRadius(6f, 6f),
        )

        reps.forEachIndexed { i, rep ->
            val x0 = (rep.startS / durationS).toFloat() * size.width
            val x1 = (rep.endS / durationS).toFloat() * size.width
            val color = spanColors[i]
            drawRoundRect(
                color = color.copy(alpha = if (i == activeRep) 0.95f else 0.55f),
                topLeft = androidx.compose.ui.geometry.Offset(x0, spanTop),
                size = androidx.compose.ui.geometry.Size(
                    (x1 - x0).coerceAtLeast(4f), spanBottom - spanTop),
                cornerRadius = androidx.compose.ui.geometry.CornerRadius(6f, 6f),
            )
            // the turning point: where the movement changed direction
            if (rep.turnS > 0) {
                val cx = (rep.turnS / durationS).toFloat() * size.width
                drawCircle(
                    color = color,
                    radius = if (i == activeRep) 7f else 5f,
                    center = androidx.compose.ui.geometry.Offset(
                        cx.coerceIn(x0, x1), (spanTop + spanBottom) / 2f),
                )
            }
        }

        val px = (positionS / durationS).toFloat().coerceIn(0f, 1f) * size.width
        drawLine(
            color = playhead,
            start = androidx.compose.ui.geometry.Offset(px, 0f),
            end = androidx.compose.ui.geometry.Offset(px, h),
            strokeWidth = 3f,
        )
    }
}

@Composable
private fun RepComment(rep: RepRow, index: Int, active: Boolean, onClick: () -> Unit) {
    val color = bandColor(rep.band)
    Column(
        Modifier
            .fillMaxWidth()
            .widthIn(max = 560.dp)
            .clip(RoundedCornerShape(14.dp))
            .background(color.copy(alpha = 0.08f))
            .then(
                if (active) Modifier.border(1.dp, color, RoundedCornerShape(14.dp))
                else Modifier
            )
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 10.dp),
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                "Rep ${index + 1}",
                style = MaterialTheme.typography.labelLarge,
            )
            Pill(
                rep.score?.let { "${rep.band} · $it" } ?: rep.band,
                color = color,
            )
            Spacer(Modifier.weight(1f))
            Text(
                "${"%.1f".format(rep.startS)}s → ${"%.1f".format(rep.endS)}s",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Spacer(Modifier.height(6.dp))
        val body = when {
            rep.problems.isNotEmpty() -> rep.problems.joinToString(" · ")
            rep.scoreNote.isNotBlank() -> rep.scoreNote
            rep.metrics.isNotEmpty() -> rep.metrics.take(3)
                .joinToString(" · ") { "${it.name}: ${it.value}" }
            else -> "measured, nothing flagged"
        }
        Text(body, style = MaterialTheme.typography.bodyMedium)
        if (rep.turnS > 0) {
            Spacer(Modifier.height(4.dp))
            Text(
                "Turning point at ${"%.1f".format(rep.turnS)}s — tap to jump there",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
