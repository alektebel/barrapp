package com.barrapp.ui.theme

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.PlatformTextStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.LineHeightStyle
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import com.barrapp.R

/**
 * The Calisthenics Progress Tracker design, ported from its React source.
 *
 * Every colour here is a token from the design's `@theme` block, and every
 * type style below is one of its Tailwind class stacks resolved to concrete
 * numbers — `text-[38px] font-black leading-none tracking-[0.02em]` becomes
 * `display(38, Black, 1f, 0.02f)`. Nothing is rounded or reinterpreted.
 *
 * Two declared departures from the mockup, both because the mockup's data was
 * invented and this app's is measured:
 *
 *  1. Score bands. The design cuts at 85/70/55; barra's own boundaries are
 *     73/47/20 (Progression.STRONG/SOLID/SHAKY), calibrated against the real
 *     score distribution. The app keeps its own cuts and wears the design's
 *     colours over them, so a "strong" set is teal in both places and no set
 *     changes verdict because of a repaint.
 *  2. `backdrop-filter: blur(16px)` on the `.glass` nav has no portable
 *     Compose equivalent; the bar renders as a solid fill instead.
 */
object Tk {
    val bg = Color(0xFF0B0B12)
    val surface = Color(0xFF161626)
    val card = Color(0xFF1E1E32)
    val primary = Color(0xFF7C5DFA)
    val primaryLight = Color(0xFFA78BFA)
    val teal = Color(0xFF22D3A5)
    val amber = Color(0xFFF59E0B)
    val rose = Color(0xFFF43F5E)
    val ink = Color(0xFFF0EEFF)
    val muted = Color(0xFF7070A0)
    val border = Color(0xFF2A2A44)

    /** placeholder-[#3a3a58] / the locked badge's ground and label */
    val faint = Color(0xFF3A3A58)
    val locked = Color(0xFF1A1A26)

    // rgba(124,93,250,a) and friends, kept as alpha rather than pre-baked
    fun primaryA(alpha: Float) = primary.copy(alpha = alpha)
    fun amberA(alpha: Float) = amber.copy(alpha = alpha)
    fun tealA(alpha: Float) = teal.copy(alpha = alpha)
    fun inkA(alpha: Float) = ink.copy(alpha = alpha)
}

/** Barlow Condensed — the design's `.font-display`. */
val Display = FontFamily(
    Font(R.font.barlow_condensed_semibold, FontWeight.SemiBold),
    Font(R.font.barlow_condensed_bold, FontWeight.Bold),
    Font(R.font.barlow_condensed_black, FontWeight.Black),
)

/** JetBrains Mono — the design's `.font-mono-data`, which carries every
 *  eyebrow, count and timestamp. */
val MonoData = FontFamily(
    Font(R.font.jetbrains_mono_regular, FontWeight.Normal),
    Font(R.font.jetbrains_mono_medium, FontWeight.Medium),
    Font(R.font.jetbrains_mono_semibold, FontWeight.SemiBold),
)

private val trim = LineHeightStyle(
    alignment = LineHeightStyle.Alignment.Center,
    trim = LineHeightStyle.Trim.Both,
)
private val noPad = PlatformTextStyle(includeFontPadding = false)

/** `.font-display` + a Tailwind size/weight/leading/tracking stack. */
fun display(
    size: Int,
    weight: FontWeight = FontWeight.Black,
    line: Float = 1f,
    tracking: Float = 0f,
    color: Color = Tk.ink,
): TextStyle = TextStyle(
    fontFamily = Display,
    fontWeight = weight,
    fontSize = size.sp,
    lineHeight = (size * line).sp,
    letterSpacing = tracking.em,
    color = color,
    platformStyle = noPad,
    lineHeightStyle = trim,
)

