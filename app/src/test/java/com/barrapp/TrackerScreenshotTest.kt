package com.barrapp

import android.graphics.Bitmap
import android.graphics.Canvas
import androidx.activity.ComponentActivity
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import com.barrapp.data.ActivityLevel
import com.barrapp.data.Profile
import com.barrapp.ui.theme.BarrappTheme
import com.barrapp.ui.tracker.HomeData
import com.barrapp.ui.tracker.LastSessionData
import com.barrapp.ui.tracker.SessionRowData
import com.barrapp.ui.theme.Tk
import com.barrapp.ui.tracker.CoachData
import com.barrapp.ui.tracker.CoachFocus
import com.barrapp.ui.tracker.CoachRule
import com.barrapp.ui.tracker.HistoryRow
import com.barrapp.ui.tracker.LastAnalyzed
import com.barrapp.ui.tracker.PersonalBest
import com.barrapp.ui.tracker.ProgressData
import com.barrapp.ui.tracker.RecordPhase
import com.barrapp.ui.tracker.RepCardItem
import com.barrapp.ui.tracker.ResultsData
import com.barrapp.ui.tracker.TrackerCoach
import com.barrapp.ui.tracker.TrackerHome
import com.barrapp.ui.tracker.TrackerProgress
import com.barrapp.ui.tracker.TrackerRecord
import com.barrapp.ui.tracker.TrendPoint
import com.barrapp.ui.tracker.TrackerOnboarding
import com.barrapp.ui.tracker.TrackerShell
import com.barrapp.ui.tracker.TrackerTab
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File
import java.util.Calendar

