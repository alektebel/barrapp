package com.barrapp.ui.theme

import androidx.compose.ui.graphics.Color

/**
 * Barrapp reads as an instrument, not a scoreboard. The palette is cool and
 * quiet so that the only saturated things on screen are the ones carrying a
 * measurement.
 *
 * Score colours are deliberately separate from the accent. The accent says
 * "this is interactive"; the score colours say "this is how the rep went". If
 * they were the same hue the app would look like it was congratulating you for
 * tapping a button.
 */

// ---- light ----
val LightBackground = Color(0xFFF4F7F5)
val LightSurface = Color(0xFFFFFFFF)
val LightSurfaceVariant = Color(0xFFE7ECF1)
val LightPrimary = Color(0xFF006B60)
val LightOnPrimary = Color(0xFFFFFFFF)
val LightSecondary = Color(0xFF4A6274)
val LightOutline = Color(0xFFC4CDD6)
val LightOnBackground = Color(0xFF121B23)
val LightOnSurfaceVariant = Color(0xFF4C5B69)
val LightError = Color(0xFF8E3A38)

// ---- dark ----
val DarkBackground = Color(0xFF0B1515)
val DarkSurface = Color(0xFF142221)
val DarkSurfaceVariant = Color(0xFF1D2933)
val DarkPrimary = Color(0xFF80E5CC)
val DarkOnPrimary = Color(0xFF04202D)
val DarkSecondary = Color(0xFF9EB3C3)
val DarkOutline = Color(0xFF2B3945)
val DarkOnBackground = Color(0xFFDEE6ED)
val DarkOnSurfaceVariant = Color(0xFF9AACBB)
val DarkError = Color(0xFFDE8A87)

/** One colour per quality band, in both themes. */
data class BandColors(
    val strong: Color,
    val solid: Color,
    val shaky: Color,
    val broken: Color,
    val unmeasured: Color,
)

val LightBands = BandColors(
    strong = Color(0xFF2E7D5B),
    solid = Color(0xFF2A6C9C),
    shaky = Color(0xFF97671D),
    broken = Color(0xFF97413F),
    unmeasured = Color(0xFF8494A1),
)

val DarkBands = BandColors(
    strong = Color(0xFF62C097),
    solid = Color(0xFF74B4DE),
    shaky = Color(0xFFD4A257),
    broken = Color(0xFFDE8A87),
    unmeasured = Color(0xFF6F808E),
)
