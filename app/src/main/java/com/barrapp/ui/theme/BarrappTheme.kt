package com.barrapp.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.PlatformTextStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.LineHeightStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import com.barrapp.R

/**
 * Nocturne, ported literally from the browser prototype.
 *
 * Every colour, size, line-height, letter-spacing and dash pattern here is a
 * value from the design, already resolved. Nothing is rounded, harmonised or
 * reinterpreted; odd values (9dp gaps, 2.6 strokes, 46x42 buttons) are the
 * design's own and stay.
 *
 * The one declared platform gap: the nav bar's `backdrop-filter: blur(12px)`
 * has no portable Compose equivalent, so the bar renders as a solid
 * #232532 at 0.92 alpha instead of a true backdrop blur.
 */
object Nocturne {
    val background = Color(0xFF161826)
    val surface = Color(0xFF232532)
    val dim = Color(0xFF292B31)
    val hairline = Color(0xFF3F424D)
    val accent = Color(0xFF9184D9)
    val accentDeep = Color(0xFF5D5294)
    val accentText = Color(0xFFD2CEFD)
    val fg = Color(0xFFE9E9ED)

    // measurement encoding — how the rep went; never the accent
    val strong = Color(0xFF62C097)
    val solid = Color(0xFF74B4DE)
    val shaky = Color(0xFFD4A257)
    val nothing = Color(0xFF595D6C)

    val deep = Color(0xFF423A6A)          // earned chip / user bubble ground
    val onDeep = Color(0xFFF5F4FF)
    val muted = Color(0xFF9397AB)         // unmeasured chip text

    // rgba(233,233,237, a) — kept as alpha multiplications, never pre-baked
    fun fgA(alpha: Float) = fg.copy(alpha = alpha)

    val navFill = surface.copy(alpha = 0.92f)   // the declared backdrop-gap stand-in
    val dropShadow = Color(0, 0, 0, 140)        // 0 10px 30px rgba(0,0,0,.55)
}

/** Inter, weights 400/500/600, bundled — never a substitution. */
val Inter = FontFamily(
    Font(R.font.inter_regular, FontWeight.Normal),      // 400
    Font(R.font.inter_medium, FontWeight.Medium),       // 500
    Font(R.font.inter_semibold, FontWeight.SemiBold),   // 600
)

private val lineHeightTrim = LineHeightStyle(
    alignment = LineHeightStyle.Alignment.Center,
    trim = LineHeightStyle.Trim.Both,
)

private val platform = PlatformTextStyle(includeFontPadding = false)

/**
 * `font: <weight> <size>/<factor> Inter` made explicit. lineHeight is always
 * set (size * factor), font padding is trimmed, letter-spacing stays in em,
 * and `tnum` turns on the design's tabular numerals.
 */
fun nocturne(
    weight: Int,
    size: Int,
    lineFactor: Float,
    letterSpacing: TextUnit = 0.em,
    tnum: Boolean = false,
    align: TextAlign = TextAlign.Start,
): TextStyle = TextStyle(
    fontFamily = Inter,
    fontWeight = when (weight) {
        500 -> FontWeight.Medium
        600 -> FontWeight.SemiBold
        else -> FontWeight.Normal
    },
    fontSize = size.sp,
    lineHeight = (size * lineFactor).sp,
    letterSpacing = letterSpacing,
    fontFeatureSettings = if (tnum) "tnum" else null,
    textAlign = align,
    platformStyle = platform,
    lineHeightStyle = lineHeightTrim,
)

