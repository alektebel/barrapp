package com.barrapp.ui.tracker

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.barrapp.data.ActivityLevel
import com.barrapp.ui.theme.T
import com.barrapp.ui.theme.Tk
import com.barrapp.ui.theme.body
import com.barrapp.ui.theme.display
import com.barrapp.ui.theme.mono

/** What the onboarding collects, in the app's own vocabulary. */
data class OnboardingResult(
    val name: String,
    /** A ladder movement key: pull_up, push_up, dip, muscle_up, squat, knee_raise. */
    val focusExercise: String,
    val goal: String,
    val activity: ActivityLevel,
)

private data class Option(val value: String, val label: String, val sub: String = "")

/** Only movements barra can actually measure are offered. Offering an L-sit
 *  here would promise a verdict the pipeline cannot give. */
private val EXERCISES = listOf(
    Option("pull_up", "Dominada", "El movimiento de tirón de referencia"),
    Option("push_up", "Flexión", "El empuje que abre la escalera"),
    Option("dip", "Fondo", "Empuje vertical, recorrido largo"),
    Option("muscle_up", "Muscle-up", "Tirón y fondo en un solo movimiento"),
    Option("squat", "Sentadilla", "Tren inferior, patrón de bisagra"),
    Option("bulgarian_split_squat", "Sentadilla búlgara",
        "Tren inferior, una pierna retrasada"),
    Option("split_squat", "Split squat", "Tren inferior, zancada estática"),
    Option("knee_raise", "Elevación de rodillas", "Core colgado de la barra"),
)

private val GOALS = listOf(
    Option("Perfeccionar la técnica", "Perfeccionar técnica",
        "Cada rep más limpia que la anterior"),
    Option("Ganar fuerza", "Ganar fuerza",
        "Más reps, mejor calidad, semana a semana"),
    Option("Competir", "Competir",
        "Llevar el rendimiento al límite"),
)

/**
 * The design's fourth step asks for a skill level. This app has no use for
 * one — what it actually reads is how often you train, because that is what
 * sets the rep target a set is compared against. So the step keeps the
 * design's shape and asks the question the app will really use, rather than
 * collecting a self-rating and quietly ignoring it.
 */
private val LEVELS = ActivityLevel.entries.filter { it != ActivityLevel.Unset }.map {
    when (it) {
        ActivityLevel.New -> Option("New", "Estoy empezando",
            "Nuevo en esto, o volviendo tras un parón")
        ActivityLevel.Occasional -> Option("Occasional", "Una o dos veces por semana",
            "Entreno, pero sin calendario fijo")
        ActivityLevel.Regular -> Option("Regular", "Tres o cuatro veces por semana",
            "Una rutina que más o menos cumplo")
        ActivityLevel.Daily -> Option("Daily", "Cinco o más veces por semana",
            "Entrenar es parte de casi todos los días")
        else -> Option("", "", "")
    }
}

/**
 * The four-step intake, then the briefing.
 *
 * Faithful to the mockup step for step: the dots, the choice cards with their
 * scale-up on selection, the display-face headings, and the briefing card that
 * says what the app will and will not do.
 */
@Composable
fun TrackerOnboarding(
    initialName: String = "",
    onComplete: (OnboardingResult) -> Unit,
    modifier: Modifier = Modifier,
) {
    var step by remember { mutableIntStateOf(0) }
    var name by remember { mutableStateOf(initialName) }
    var exercise by remember { mutableStateOf("") }
    var goal by remember { mutableStateOf("") }
    var level by remember { mutableStateOf("") }
    var briefing by remember { mutableStateOf(false) }

    val canNext = when (step) {
        0 -> name.isNotBlank()
        1 -> exercise.isNotBlank()
        2 -> goal.isNotBlank()
        else -> level.isNotBlank()
    }

    fun finish() = onComplete(
        OnboardingResult(
            name = name.trim(),
            focusExercise = exercise,
            goal = goal,
            activity = ActivityLevel.entries.firstOrNull { it.name == level } ?: ActivityLevel.Unset,
        )
    )

    if (briefing) {
        Briefing(
            name = name.trim(),
            exercise = EXERCISES.first { it.value == exercise }.label,
            goal = GOALS.first { it.value == goal }.label,
            onStart = ::finish,
            modifier = modifier,
        )
        return
    }

    Column(
        modifier
            .fillMaxSize()
            .background(Tk.bg)
            .padding(horizontal = 24.dp),
    ) {
        Spacer(Modifier.height(40.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier
                    .size(32.dp)
                    .clip(ChipShape)
                    .background(Tk.primaryA(0.2f))
                    .border(1.dp, Tk.primaryA(0.4f), ChipShape),
                contentAlignment = Alignment.Center,
            ) {
                Canvas(Modifier.size(16.dp)) { drawLogoMark() }
            }
            Spacer(Modifier.width(8.dp))
            Text("BARRAPP", style = display(20, androidx.compose.ui.text.font.FontWeight.Black, 1f, 0.05f))
        }
        Spacer(Modifier.height(40.dp))
        ProgressDots(step, 4)
        Spacer(Modifier.height(32.dp))

        Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
            Text("PASO ${step + 1} DE 4", style = T.eyebrowAccent)
            Spacer(Modifier.height(12.dp))
            when (step) {
                0 -> {
                    Heading("¿CÓMO TE\nLLAMAMOS?")
                    Text(
                        "Tu nombre aparece en tus logros. No sale del teléfono.",
                        style = T.lead,
                    )
                    Spacer(Modifier.height(32.dp))
                    NameField(name) { name = it }
                }
                1 -> {
                    Heading("TU MOVIMIENTO\nPRINCIPAL")
                    Text("El coach ajustará el análisis a este ejercicio.", style = T.lead)
                    Spacer(Modifier.height(24.dp))
                    EXERCISES.forEach { o ->
                        ChoiceCard(o.label, o.sub, exercise == o.value) { exercise = o.value }
                    }
                }
                2 -> {
                    Heading("¿QUÉ QUIERES\nCONSEGUIR?")
                    Text("Define tu objetivo ahora. Puedes cambiarlo más adelante.", style = T.lead)
                    Spacer(Modifier.height(24.dp))
                    GOALS.forEach { o ->
                        ChoiceCard(o.label, o.sub, goal == o.value) { goal = o.value }
                    }
                }
                else -> {
                    Heading("CON QUÉ\nFRECUENCIA")
                    Text(
                        "Sé honesto — solo sirve para calibrar cuántas reps pedirle a una serie.",
                        style = T.lead,
                    )
                    Spacer(Modifier.height(24.dp))
                    LEVELS.forEach { o ->
                        ChoiceCard(o.label, o.sub, level == o.value) { level = o.value }
                    }
                }
            }
            Spacer(Modifier.height(16.dp))
        }

        Column(Modifier.padding(bottom = 32.dp)) {
            TkPrimaryButton(
                if (step < 3) "Siguiente" else "Ver mi misión",
                onClick = { if (step < 3) step++ else briefing = true },
                enabled = canNext,
            )
        }
    }
}