/**
 * Screenshots of the redesigned screens.
 *
 * Deliberately does NOT use `captureToImage()`. That path goes through
 * PixelCopy and a forced redraw, which never completes under Robolectric in
 * this environment — every test in [UiScreenshotTest] times out there, before
 * and after this redesign. Drawing the decor view straight onto a software
 * bitmap sidesteps it and produces the same picture.
 *
 * Run:  ./gradlew :app:testDebugUnitTest --tests '*TrackerScreenshotTest'
 * then look in app/build/screenshots.
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [35], qualifiers = "w360dp-h800dp-420dpi")
class TrackerScreenshotTest {

    @get:Rule
    val rule = createAndroidComposeRule<ComponentActivity>()

    private fun snap(name: String) {
        rule.waitForIdle()
        val view = rule.activity.window.decorView
        val bitmap = Bitmap.createBitmap(
            view.width.coerceAtLeast(1), view.height.coerceAtLeast(1), Bitmap.Config.ARGB_8888,
        )
        rule.runOnUiThread { view.draw(Canvas(bitmap)) }
        val dir = File("build/screenshots").apply { mkdirs() }
        val out = File(dir, "$name.png")
        out.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
        println("screenshot: ${out.absolutePath} (${bitmap.width}x${bitmap.height})")
    }

    private fun sampleHome(measured: Boolean): HomeData {
        val days = if (!measured) emptyList() else listOf(
            sampleDay(0, 8, 71), sampleDay(-1, 6, 64), sampleDay(-2, 7, 58),
        )
        return HomeData(
            name = "Diego",
            standing = Gamification.standing(days),
            week = Gamification.week(days),
            mission = Gamification.mission(
                days, Profile("Diego", 30, ActivityLevel.Regular), "pull_up",
                "corta el balanceo — tira estricto, sin impulso",
            ),
            lastSession = days.firstOrNull()?.let {
                LastSessionData(
                    movement = "Dominada", date = "8 sept", reps = it.reps, score = it.score,
                    rows = listOf(SessionRowData("Dominada", it.score, it.reps)),
                    topFault = "Balanceo" to 4,
                )
            },
            badges = Gamification.badges(days, "pull_up"),
        )
    }

    private fun sampleDay(offset: Int, reps: Int, score: Int): com.barrapp.data.DayEntry {
        val c = Calendar.getInstance().apply { add(Calendar.DAY_OF_YEAR, offset) }
        val iso = "%04d-%02d-%02d".format(
            c.get(Calendar.YEAR), c.get(Calendar.MONTH) + 1, c.get(Calendar.DAY_OF_MONTH))
        return com.barrapp.data.DayEntry(
            date = iso, exercise = "pull_up", exerciseLabel = "Pull-up",
            reps = reps, score = score, band = "solid", jobIds = listOf("j-$iso"),
            byMovement = mapOf("pull_up" to com.barrapp.data.MovementDay(
                "pull_up", "Pull-up", reps, reps, score * reps)),
        )
    }

    @Test
    fun home() {
        rule.setContent {
            BarrappTheme {
                TrackerShell(TrackerTab.HOME, {}, Modifier.fillMaxSize()) {
                    TrackerHome(sampleHome(true), {}, {}, {}, {}, {})
                }
            }
        }
        snap("tracker-home")
    }

    @Test
    fun homeEmpty() {
        rule.setContent {
            BarrappTheme {
                TrackerShell(TrackerTab.HOME, {}, Modifier.fillMaxSize()) {
                    TrackerHome(sampleHome(false), {}, {}, {}, {}, {})
                }
            }
        }
        snap("tracker-home-empty")
    }

    @Test
    fun record() {
        rule.setContent {
            BarrappTheme {
                TrackerShell(TrackerTab.RECORD, {}, Modifier.fillMaxSize()) {
                    TrackerRecord(
                        phase = RecordPhase.IDLE,
                        stages = emptyList(), activeStage = 0, results = null,
                        lastAnalyzed = LastAnalyzed("Dominada", "8 sept · 8 reps", 71),
                        standard = "strict", camera = "",
                        onStandard = {}, onCamera = {}, onRecord = {}, onPick = {}, onDone = {},
                    )
                }
            }
        }
        snap("tracker-record")
    }

    @Test
    fun recordResults() {
        rule.setContent {
            BarrappTheme {
                TrackerShell(TrackerTab.RECORD, {}, Modifier.fillMaxSize()) {
                    TrackerRecord(
                        phase = RecordPhase.RESULTS,
                        stages = emptyList(), activeStage = 0,
                        results = ResultsData(
                            movement = "Dominada", setsLabel = "1 serie", reps = 6, score = 71,
                            faults = listOf("Balanceo" to 4, "Sin bloqueo arriba" to 2),
                            repCards = listOf(
                                RepCardItem("Rep 1", 88, emptyList(), "1.2–3.0s", null),
                                RepCardItem("Rep 2", 74, listOf("Balanceo"), "3.4–5.1s", null),
                                RepCardItem("Rep 3", 52,
                                    listOf("Balanceo", "Sin bloqueo arriba"), "5.5–7.4s", null),
                                RepCardItem("Rep 4", null, emptyList(), "7.8–9.6s", null),
                            ),
                            xp = 134, aboveAverage = true,
                        ),
                        lastAnalyzed = null,
                        standard = "", camera = "",
                        onStandard = {}, onCamera = {}, onRecord = {}, onPick = {}, onDone = {},
                    )
                }
            }
        }
        snap("tracker-record-results")
    }

    @Test
    fun progress() {
        rule.setContent {
            BarrappTheme {
                TrackerShell(TrackerTab.PROGRESS, {}, Modifier.fillMaxSize()) {
                    TrackerProgress(
                        data = ProgressData(
                            averageScore = 71, averageDelta = 9, repsThisMonth = 84,
                            bestScore = 81, bestScoreDate = "31 ago",
                            trend = listOf(
                                TrendPoint("9 ago", 58), TrendPoint("13 ago", 61),
                                TrendPoint("17 ago", 59), TrendPoint("21 ago", 66),
                                TrendPoint("25 ago", 64), TrendPoint("29 ago", 72),
                                TrendPoint("2 sept", 70), TrendPoint("8 sept", 76),
                            ),
                            bests = listOf(
                                PersonalBest("Dominada", "Mejor día", "81", "pts", "31 ago"),
                                PersonalBest("Dominada", "Más reps en un día", "19", "reps", "27 ago"),
                            ),
                            faults = listOf(
                                FaultTrend.Row("momentum", 19, -7, 26),
                                FaultTrend.Row("lockout", 12, -2, 14),
                                FaultTrend.Row("poor range of motion", 6, 3, 3),
                            ),
                            history = listOf(
                                HistoryRow("2026-09-08", "8 sept", "Dominada", 8, 1, 71),
                                HistoryRow("2026-09-07", "7 sept", "Dominada", 6, 2, 64),
                                HistoryRow("2026-09-06", "6 sept", "Flexión", 12, 1, null),
                            ),
                        ),
                        onOpenDay = {}, onOpenLadder = {}, onRecord = {},
                    )
                }
            }
        }
        snap("tracker-progress")
    }

    @Test
    fun coach() {
        rule.setContent {
            BarrappTheme {
                TrackerShell(TrackerTab.COACH, {}, Modifier.fillMaxSize()) {
                    TrackerCoach(
                        data = CoachData(
                            movement = "Dominada", sessions = 4,
                            focus = CoachFocus(
                                "Balanceo",
                                "Corta el balanceo — tira estricto, sin impulso.",
                                drillEs("momentum"), 19, 27, true,
                            ),
                            secondary = CoachFocus(
                                "Sin bloqueo arriba",
                                "Bloquea del todo arriba en cada repetición.",
                                drillEs("lockout"), 12, 14, true,
                            ),
                            rules = listOf(
                                CoachRule("swing", "Balanceo", "Toda la repetición", "Corregir",
                                    Tk.amber,
                                    "Se detectó en 4 de 6 reps juzgadas en la última serie.",
                                    "Corta el balanceo — tira estricto, sin impulso."),
                                CoachRule("lockout", "Sin bloqueo arriba", "Bloqueo superior",
                                    "Progresando", Tk.teal,
                                    "Se detectó en 2 de 6 reps juzgadas en la última serie.",
                                    "Bloquea del todo arriba en cada repetición."),
                                CoachRule("hang", "Sin dead hang", "Posición baja", "Correcto",
                                    Tk.primaryLight,
                                    "Comprobado en 6 reps y limpio en todas ellas.", ""),
                            ),
                            drills = listOfNotNull(drillEs("momentum"), drillEs("lockout")),
                            totalMinutes = 7,
                        ),
                        onAskCoach = {}, onRecord = {},
                    )
                }
            }
        }
        snap("tracker-coach")
    }

    @Test
    fun onboarding() {
        rule.setContent {
            BarrappTheme { TrackerOnboarding(onComplete = {}, modifier = Modifier.fillMaxSize()) }
        }
        snap("tracker-onboarding")
    }
}
