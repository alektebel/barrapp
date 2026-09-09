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
import com.barrapp.ui.CheckLine
import com.barrapp.ui.RepCardData
import com.barrapp.ui.RepCheck
import com.barrapp.ui.RepComponent
import com.barrapp.ui.SessionScreen
import com.barrapp.ui.VisionLine
import com.barrapp.ui.WeekBar
import androidx.compose.foundation.verticalScroll
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

    /**
     * Draws the decor view straight onto a software bitmap.
     *
     * `captureToImage()` goes through PixelCopy and a forced redraw, and that
     * redraw never completes under Robolectric here - every test in this class
     * failed with `ComposeTimeoutException: Condition still not satisfied
     * after 2000 ms`, so the screenshots this file exists to produce were
     * never produced. Drawing the view gives the same picture without the
     * round trip. (Same helper as [TrackerScreenshotTest.snap].)
     *
     * The output path is relative to the module, which is where Gradle runs
     * the unit tests from; the old "app/build/..." was relative to the repo
     * root and only worked when the test was run by hand.
     */
    private fun snap(name: String) {
        rule.waitForIdle()
        val view = rule.activity.window.decorView
        val img = Bitmap.createBitmap(
            view.width.coerceAtLeast(1), view.height.coerceAtLeast(1), Bitmap.Config.ARGB_8888,
        )
        rule.runOnUiThread { view.draw(android.graphics.Canvas(img)) }
        val dir = File("build/screenshots").apply { mkdirs() }
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

    /** The session page under measurement version 2: the standard, the
     *  per-check tally, a vision advisory, and rep cards with every status. */
    @Test
    fun session() {
        rule.setContent {
            BarrappTheme(darkTheme = true) {
                androidx.compose.foundation.layout.Column(
                    androidx.compose.ui.Modifier
                        .verticalScroll(androidx.compose.foundation.rememberScrollState())
                ) {
                    SessionScreen(
                        eyebrow = "8 Sep · Muscle-up",
                        verdict = "Solid set.\nFix the stall.",
                        subtitle = "3 reps over a 14-second working set.",
                        score = 64, scoreBand = "solid", bandColor = Nocturne.solid,
                        cues = listOf(
                            "Press out to straight arms at the top of every rep",
                            "Pull both elbows over together",
                        ),
                        onWatchReplay = {},
                        reps = listOf(
                            RepCardData(
                                title = "Muscle up", chip = "solid", chipColor = Nocturne.solid,
                                score = "68", scoreColor = Nocturne.solid, measured = true,
                                times = "5.0s – 7.1s",
                                trace = listOf(0.1f, 0.3f, 0.7f, 1f, 0.9f, 0.4f, 0.1f),
                                traceColor = Nocturne.solid,
                                components = listOf(RepComponent("Range", 40, 82),
                                    RepComponent("Control", 30, 61)),
                                checks = listOf(
                                    RepCheck("Bent arms at the top", "observed",
                                        "support · 5.8–6.0s", "141 deg, needs 160 deg"),
                                    RepCheck("One arm over first", "not_observed",
                                        "transition · 5.4–5.6s", "0.04, limit 0.15"),
                                    RepCheck("Excessive swing", "unobservable", "",
                                        "needs a different camera angle"),
                                ),
                            ),
                            RepCardData(
                                title = "Muscle up", chip = "unmeasured",
                                chipColor = Nocturne.nothing, score = null, scoreColor = null,
                                measured = false,
                                note = "Wrists left the frame.",
                                blocked = "Withheld from the technique checks: " +
                                    "pose implausible for 40% of the rep.",
                            ),
                        ),
                        runLine = "run 260908-abc · build 1a2b3c · pose_landmarker_lite · measurement v2",
                        onBackToWeek = {}, repsOpen = true, onToggleReps = {},
                        standard = "Judged to the strict standard you declared.",
                        checks = listOf(
                            CheckLine("Bent arms at the top", 2, 1, 0),
                            CheckLine("One arm over first", 0, 3, 0),
                            CheckLine("Excessive swing", 0, 0, 3),
                        ),
                        vision = listOf(
                            VisionLine("Rep 2", "bent arms at the top", "observed",
                                "Elbows visibly bent at the top still."),
                        ),
                        visionDisagrees = false,
                    )
                }
            }
        }
        snap("session")
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
