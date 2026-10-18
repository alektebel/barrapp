package com.barrapp.ui.tracker

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
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
 * underneath, and the notes' "?" at the trailing edge of that bar.
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
    onHelp: () -> Unit = {},
    content: @Composable () -> Unit,
) {
    Column(modifier.fillMaxSize().background(Tk.bg)) {
        Box(Modifier.weight(1f).fillMaxWidth()) { content() }
        TrackerNav(tab, onTab, onHelp)
    }
}

/**
 * The design's bottom bar (the `tabs()` template of the spec): four equal
 * columns over a 2dp ink border, each tab a 22x4 bar sitting on top of a mono
 * label — orange when active, transparent otherwise — and no icons. The "?"
 * the notes give the shell opens the help on how to film.
 */
@Composable
private fun TrackerNav(tab: TrackerTab, onTab: (TrackerTab) -> Unit, onHelp: () -> Unit) {
    Column {
        Box(Modifier.fillMaxWidth().height(2.dp).background(Tk.border))
        Row(
            Modifier
                .fillMaxWidth()
                .background(Tk.bg)
                .padding(start = 6.dp, end = 8.dp, top = 8.dp, bottom = 14.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(Modifier.weight(1f)) {
                TrackerTab.entries.forEach { t ->
                    NavSlot(t, tab == t, Modifier.weight(1f)) { onTab(t) }
                }
            }
            HelpSlot(onHelp)
        }
    }
}

@Composable
private fun NavSlot(
    tab: TrackerTab,
    active: Boolean,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    Column(
        modifier
            .heightIn(min = 48.dp)
            .noRipple(onClick),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(4.dp, Alignment.CenterVertically),
    ) {
        Box(
            Modifier
                .width(22.dp)
                .height(4.dp)
                .background(if (active) Tk.primary else Color.Transparent),
        )
        Text(
            tab.label.uppercase(),
            style = mono(
                11, 0.05f,
                if (active) Tk.ink else Tk.muted,
                if (active) FontWeight.SemiBold else FontWeight.Normal,
            ),
        )
    }
}

/** Help is a control like any other — white, 2dp ink border — but never the
 *  screen's action, so no orange and no hard shadow. */
@Composable
private fun HelpSlot(onHelp: () -> Unit) {
    Box(
        Modifier
            .size(48.dp)
            .clip(CircleShape)
            .background(Tk.surface)
            .border(2.dp, Tk.border, CircleShape)
            .noRipple(onHelp)
            .semantics { contentDescription = "Ayuda: cómo filmar" },
        contentAlignment = Alignment.Center,
    ) {
        Text("?", style = mono(18, 0f, Tk.ink, FontWeight.SemiBold))
    }
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
