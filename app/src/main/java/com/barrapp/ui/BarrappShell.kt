package com.barrapp.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import com.barrapp.ui.theme.Nocturne
import com.barrapp.ui.theme.N
import com.barrapp.ui.theme.nocturne

/** The prototype's screens, mutually exclusive, Week first. */
enum class NScreen { WEEK, CALENDAR, TREE, SESSION, UPLOAD, COACH }

/** The prototype's state, verbatim from its source: screen (null = week) and
 *  the reps toggle. Nothing else is stateful in the design. */
class NocturneState(initial: NScreen? = null, repsOpen: Boolean = false) {
    var screen by mutableStateOf(initial)
    var repsOpen by mutableStateOf(repsOpen)
    val effective get() = screen ?: NScreen.WEEK
    fun goWeek() { screen = NScreen.WEEK }
    fun goCal() { screen = NScreen.CALENDAR }
    fun goTree() { screen = NScreen.TREE }
    fun goSession() { screen = NScreen.SESSION }
    fun goUpload() { screen = NScreen.UPLOAD }
    fun goCoach() { screen = NScreen.COACH }
    fun toggleReps() { repsOpen = !repsOpen }
}

/** Hooks into the real app: the picker, the replay, the coach's send. */
class NocturneActions(
    val onPickVideo: () -> Unit = {},
    val onOpenReplay: () -> Unit = {},
    val onSend: (String) -> Unit = {},
)

private fun ink(active: Boolean) = if (active) Nocturne.accentText else Nocturne.fgA(0.5f)

private fun navTextStyle(active: Boolean): TextStyle = nocturne(500, 9, 1f, 0.04.em)
    .copy(color = ink(active))

private fun noRipple(action: () -> Unit): Modifier = Modifier.clickable(
    interactionSource = MutableInteractionSource(),
    indication = null,
    onClick = action,
)

/**
 * The shell: header, scroll area (6/17/96 applied HERE, screens never
 * re-apply it), and the floating nav bar. Nav ink follows the prototype's
 * ink(k) bindings. The bar's backdrop blur is declared as a platform gap and
 * rendered as a solid 0.92 fill instead.
 */