// The recurring one-off styles, named so no screen re-derives them.
object N {
    val logo = nocturne(500, 15, 1.2f, (-0.01).em)
    val subtitle = nocturne(400, 11, 1.4f).copy(color = Nocturne.fgA(0.55f))
    val eyebrowAccent = nocturne(500, 11, 1f, 0.1.em).copy(color = Nocturne.accent)
    val eyebrowMuted = nocturne(500, 10, 1f, 0.1.em).copy(color = Nocturne.fgA(0.45f))
    val bigNumber = nocturne(600, 46, 1f, (-0.03).em, tnum = true)
    val caption = nocturne(400, 13, 1.5f).copy(color = Nocturne.fgA(0.6f))
    val captionPlain = nocturne(400, 13, 1.5f)
    val chip = nocturne(500, 11, 1f, tnum = true).copy(color = Nocturne.accentText)
    val dayLetter = nocturne(400, 10, 1f).copy(color = Nocturne.fgA(0.45f))
    val legend = nocturne(400, 10, 1.4f).copy(color = Nocturne.fgA(0.45f))
    val cardTitle = nocturne(500, 20, 1.2f, (-0.02).em)
    val cardBody = nocturne(400, 12, 1.5f).copy(color = Nocturne.fgA(0.6f))
    val sessionMeta = nocturne(400, 11, 1f, tnum = true).copy(color = Nocturne.fgA(0.4f))
    val pageTitle = nocturne(500, 22, 1.2f, (-0.02).em)
    val pageTitleMuted = nocturne(400, 12, 1f, tnum = true).copy(color = Nocturne.fgA(0.45f))
    val bodyNote = nocturne(400, 12, 1.5f).copy(color = Nocturne.fgA(0.55f))
    val back = nocturne(500, 12, 1f).copy(color = Nocturne.accent)
    val cellDay = nocturne(400, 12, 1f, tnum = true).copy(color = Nocturne.fgA(0.3f))
    val cellDayMeasured = nocturne(500, 12, 1f, tnum = true).copy(color = Nocturne.fg)
    val listTitle = nocturne(500, 13, 1.3f)
    val listSub = nocturne(400, 11, 1.4f).copy(color = Nocturne.fgA(0.5f))
    val listScore = nocturne(600, 16, 1f, tnum = true)
    val verdict = nocturne(500, 26, 1.15f, (-0.025).em)
    val ringNumber = nocturne(600, 18, 1f, tnum = true)
    val ringBig = nocturne(600, 26, 1f, tnum = true)
    val ringLabel = nocturne(400, 9, 1f).copy(color = Nocturne.fgA(0.45f))
    val cue = nocturne(400, 13, 1.4f)
    val cueNumber = nocturne(600, 13, 1.4f, tnum = true).copy(color = Nocturne.accentDeep)
    val button = nocturne(500, 13, 1f)
    val repTitle = nocturne(500, 13, 1f)
    val repTimes = nocturne(400, 10, 1f, tnum = true).copy(color = Nocturne.fgA(0.4f))
    val repScore = nocturne(600, 15, 1f, tnum = true)
    val barLabel = nocturne(400, 11, 1f)
    val barWeight = nocturne(400, 11, 1f).copy(color = Nocturne.fgA(0.4f))
    val barValue = nocturne(400, 11, 1f, tnum = true).copy(color = Nocturne.fgA(0.6f))
    val asideRow = nocturne(400, 11, 1.6f)
    val asideValue = nocturne(400, 11, 1.6f, tnum = true).copy(color = Nocturne.fgA(0.6f))
    val runLine = nocturne(400, 10, 1.4f, tnum = true).copy(color = Nocturne.fgA(0.35f))
    val stageTitle = nocturne(500, 13, 1.3f)
    val stageSub = nocturne(400, 11, 1.5f).copy(color = Nocturne.fgA(0.5f))
    val bubble = nocturne(400, 13, 1.5f)
    val bubbleLabel = nocturne(500, 9, 1f, 0.1.em).copy(color = Nocturne.accent)
    val bubbleNote = nocturne(400, 11, 1.5f).copy(color = Nocturne.fgA(0.5f))
    val input = nocturne(400, 13, 1f).copy(color = Nocturne.fgA(0.4f))
    val send = nocturne(500, 14, 1f).copy(color = Nocturne.accentText)
    val chipTry = nocturne(400, 12, 1f).copy(color = Nocturne.accentText)
    val headerButton = nocturne(500, 12, 1f).copy(color = Nocturne.accentText)
    val monthCell = nocturne(500, 13, 1f)
    val navLabel = nocturne(500, 9, 1f, 0.04.em)
    val question = nocturne(400, 13, 1.4f).copy(color = Nocturne.fgA(0.75f))
    val notePlain = nocturne(400, 11, 1.5f).copy(color = Nocturne.fgA(0.55f))
    val evidenceBold = nocturne(500, 11, 1.5f).copy(color = Nocturne.fg)
    val stepTitle = nocturne(500, 14, 1.2f)
    val stepTitleBig = nocturne(500, 17, 1.2f, (-0.01).em)
    val stepNote = nocturne(400, 11, 1.5f).copy(color = Nocturne.fgA(0.55f))
    val stepCount = nocturne(500, 12, 1f, tnum = true).copy(color = Nocturne.accentText)
}

/** Material stays only because the legacy screens still read it; the Nocturne
 *  screens draw everything themselves. Every role is Nocturne now. */
@Composable
fun BarrappTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Nocturne.accent,
            onPrimary = Nocturne.background,
            primaryContainer = Nocturne.deep,
            onPrimaryContainer = Nocturne.onDeep,
            secondary = Nocturne.accentDeep,
            background = Nocturne.background,
            onBackground = Nocturne.fg,
            surface = Nocturne.surface,
            onSurface = Nocturne.fg,
            surfaceVariant = Nocturne.surface,
            onSurfaceVariant = Nocturne.fgA(0.6f),
            outline = Nocturne.hairline,
            error = Nocturne.shaky,
        ),
        typography = BarrappTypography,
    ) { content() }
}

/** Kept for the legacy screens that read band colours through this local. */
val LocalBandColors = staticCompositionLocalOf { LightBands }