/** `.font-mono-data`. Tabular by construction, so counts never jitter. */
fun mono(
    size: Int,
    tracking: Float = 0.05f,
    color: Color = Tk.muted,
    weight: FontWeight = FontWeight.Normal,
    line: Float = 1.3f,
): TextStyle = TextStyle(
    fontFamily = MonoData,
    fontWeight = weight,
    fontSize = size.sp,
    lineHeight = (size * line).sp,
    letterSpacing = tracking.em,
    color = color,
    platformStyle = noPad,
    lineHeightStyle = trim,
)

/** Inter — everything the design leaves in the body face. */
fun body(
    size: Int,
    color: Color = Tk.muted,
    line: Float = 1.45f,
    weight: FontWeight = FontWeight.Normal,
): TextStyle = TextStyle(
    fontFamily = Inter,
    fontWeight = weight,
    fontSize = size.sp,
    lineHeight = (size * line).sp,
    color = color,
    platformStyle = noPad,
    lineHeightStyle = trim,
)

/** The recurring stacks, named once so no screen re-derives them. */
object T {
    // eyebrows — mono, uppercase, wide
    val eyebrow = mono(10, 0.05f)                                  // tracking-wider
    val eyebrowWide = mono(10, 0.18f)                              // tracking-[0.18em]
    val eyebrowAccent = mono(10, 0.2f, Tk.primary)                 // step counters
    val eyebrowMission = mono(10, 0.15f, Tk.primary)
    val eyebrowTiny = mono(8, 0.05f)
    val eyebrowNine = mono(9, 0.05f)

    // display
    val name = display(38, FontWeight.Black, 1f, 0.02f)            // the greeting
    val headline = display(36, FontWeight.Black, 1.1f)             // onboarding steps
    val pageTitle = display(30, FontWeight.Black, 1f)              // PROGRESO / COACH
    val bigScore = display(36, FontWeight.Black, 1f)
    val streak = display(24, FontWeight.Black, 1.1f, color = Tk.amber)
    val cardHeadline = display(24, FontWeight.Black, 1f)
    val statValue = display(24, FontWeight.Black, 1f)
    val missionTitle = display(20, FontWeight.Bold, 1.1f, 0.025f)
    val button = display(20, FontWeight.Black, 1f, 0.1f, Color.White)
    val buttonSmall = display(18, FontWeight.Bold, 1f, 0.1f)
    val sectionTitle = display(18, FontWeight.Bold, 1.1f)
    val rowTitle = display(16, FontWeight.Bold, 1.1f)
    val rowTitleSmall = display(14, FontWeight.Bold, 1.1f)

    // body
    val bodyS = body(12)
    val bodyInk = body(12, Tk.ink)
    val note = body(11)
    val noteTiny = body(10)
    val noteNine = body(9)
    val lead = body(14, Tk.muted, 1.6f)
    val itemTitle = body(14, Tk.ink, 1.3f, FontWeight.SemiBold)
    val itemTitleSmall = body(12, Tk.ink, 1.3f, FontWeight.SemiBold)
}

/**
 * The colour a band wears. barra's bands, the design's palette.
 *
 * `unmeasured` is deliberately the muted grey and never a score colour: a rep
 * the pose model could not read is not a bad rep, and painting it rose would
 * say it was.
 */
fun bandInk(band: String): Color = when (band) {
    "strong" -> Tk.teal
    "solid" -> Tk.primary
    "shaky" -> Tk.amber
    "broken", "broken down" -> Tk.rose
    else -> Tk.muted
}

/** The band a score falls in, by barra's own boundaries. */
fun bandOf(score: Int?): String = when {
    score == null -> "unmeasured"
    score >= com.barrapp.Progression.STRONG -> "strong"
    score >= com.barrapp.Progression.SOLID -> "solid"
    score >= com.barrapp.Progression.SHAKY -> "shaky"
    else -> "broken"
}

fun scoreInk(score: Int?): Color = bandInk(bandOf(score))

/** The design's `scoreLabel`, in barra's bands and the app's language. */
fun scoreLabel(score: Int?): String = when (bandOf(score)) {
    "strong" -> "Fuerte"
    "solid" -> "Sólido"
    "shaky" -> "Inestable"
    "broken" -> "Se rompió"
    else -> "Sin medir"
}