@Composable
fun BarrappShell(
    state: NocturneState,
    subtitle: String,
    onPlus: (() -> Unit)? = null,
    week: @Composable () -> Unit,
    calendar: @Composable () -> Unit,
    tree: @Composable () -> Unit,
    session: @Composable () -> Unit,
    upload: @Composable () -> Unit,
    coach: @Composable () -> Unit,
) {
    Column(Modifier.fillMaxSize().background(Nocturne.background)) {
        // ---- header ----
        Row(
            Modifier.fillMaxWidth().padding(start = 17.dp, top = 14.dp, end = 17.dp, bottom = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // The app's own launcher icon, not the prototype's drawn mark.
            androidx.compose.foundation.Image(
                painter = androidx.compose.ui.res.painterResource(
                    com.barrapp.R.drawable.ic_launcher_foreground),
                contentDescription = null,
                modifier = Modifier.size(32.dp).background(
                    androidx.compose.ui.graphics.Color(0xFF102421),
                    RoundedCornerShape(9.dp)),
            )
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                androidx.compose.material3.Text("barrapp", style = N.logo)
                androidx.compose.material3.Text(subtitle, style = N.subtitle)
            }
            // A chat bubble, not "?": this is the Coach shortcut, and a "?"
            // reads as a help affordance that then silently opens a chat.
            Box(
                Modifier.size(30.dp)
                    .border(1.dp, Nocturne.fgA(0.16f), RoundedCornerShape(8.dp))
                    .then(noRipple(state::goCoach)),
                contentAlignment = Alignment.Center,
            ) {
                Canvas(Modifier.size(16.dp)) {
                    val s = size.width / 16f
                    val p = Path().apply {
                        moveTo(2f * s, 3f * s)
                        lineTo(14f * s, 3f * s)
                        arcTo(androidx.compose.ui.geometry.Rect(10f * s, 2f * s, 15f * s, 7f * s), 0f, 180f, false)
                        lineTo(2f * s, 7f * s)
                        arcTo(androidx.compose.ui.geometry.Rect(1f * s, 2f * s, 6f * s, 7f * s), 180f, 180f, false)
                        close()
                    }
                    drawPath(p, Nocturne.fgA(0.6f), style = Stroke(1.5f * s,
                        cap = StrokeCap.Round, join = androidx.compose.ui.graphics.StrokeJoin.Round))
                    drawLine(Nocturne.fgA(0.6f), Offset(4f * s, 8f * s), Offset(2.5f * s, 11f * s), 1.4f * s)
                    drawLine(Nocturne.fgA(0.6f), Offset(2.5f * s, 11f * s), Offset(7f * s, 8f * s), 1.4f * s)
                }
            }
        }

        // ---- scroll area: the active screen renders here ----
        // The coach renders OUTSIDE the page scroll and manages its own, so its
        // entry box stays pinned while the conversation scrolls past. A screen
        // inside a page scroll would carry the input away with the content.
        Box(Modifier.weight(1f)) {
            if (state.effective == NScreen.COACH) {
                // A small bottom pad only: the pinned entry box should sit
                // next to the nav bar, not a page-scroll's 96dp above it.
                Box(
                    Modifier.fillMaxSize()
                        .padding(start = 17.dp, top = 6.dp, end = 17.dp, bottom = 8.dp),
                ) {
                    coach()
                }
            } else {
                Column(
                    Modifier.fillMaxSize()
                        .verticalScroll(rememberScrollState())
                        .padding(start = 17.dp, top = 6.dp, end = 17.dp, bottom = 96.dp),
                ) {
                    when (state.effective) {
                        NScreen.WEEK -> week()
                        NScreen.CALENDAR -> calendar()
                        NScreen.TREE -> tree()
                        NScreen.SESSION -> session()
                        NScreen.UPLOAD -> upload()
                        NScreen.COACH -> {}
                    }
                }
            }
        }

        // ---- nav bar ----
        Box(Modifier.fillMaxWidth().padding(start = 17.dp, end = 17.dp, bottom = 16.dp)) {
            Row(
                Modifier.fillMaxWidth()
                    .height(58.dp)
                    .shadow(12.dp, RoundedCornerShape(14.dp), clip = false,
                        ambientColor = Nocturne.dropShadow, spotColor = Nocturne.dropShadow)
                    .background(Nocturne.navFill, RoundedCornerShape(14.dp))
                    .border(1.dp, Nocturne.hairline, RoundedCornerShape(14.dp)),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                NavSlot("Week", state.effective == NScreen.WEEK, state::goWeek) { size ->
                    drawWeekIcon(ink(state.effective == NScreen.WEEK), size)
                }
                NavSlot("Calendar", state.effective == NScreen.CALENDAR, state::goCal) { size ->
                    drawCalIcon(ink(state.effective == NScreen.CALENDAR), size)
                }
                // the + slot: 46x42, its own accent border, gap 2, margin 0 2
                Box(
                    Modifier.padding(horizontal = 2.dp)
                        .width(46.dp).height(42.dp)
                        .border(1.dp, Nocturne.accent, RoundedCornerShape(11.dp))
                        .then(noRipple { onPlus?.invoke() ?: state.goUpload() }),
                    contentAlignment = Alignment.Center,
                ) {
                    Canvas(Modifier.size(18.dp)) { drawPlus() }
                }
                NavSlot("Ladder", state.effective == NScreen.TREE, state::goTree) { size ->
                    drawTreeIcon(ink(state.effective == NScreen.TREE), size)
                }
                NavSlot("Coach", state.effective == NScreen.COACH, state::goCoach) { size ->
                    drawCoachIcon(ink(state.effective == NScreen.COACH), size)
                }
            }
        }
    }
}

