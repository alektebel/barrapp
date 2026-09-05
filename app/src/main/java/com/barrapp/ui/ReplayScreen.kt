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
import kotlinx.coroutines.launch

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
                Text("Video review", style = MaterialTheme.typography.titleMedium)
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
    val listState = rememberLazyListState()
    val scope = androidx.compose.runtime.rememberCoroutineScope()
    val screenHeight = androidx.compose.ui.platform.LocalConfiguration.current.screenHeightDp
    val videoHeight = (screenHeight * 0.34f).coerceIn(160f, 360f).dp
    val reps = remember(analysis) { analysis.reps.filter { it.endS > it.startS }.sortedBy { it.startS } }
    // The server measured the working set between trim.startS and trim.endS;
    // everything outside it is the walk to the bar. Playback stays inside.
    var durationS by remember(clip) { mutableFloatStateOf(1f) }
    val windowStart = analysis.trim?.startS?.toFloat()?.coerceAtLeast(0f) ?: 0f
    val windowEnd = analysis.trim?.endS?.toFloat()?.takeIf { it > windowStart } ?: durationS
    var positionS by remember(clip) { mutableFloatStateOf(windowStart) }
    var playing by remember(clip) { mutableStateOf(false) }
    var activeRep by remember(clip) { mutableIntStateOf(-1) }
    var guided by remember { mutableStateOf(true) }
    var reviewed by remember(clip) { mutableStateOf(setOf<Int>()) }
    var mediaPlayer by remember(clip) { mutableStateOf<android.media.MediaPlayer?>(null) }
    var playbackError by remember(clip) { mutableStateOf(false) }
    val videoView = remember(clip) {
        VideoView(context).apply {
            setVideoPath(clip.absolutePath)
            setOnPreparedListener { mp ->
                mediaPlayer = mp
                durationS = (mp.duration / 1000f).coerceAtLeast(1f)
                seekTo((windowStart * 1000).toInt().coerceAtLeast(1))
            }
            setOnErrorListener { _, _, _ -> playbackError = true; true }
        }
    }
    DisposableEffect(videoView) { onDispose { videoView.stopPlayback() } }
    val lifecycleOwner = androidx.lifecycle.compose.LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner, videoView) {
        val observer = androidx.lifecycle.LifecycleEventObserver { _, event ->
            if (event == androidx.lifecycle.Lifecycle.Event.ON_PAUSE) videoView.pause()
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }
    fun moment(rep: RepRow) = rep.turnS.takeIf { it in rep.startS..rep.endS } ?: rep.startS
    fun seek(raw: Double, index: Int = -1) {
        val t = raw.coerceIn(windowStart.toDouble(), windowEnd.toDouble())
        videoView.pause()
        if (android.os.Build.VERSION.SDK_INT >= 26 && mediaPlayer != null) {
            mediaPlayer?.seekTo((t * 1000).toLong(), android.media.MediaPlayer.SEEK_CLOSEST)
        } else {
            videoView.seekTo((t * 1000).toInt())
        }
        positionS = t.toFloat()
        activeRep = index
        reviewed = reps.indices.filter { moment(reps[it]) <= t + 0.15 }.toSet()
    }
    LaunchedEffect(videoView, guided, windowStart, windowEnd) {
        while (true) {
            val current = videoView.currentPosition / 1000f
            if (videoView.isPlaying && current >= windowEnd) {
                seek(windowEnd.toDouble())
            }
            if (videoView.isPlaying) {
                val stop = reps.indices.firstOrNull {
                    guided && it !in reviewed && repFault(reps[it]) != null &&
                        current >= moment(reps[it]) && current <= reps[it].endS
                }
                if (stop != null) {
                    seek(moment(reps[stop]), stop)
                } else {
                    positionS = current
                    activeRep = reps.indexOfFirst { current >= it.startS && current <= it.endS }
                }
            }
            playing = videoView.isPlaying
            delay(80)
        }
    }
    LazyColumn(
        Modifier.fillMaxSize(),
        state = listState,
        contentPadding = androidx.compose.foundation.layout.PaddingValues(bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Box(Modifier.fillMaxWidth().height(videoHeight).background(Color.Black), contentAlignment = Alignment.Center) {
                AndroidView(factory = { videoView }, modifier = Modifier.fillMaxSize())
                reps.getOrNull(activeRep)?.let { rep ->
                    repFault(rep)?.let { fault ->
                        Text("Rep ${activeRep + 1} · $fault", color = Color.White,
                            style = MaterialTheme.typography.labelLarge,
                            modifier = Modifier.align(Alignment.TopCenter).padding(16.dp)
                                .background(Color(0xFF803B21), RoundedCornerShape(16.dp)).padding(12.dp))
                    }
                }
                if (playbackError) Text("This video cannot be played on this device.", color = Color.White,
                    modifier = Modifier.padding(24.dp))
            }
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                androidx.compose.material3.FilledTonalButton(onClick = {
                    if (videoView.isPlaying) videoView.pause() else {
                        if (positionS >= windowEnd - 0.3f) { seek(windowStart.toDouble()); reviewed = emptySet() }
                        videoView.start()
                    }
                }, enabled = !playbackError) { Text(if (playing) "Pause" else "Play") }
                Spacer(Modifier.weight(1f))
                Text("${"%.1f".format(positionS)} / ${"%.1f".format(windowEnd)} s", style = MaterialTheme.typography.bodySmall)
            }
            androidx.compose.material3.Slider(
                value = positionS.coerceIn(windowStart, windowEnd),
                onValueChange = { seek(it.toDouble()) },
                valueRange = windowStart..windowEnd,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
            )
            if (analysis.trim != null && durationS > windowEnd + 0.5f) {
                Text(
                    "Playing the working set, %.1fs\u2013%.1fs of the %.0fs clip."
                        .format(windowStart, windowEnd, durationS),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 20.dp),
                )
            }
            Row(Modifier.padding(horizontal = 20.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Guided review", style = MaterialTheme.typography.titleMedium)
                    if (screenHeight >= 700) Text("Pause at reps with feedback", style = MaterialTheme.typography.bodySmall)
                }
                androidx.compose.material3.Switch(checked = guided, onCheckedChange = { guided = it })
            }
        }
        item {
            val rep = reps.getOrNull(activeRep)
            com.barrapp.ui.parts.Panel(Modifier.padding(horizontal = 16.dp)) {
                Eyebrow(if (rep == null) "Your technique, in focus" else "Rep ${activeRep + 1} · Review moment")
                Spacer(Modifier.height(8.dp))
                Text(rep?.let { repFault(it) } ?: if (rep == null) "Watch. Pause. Improve." else "No technique issue flagged",
                    style = MaterialTheme.typography.headlineSmall)
                Spacer(Modifier.height(8.dp))
                Text(rep?.let { com.barrapp.repAdvice(it) }
                    ?: if (rep != null) "No specific correction was found in the available measurements."
                    else "Choose a rep below to inspect its turning point. Markers locate review moments, not exact fault timestamps.",
                    style = MaterialTheme.typography.bodyMedium)
            }
        }
        item { Eyebrow("${reps.size} reps · Tap to review", Modifier.padding(horizontal = 20.dp)) }
        itemsIndexed(reps) { i, rep ->
            Box(Modifier.padding(horizontal = 16.dp)) {
                RepComment(rep, i, i == activeRep) {
                    seek(moment(rep), i)
                    scope.launch { listState.animateScrollToItem(0) }
                }
            }
        }
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
