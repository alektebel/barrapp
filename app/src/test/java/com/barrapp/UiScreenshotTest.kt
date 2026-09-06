package com.barrapp

import android.graphics.Bitmap
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.test.captureToImage
import androidx.activity.ComponentActivity
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.width
import org.robolectric.RobolectricTestRunner
import com.barrapp.ui.theme.BarrappTheme
import com.barrapp.ui.CalRow
import com.barrapp.ui.CalDay
import com.barrapp.ui.CalKind
import com.barrapp.ui.CalendarScreen
import com.barrapp.ui.CoachScreen
import com.barrapp.ui.CoachTurn
import com.barrapp.ui.LadderChipKind
import com.barrapp.ui.LadderDot
import com.barrapp.ui.LadderLine
import com.barrapp.ui.LadderScreen
import com.barrapp.ui.LadderStep
import com.barrapp.ui.LastSessionCard
import com.barrapp.ui.WeekBar
import com.barrapp.ui.WeekScreen
import com.barrapp.ui.theme.Nocturne
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

/**
 * Renders the real Compose screens to PNG on the JVM, so an agent or a vision
 * model can look at the actual UI without an emulator. Screenshots land in
 * app/build/screenshots/.
 *
 * Run:
 *   ./gradlew testDebugUnitTest --tests "*UiScreenshotTest*"
 *
 * Then inspect the PNGs, or hand them to the vision harness:
 *   python tools/visual_assess.py  # (after pointing it at build/screenshots)
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [35], qualifiers = "w360dp-h640dp-420dpi")
class UiScreenshotTest {

    @get:Rule
    val rule = createAndroidComposeRule<ComponentActivity>()

    private fun snap(name: String) {
        rule.waitForIdle()
        val img = rule.onRoot().captureToImage().asAndroidBitmap()
        val dir = File("app/build/screenshots").apply { mkdirs() }
        val out = File(dir, "$name.png")
        out.outputStream().use { img.compress(Bitmap.CompressFormat.PNG, 100, it) }
        println("screenshot: ${out.absolutePath} (${img.width}x${img.height})")
    }

    @Test
    fun week() {
        rule.setContent {
            BarrappTheme(darkTheme = true) {
                WeekScreen(
                    reps = 28, measuredDays = 3, delta = "+22 vs last",
                    bars = listOf(
                        WeekBar("M", 0.8f, Nocturne.strong),
                        WeekBar("T", null, null),
                        WeekBar("W", 0.5f, Nocturne.solid),
                        WeekBar("T", 0.2f, Nocturne.shaky, dashed = true),
                        WeekBar("F", 0.0f, null),
                        WeekBar("S", 0.0f, null),
                        WeekBar("S", 0.0f, null),
                    ),
                    unlockTitle = "Muscle-up", unlockCount = "5 / 8",
                    unlockNote = "8 verified reps and 2 qualifying days to go.",
                    unlockProgress = 0.62f, onOpenLadder = {},
                    lastSession = LastSessionCard(
                        "Muscle-up · 2 reps", "Solid. Weakest part was smoothness.",
                        "Thu 14 Aug · 13s working set", 78, 0.78f, Nocturne.solid,
                    ),
                    onOpenSession = {}, onOpenCoach = {},
                )
            }
        }
        snap("week")
    }

    @Test
    fun calendar() {
        rule.setContent {
            BarrappTheme(darkTheme = true) {
                val today = 6
                val days = (1..30).map { d ->
                    val kind = when {
                        d == today -> CalKind.TODAY
                        d % 5 == 0 -> CalKind.MEASURED
                        d % 3 == 0 -> CalKind.DASHED
                        else -> CalKind.PLAIN
                    }
                    CalDay(d, kind, Nocturne.solid, leadingBlanks = if (d == 1) 4 else 0)
                }
                CalendarScreen(
                    month = "August", year = "2026", days = days,
                    summaryMeasured = "4 measured days", summaryReps = "28 reps in August",
                    rows = listOf(CalRow("Muscle-up", "2 reps · 14 Aug", "78", Nocturne.solid,
                        Nocturne.solid, true, 14)),
                    onOpenDay = {},
                )
            }
        }
        snap("calendar")
    }

    @Test
    fun ladder() {
        rule.setContent {
            BarrappTheme(darkTheme = true) {
                LadderScreen(listOf(
                    LadderStep("Push-up", LadderChipKind.EARNED,
                        lines = listOf(LadderLine("", "19 verified at 94 · 3 days")),
                        dot = LadderDot.EARNED),
                    LadderStep("Muscle-up", null,
                        count = "5 / 8", progress = 0.62f,
                        lines = listOf(LadderLine("The standard", "8 reps at 47+ on 2 days"),
                            LadderLine("Your evidence", "Best session: 5 at 78"),
                            LadderLine("", "Still needed: 3 more reps.", accent = true)),
                        dot = LadderDot.CURRENT, big = true, borderColor = Nocturne.accentDeep),
                    LadderStep("Weighted pull-up", LadderChipKind.NOT_MEASURABLE,
                        lines = listOf(LadderLine("", "Barra can't verify added load.")),
                        dot = LadderDot.LOCKED, ghost = true),
                ))
            }
        }
        snap("ladder")
    }

    @Test
    fun coach() {
        rule.setContent {
            BarrappTheme(darkTheme = true) {
                CoachScreen(
                    turns = listOf(
                        CoachTurn(false, "From your data: 28 reps across 3 days."),
                        CoachTurn(true, "How is my muscle-up?",
                            "Work the transition drill — the crossing is slow."),
                    ),
                    thinking = false,
                    suggestions = listOf("How is my progress?", "What should I work on?"),
                    onSend = {}, onBackToWeek = {},
                )
            }
        }
        snap("coach")
    }
}
