package com.barrapp.ui.theme

import androidx.compose.ui.graphics.Color
import androidx.compose.runtime.staticCompositionLocalOf

/**
 * Nocturne — the palette the design mockup ships in.
 *
 * Dark is the primary face: ink #161826, panels #1c1d28 / #232532, the accent
 * purple #9184d9 with its pale companion #d2cefd. Band colours stay separate
 * from the accent — the accent says "interactive"; the bands say "how the rep
 * went": strong green #62C097, solid blue #74B4DE, shaky amber #D4A257.
 */

// ---- dark (the design's own face) ----
val DarkBackground = Color(0xFF161826)
val DarkSurface = Color(0xFF1C1D28)
val DarkSurfaceVariant = Color(0xFF232532)
val DarkPrimary = Color(0xFF9184D9)
val DarkOnPrimary = Color(0xFF161826)
val DarkPrimaryContainer = Color(0xFF262A60)
val DarkOnPrimaryContainer = Color(0xFFD2CEFD)
val DarkSecondary = Color(0xFF5D5294)
val DarkOutline = Color(0xFF3F424D)
val DarkOnBackground = Color(0xFFE9E9ED)
val DarkOnSurfaceVariant = Color(0xFF9B9DAD)
val DarkError = Color(0xFFD4715F)

// ---- light (same hues, raised to daylight) ----
val LightBackground = Color(0xFFFAF9F5)
val LightSurface = Color(0xFFFFFFFF)
val LightSurfaceVariant = Color(0xFFECEBF6)
val LightPrimary = Color(0xFF5D5294)
val LightOnPrimary = Color(0xFFFFFFFF)
val LightPrimaryContainer = Color(0xFFD2CEFD)
val LightOnPrimaryContainer = Color(0xFF232532)
val LightSecondary = Color(0xFF423A6A)
val LightOutline = Color(0xFFD5D4E2)
val LightOnBackground = Color(0xFF232532)
val LightOnSurfaceVariant = Color(0xFF595D6C)
val LightError = Color(0xFF8E3A38)

/** One colour per quality band, in both themes — green/blue/amber, exactly
 *  the mockup's week-chart hues. */

// band colours — shared across themes, tuned per theme only in weight
data class BandColors(
    val strong: Color,
    val solid: Color,
    val shaky: Color,
    val broken: Color,
    val unmeasured: Color,
)

val DarkBands = BandColors(
    strong = Color(0xFF62C097),
    solid = Color(0xFF74B4DE),
    shaky = Color(0xFFD4A257),
    broken = Color(0xFFC96A5B),
    unmeasured = Color(0xFF3F424D),
)

val LightBands = BandColors(
    strong = Color(0xFF3E9E77),
    solid = Color(0xFF4A8FBC),
    shaky = Color(0xFFB3822F),
    broken = Color(0xFFA9503F),
    unmeasured = Color(0xFFC4C4CE),
)

val LocalBandColors = staticCompositionLocalOf { LightBands }