@Composable
private fun androidx.compose.foundation.layout.RowScope.NavSlot(
    label: String,
    active: Boolean,
    onClick: () -> Unit,
    icon: androidx.compose.ui.graphics.drawscope.DrawScope.(Size) -> Unit,
) {
    Column(
        Modifier.weight(1f)
            .then(noRipple(onClick))
            .padding(vertical = 8.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Canvas(Modifier.size(19.dp)) { icon(size) }
        androidx.compose.material3.Text(label, style = navTextStyle(active))
    }
}

// ---- vector art, drawn from the fragments' own path data ----

/** Header logo: 40 box, rx 11, the rep trace over the bar line. */
private fun androidx.compose.ui.graphics.drawscope.DrawScope.logoMark() {
    val s = size.width / 40f
    drawRoundRect(Nocturne.surface, cornerRadius = CornerRadius(11f * s, 11f * s),
        size = Size(40f * s, 40f * s))
    drawPath(Path().apply {
        moveTo(9f * s, 27.5f * s)
        cubicTo(14f * s, 27.5f * s, 15.5f * s, 12.5f * s, 20f * s, 12.5f * s)
        cubicTo(24.5f * s, 27.5f * s, 26f * s, 27.5f * s, 31f * s, 27.5f * s)
    }, Nocturne.accent, style = Stroke(2.6f * s, cap = StrokeCap.Round))
    drawLine(Color(0xFF5D5294), Offset(8f * s, 15.5f * s), Offset(32f * s, 15.5f * s),
        strokeWidth = 2.2f * s, cap = StrokeCap.Round)
}

private fun androidx.compose.ui.graphics.drawscope.DrawScope.drawWeekIcon(c: Color, size: Size) {
    val s = size.width / 20f
    drawPath(Path().apply {
        moveTo(2f * s, 14f * s)
        cubicTo(5f * s, 14f * s, 6f * s, 6f * s, 10f * s, 6f * s)
        cubicTo(14f * s, 6f * s, 15f * s, 14f * s, 18f * s, 14f * s)
    }, c, style = Stroke(1.8f * s, cap = StrokeCap.Round))
}

private fun androidx.compose.ui.graphics.drawscope.DrawScope.drawCalIcon(c: Color, size: Size) {
    val s = size.width / 20f
    drawRoundRect(c, topLeft = Offset(3f * s, 4.5f * s),
        size = Size(14f * s, 12.5f * s), cornerRadius = CornerRadius(2.5f * s, 2.5f * s),
        style = Stroke(1.6f * s))
    drawLine(c, Offset(3f * s, 8.5f * s), Offset(17f * s, 8.5f * s), 1.6f * s)
    drawCircle(c, 1.3f * s, Offset(7.5f * s, 12.5f * s))
}

private fun androidx.compose.ui.graphics.drawscope.DrawScope.drawPlus() {
    val s = size.width / 20f
    drawLine(Nocturne.accentText, Offset(10f * s, 4f * s), Offset(10f * s, 16f * s),
        1.9f * s, cap = StrokeCap.Round)
    drawLine(Nocturne.accentText, Offset(4f * s, 10f * s), Offset(16f * s, 10f * s),
        1.9f * s, cap = StrokeCap.Round)
}

private fun androidx.compose.ui.graphics.drawscope.DrawScope.drawTreeIcon(c: Color, size: Size) {
    val s = size.width / 20f
    drawLine(c, Offset(6f * s, 4f * s), Offset(6f * s, 16f * s), 1.6f * s)
    drawCircle(c, 2f * s, Offset(6f * s, 5f * s))
    drawCircle(c, 2f * s, Offset(6f * s, 10f * s), style = Stroke(1.6f * s))
    drawLine(c, Offset(6f * s, 15f * s), Offset(14f * s, 15f * s), 1.6f * s)
    drawCircle(c, 2f * s, Offset(15f * s, 15f * s), style = Stroke(1.6f * s))
}

private fun androidx.compose.ui.graphics.drawscope.DrawScope.drawCoachIcon(c: Color, size: Size) {
    val s = size.width / 20f
    fun r(l: Float, t: Float, rgt: Float, b: Float) =
        androidx.compose.ui.geometry.Rect(l * s, t * s, rgt * s, b * s)
    drawPath(Path().apply {
        moveTo(4f * s, 5.5f * s)
        lineTo(16f * s, 5.5f * s)
        arcTo(r(14.5f, 5.5f, 17.5f, 8.5f), -90f, 90f, false)
        lineTo(17.5f * s, 12f * s)
        arcTo(r(14.5f, 10.5f, 17.5f, 13.5f), 0f, 90f, false)
        lineTo(10f * s, 13.5f * s)
        lineTo(6.5f * s, 16.5f * s)
        lineTo(6.5f * s, 13.5f * s)
        lineTo(4f * s, 13.5f * s)
        arcTo(r(2.5f, 10.5f, 5.5f, 13.5f), 90f, 90f, false)
        lineTo(2.5f * s, 7f * s)
        arcTo(r(2.5f, 4f, 5.5f, 7f), 180f, 90f, false)
        close()
    }, c, style = Stroke(1.6f * s,
        join = androidx.compose.ui.graphics.StrokeJoin.Round))
}