@Composable
private fun Heading(text: String) {
    Text(text, style = T.headline)
    Spacer(Modifier.height(8.dp))
}

@Composable
private fun ProgressDots(step: Int, total: Int) {
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        repeat(total) { i ->
            Box(
                Modifier
                    .width(if (i == step) 20.dp else 6.dp)
                    .height(6.dp)
                    .clip(RoundedCornerShape(3.dp))
                    .background(if (i <= step) Tk.primary else Tk.border),
            )
        }
    }
}

@Composable
private fun NameField(value: String, onValue: (String) -> Unit) {
    Box(
        Modifier
            .fillMaxWidth()
            .clip(CardShape)
            .background(Tk.surface)
            .border(1.5.dp, if (value.isBlank()) Tk.border else Tk.primary, CardShape)
            .padding(horizontal = 16.dp, vertical = 14.dp),
    ) {
        BasicTextField(
            value = value,
            onValueChange = { onValue(it.take(24)) },
            textStyle = display(24, androidx.compose.ui.text.font.FontWeight.Bold, 1.1f, 0.02f),
            cursorBrush = SolidColor(Tk.primary),
            singleLine = true,
            keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                imeAction = ImeAction.Done,
            ),
            modifier = Modifier.fillMaxWidth(),
            decorationBox = { inner ->
                if (value.isBlank()) {
                    Text(
                        "TU NOMBRE…",
                        style = display(24, androidx.compose.ui.text.font.FontWeight.Bold,
                            1.1f, 0.02f, Tk.faint),
                    )
                }
                inner()
            },
        )
    }
}

@Composable
private fun ChoiceCard(label: String, sub: String, selected: Boolean, onClick: () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .padding(bottom = 12.dp)
            .clip(CardShape)
            .background(if (selected) Tk.primaryA(0.18f) else Tk.surface)
            .border(1.5.dp, if (selected) Tk.primary else Tk.border, CardShape)
            .noRipple(onClick)
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(label.uppercase(), style = T.sectionTitle)
            if (sub.isNotBlank()) {
                Text(sub, style = T.bodyS, modifier = Modifier.padding(top = 2.dp))
            }
        }
        Box(
            Modifier
                .size(20.dp)
                .clip(CircleShape)
                .background(if (selected) Tk.primary else Color.Transparent)
                .border(2.dp, if (selected) Tk.primary else Tk.border, CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            if (selected) {
                Canvas(Modifier.size(10.dp)) { drawCheck(Color.White) }
            }
        }
    }
}

@Composable
private fun Briefing(
    name: String,
    exercise: String,
    goal: String,
    onStart: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier
            .fillMaxSize()
            .background(Tk.bg)
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Spacer(Modifier.height(64.dp))
        Box(
            Modifier
                .size(80.dp)
                .clip(RoundedCornerShape(24.dp))
                .background(Tk.primaryA(0.15f))
                .border(1.5.dp, Tk.primaryA(0.4f), RoundedCornerShape(24.dp)),
            contentAlignment = Alignment.Center,
        ) {
            Text("🎯", style = body(34, Tk.ink))
        }
        Spacer(Modifier.height(24.dp))
        Text("MISIÓN ASIGNADA", style = mono(10, 0.2f, Tk.primary))
        Spacer(Modifier.height(12.dp))
        Text(
            "BIENVENIDO,\n${name.uppercase()}",
            style = T.headline,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(8.dp))
        Text(
            "Ejercicio principal: $exercise",
            style = body(14, Tk.primaryLight),
            textAlign = TextAlign.Center,
        )
        Text(
            "Objetivo: $goal",
            style = body(14, Tk.primaryLight),
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(32.dp))
        TkCard {
            Text(
                "BarrApp mide cada rep que filmes y te dice qué ha pasado: recorrido, " +
                    "control, tempo. Compara tus reps con las tuyas de antes, nunca con " +
                    "las de otro, y cuando no puede medir algo lo dice en vez de " +
                    "inventárselo.",
                style = T.bodyS,
            )
        }
        Spacer(Modifier.height(32.dp))
        TkPrimaryButton("Empezar a entrenar", onStart)
        Spacer(Modifier.height(48.dp))
    }
}
