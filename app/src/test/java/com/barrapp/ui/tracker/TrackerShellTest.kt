package com.barrapp.ui.tracker

import androidx.activity.ComponentActivity
import androidx.compose.material3.Text
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.barrapp.ui.theme.BarrappTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** El contrato del armazón: cuatro pestañas que avisan de su toque y el «?»
 *  que pide la ayuda para filmar. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], qualifiers = "w360dp-h800dp-420dpi")
class TrackerShellTest {

    @get:Rule
    val rule = createAndroidComposeRule<ComponentActivity>()

    @Test
    fun `tapping a tab reports it`() {
        var picked: TrackerTab? = null
        rule.setContent {
            BarrappTheme {
                TrackerShell(TrackerTab.HOME, { picked = it }) { Text("página") }
            }
        }
        rule.onNodeWithText("PROGRESO").performClick()
        rule.waitForIdle()
        assertEquals(TrackerTab.PROGRESS, picked)
    }

    @Test
    fun `the question mark asks for the filming help`() {
        var helped = false
        rule.setContent {
            BarrappTheme {
                TrackerShell(TrackerTab.HOME, {}, onHelp = { helped = true }) { Text("página") }
            }
        }
        rule.onNodeWithContentDescription("Ayuda: cómo filmar").performClick()
        rule.waitForIdle()
        assertTrue(helped)
    }
}
