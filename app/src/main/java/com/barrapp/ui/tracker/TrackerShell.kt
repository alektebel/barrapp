package com.barrapp.ui.tracker

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.unit.dp
import com.barrapp.ui.theme.T
import com.barrapp.ui.theme.Tk
import com.barrapp.ui.theme.mono

/** The design's four tabs, in its order. */
enum class TrackerTab(val label: String) {
    HOME("Inicio"),
    RECORD("Grabar"),
    PROGRESS("Progreso"),
    COACH("Coach"),
}

/**
 * The frame every tab renders inside: the page on top, the design's bottom bar
 * underneath.
 *
 * The mockup drew its own status bar (a fixed "9:41", a battery) because it
 * lived in a browser. On a phone the real one is right there, so it is gone —
 * the one place this port deliberately renders less than the design.
 */
@Composable
fun TrackerShell(
    tab: TrackerTab,
    onTab: (TrackerTab) -> Unit,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    Column(modifier.fillMaxSize().background(Tk.bg)) {
        Box(Modifier.weight(1f).fillMaxWidth()) { content() }
        TrackerNav(tab, onTab)
    }
}

@Composable
private fun TrackerNav(tab: TrackerTab, onTab: (TrackerTab) -> Unit) {
    Column {
        Box(Modifier.fillMaxWidth().height(1.dp).background(Tk.border))
        Row(
            Modifier
                .fillMaxWidth()
                .background(Tk.bg)
                .padding(start = 8.dp, end = 8.dp, top = 8.dp, bottom = 12.dp),
            horizontalArrangement = Arrangement.SpaceAround,
            verticalAlignment = Alignment.Bottom,
        ) {
            TrackerTab.entries.forEach { t ->
                NavSlot(t, tab == t) { onTab(t) }
            }
        }
    }
}

