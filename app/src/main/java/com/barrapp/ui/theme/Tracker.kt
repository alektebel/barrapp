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
 * Tiza: the app's design system (design file "Barrapp Tiza", turnos 2 y 3).
 *
 * Chalk-paper ground, ink lines and one loud colour. Its rules, kept here so
 * every screen inherits them instead of re-deciding:
 *
 *  - Archivo Black for headlines, IBM Plex Mono for data, Archivo for text.
 *  - Every card and control has a 2px ink border.
 *  - A hard shadow (0 4px 0 ink) only on the screen's one main action.
 *  - Orange only for what asks for action. A score is never orange.
 *  - Score bands keep barra's own cuts (73/47/20); the design's palette wears
 *    them: strong green, solid blue, shaky amber, broken red.
 *
 * The token names are the previous design's, so every screen re-skins without
 * a rename: `primary` is now the action orange, `teal` the "correct" green.
 */
object Tk {
    val bg = Color(0xFFF1EEE6)          // chalk paper
    val surface = Color(0xFFFFFFFF)     // cards
    val card = Color(0xFFF1EEE6)        // insets inside a card
    val primary = Color(0xFFFF4F1A)     // action orange
    val primaryLight = Color(0xFFFF6A3D)
    val teal = Color(0xFF1E9E63)        // correct / strong
    val blue = Color(0xFF2F6BFF)        // solid band
    val amber = Color(0xFFE39A00)       // shaky band, warnings
    val rose = Color(0xFFD7263D)        // broken band, errors
    val ink = Color(0xFF141414)
    val muted = Color(0xFF5A564E)
    val border = Color(0xFF141414)
    /** Hairlines and tracks that should not read as a border. */
    val line = Color(0xFFD6D0C2)
    /** Video surfaces: the frame behind a clip and its overlays. */
    val dark = Color(0xFF24221E)
    val darkLine = Color(0xFF3A3730)
    /** The paper colour used as text on ink. */
    val onInk = Color(0xFFF1EEE6)
    val orangeSoft = Color(0xFFFFE3D6)

    val faint = Color(0xFFB5AFA2)
    val locked = Color(0xFFDCD7CB)

    fun primaryA(alpha: Float) = primary.copy(alpha = alpha)
    fun amberA(alpha: Float) = amber.copy(alpha = alpha)
    fun tealA(alpha: Float) = teal.copy(alpha = alpha)
    fun inkA(alpha: Float) = ink.copy(alpha = alpha)
}

/** Archivo Black — headlines. One weight; every weight maps to it. */
val Display = FontFamily(
    Font(R.font.archivo_black, FontWeight.SemiBold),
    Font(R.font.archivo_black, FontWeight.Bold),
    Font(R.font.archivo_black, FontWeight.Black),
)

/** IBM Plex Mono — every eyebrow, count, time and measured value. */
val MonoData = FontFamily(
    Font(R.font.ibm_plex_mono_regular, FontWeight.Normal),
    Font(R.font.ibm_plex_mono_medium, FontWeight.Medium),
    Font(R.font.ibm_plex_mono_semibold, FontWeight.SemiBold),
)

/** Archivo — running text. */
val BodyFace = FontFamily(
    Font(R.font.archivo_regular, FontWeight.Normal),
    Font(R.font.archivo_medium, FontWeight.Medium),
    Font(R.font.archivo_semibold, FontWeight.SemiBold),
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

/** Archivo — everything that is not a headline or a number. */
fun body(
    size: Int,
    color: Color = Tk.muted,
    line: Float = 1.45f,
    weight: FontWeight = FontWeight.Normal,
): TextStyle = TextStyle(
    fontFamily = BodyFace,
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
    val eyebrowAccent = mono(10, 0.2f, Tk.ink, FontWeight.SemiBold) // step counters
    val eyebrowMission = mono(12, 0.12f, Tk.ink, FontWeight.SemiBold)
    val eyebrowTiny = mono(8, 0.05f)
    val eyebrowNine = mono(9, 0.05f)

    // display
    val name = display(38, FontWeight.Black, 1f, 0.02f)            // the greeting
    val headline = display(36, FontWeight.Black, 1.1f)             // onboarding steps
    val pageTitle = display(30, FontWeight.Black, 1f)              // PROGRESO / COACH
    val bigScore = display(36, FontWeight.Black, 1f)
    val streak = display(24, FontWeight.Black, 1.1f)
    val cardHeadline = display(24, FontWeight.Black, 1f)
    val statValue = display(24, FontWeight.Black, 1f)
    val missionTitle = display(20, FontWeight.Bold, 1.1f, 0.025f)
    val button = display(17, FontWeight.Black, 1f, 0.04f, Tk.onInk)
    val buttonSmall = mono(13, 0.02f, Tk.ink, FontWeight.SemiBold)
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
    "solid" -> Tk.blue
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
    "solid" -> "Sólida"
    "shaky" -> "Inestable"
    "broken" -> "Se rompió"
    else -> "Sin medir"
}