@Composable
private fun NavSlot(tab: TrackerTab, active: Boolean, onClick: () -> Unit) {
    val ink = if (active) Tk.primaryLight else Tk.muted
    val fill = if (active) Tk.primaryA(0.15f) else Color.Transparent
    Column(
        Modifier.noRipple(onClick).padding(horizontal = 16.dp, vertical = 4.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Canvas(Modifier.size(22.dp)) {
            when (tab) {
                TrackerTab.HOME -> drawHome(ink, fill)
                TrackerTab.RECORD -> drawRecord(ink, fill)
                TrackerTab.PROGRESS -> drawProgress(ink)
                TrackerTab.COACH -> drawCoach(ink, fill)
            }
        }
        Text(tab.label.uppercase(), style = mono(9, 0.05f, ink))
        Box(
            Modifier
                .size(4.dp)
                .background(if (active) Tk.primary else Color.Transparent, CircleShape)
        )
    }
}

// ---- the nav icons, from the design's own 22x22 path data ------------------

private fun DrawScope.unit() = size.width / 22f

private fun DrawScope.drawHome(ink: Color, fill: Color) {
    val s = unit()
    val roof = Path().apply {
        moveTo(3f * s, 9.5f * s)
        lineTo(11f * s, 3f * s)
        lineTo(19f * s, 9.5f * s)
        lineTo(19f * s, 20f * s)
        lineTo(3f * s, 20f * s)
        close()
    }
    if (fill != Color.Transparent) drawPath(roof, fill)
    drawPath(roof, ink, style = Stroke(1.7f * s, join = StrokeJoin.Round))
    drawPath(Path().apply {
        moveTo(8f * s, 20f * s)
        lineTo(8f * s, 12f * s)
        lineTo(14f * s, 12f * s)
        lineTo(14f * s, 20f * s)
    }, ink, style = Stroke(1.7f * s, join = StrokeJoin.Round))
}

private fun DrawScope.drawRecord(ink: Color, fill: Color) {
    val s = unit()
    val centre = Offset(11f * s, 11f * s)
    if (fill != Color.Transparent) drawCircle(fill, 8.5f * s, centre)
    drawCircle(ink, 8.5f * s, centre, style = Stroke(1.7f * s))
    drawCircle(ink, 4f * s, centre)
}

private fun DrawScope.drawProgress(ink: Color) {
    val s = unit()
    drawPath(Path().apply {
        moveTo(2f * s, 16f * s)
        lineTo(7f * s, 10f * s)
        lineTo(11f * s, 13f * s)
        lineTo(16f * s, 6f * s)
        lineTo(20f * s, 9f * s)
    }, ink, style = Stroke(1.7f * s, cap = StrokeCap.Round, join = StrokeJoin.Round))
    drawCircle(ink, 1.5f * s, Offset(20f * s, 9f * s))
}

private fun DrawScope.drawCoach(ink: Color, fill: Color) {
    val s = unit()
    val head = Offset(11f * s, 7.5f * s)
    if (fill != Color.Transparent) drawCircle(fill, 3.5f * s, head)
    drawCircle(ink, 3.5f * s, head, style = Stroke(1.7f * s))
    // M3.5 19c0-4.14 3.36-7.5 7.5-7.5s7.5 3.36 7.5 7.5 — the shoulders: the
    // top half of a circle of radius 7.5 centred at (11, 19), so the bounding
    // box starts at y = 11.5. Centring it on the head instead drew an eyebrow.
    drawArc(
        color = ink,
        startAngle = 180f, sweepAngle = 180f, useCenter = false,
        topLeft = Offset(3.5f * s, 11.5f * s),
        size = Size(15f * s, 15f * s),
        style = Stroke(1.7f * s, cap = StrokeCap.Round),
    )
}

/** The `w-8 h-8 rounded-lg` logo mark from the onboarding header: the bar and
 *  the rep trace over it. */
fun DrawScope.drawLogoMark() {
    val s = size.width / 16f
    drawLine(Tk.primary, Offset(4f * s, 8f * s), Offset(12f * s, 8f * s),
        2.5f * s, cap = StrokeCap.Round)
    drawPath(Path().apply {
        moveTo(4f * s, 12f * s)
        cubicTo(5.5f * s, 12f * s, 6f * s, 6f * s, 8f * s, 6f * s)
        cubicTo(10f * s, 6f * s, 10.5f * s, 12f * s, 12f * s, 12f * s)
    }, Tk.primaryLight, style = Stroke(2f * s, cap = StrokeCap.Round))
}

/** The amber warning triangle the "top fault" strip wears. */
fun DrawScope.drawWarning(ink: Color) {
    val s = size.width / 14f
    drawPath(Path().apply {
        moveTo(7f * s, 1.5f * s)
        lineTo(13f * s, 12.5f * s)
        lineTo(1f * s, 12.5f * s)
        close()
    }, ink, style = Stroke(1.5f * s, cap = StrokeCap.Round, join = StrokeJoin.Round))
    drawLine(ink, Offset(7f * s, 5.5f * s), Offset(7f * s, 8.5f * s),
        1.5f * s, cap = StrokeCap.Round)
    drawCircle(ink, 0.7f * s, Offset(7f * s, 10.5f * s))
}

/** The check the finished week days wear. */
fun DrawScope.drawCheck(ink: Color) {
    val s = size.width / 12f
    drawPath(Path().apply {
        moveTo(2f * s, 6f * s)
        lineTo(5f * s, 9f * s)
        lineTo(10f * s, 3f * s)
    }, ink, style = Stroke(2f * s, cap = StrokeCap.Round, join = StrokeJoin.Round))
}

/** The chevron on every expandable row. */
fun DrawScope.drawChevron(ink: Color, flipped: Boolean) {
    val s = size.width / 14f
    val path = Path().apply {
        moveTo(3f * s, 5f * s)
        lineTo(7f * s, 9f * s)
        lineTo(11f * s, 5f * s)
    }
    if (flipped) {
        rotate(180f) {
            drawPath(path, ink, style = Stroke(1.5f * s, cap = StrokeCap.Round, join = StrokeJoin.Round))
        }
    } else {
        drawPath(path, ink, style = Stroke(1.5f * s, cap = StrokeCap.Round, join = StrokeJoin.Round))
    }
}

@Suppress("unused")
private fun DrawScope.rectOf(l: Float, t: Float, r: Float, b: Float) = Rect(l, t, r, b)
