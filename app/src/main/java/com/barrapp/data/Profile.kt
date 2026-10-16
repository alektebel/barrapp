package com.barrapp.data

/**
 * What the athlete told us about themselves, kept on the phone.
 *
 * Age and activity level are asked once because they change how the app talks
 * to you, not what it measures. Nothing here is sent to the server: the
 * measurement is self-referential, so a population norm for a 34-year-old
 * would be noise at best and misleading at worst. The name is used to address
 * you and for nothing else.
 */
data class Profile(
    val name: String = "",
    val age: Int = 0,
    val activity: ActivityLevel = ActivityLevel.Unset,
) {
    /**
     * Enough to open the app.
     *
     * Age used to be required. The redesigned intake does not ask for it —
     * nothing in the measurement reads it, and the one thing that shapes the
     * app, how often you train, is asked directly. It stays on the model
     * because the objectives chat can still capture it, but a profile without
     * it is complete.
     */
    val complete: Boolean
        get() = name.isNotBlank() && activity != ActivityLevel.Unset

    val firstName: String
        get() = name.trim().substringBefore(' ').ifBlank { "there" }

    /** How many reps a session should aim for, given how much they train.
     *  Three is the floor for any comparison at all; more experience means
     *  more reps are realistic, not that fewer would do. */
    val repTarget: Int
        get() = when (activity) {
            ActivityLevel.Unset -> 5
            ActivityLevel.New -> 3
            ActivityLevel.Occasional -> 4
            ActivityLevel.Regular -> 5
            ActivityLevel.Daily -> 6
        }
}

enum class ActivityLevel(val label: String, val detail: String) {
    Unset("", ""),
    New("Estoy empezando", "Nuevo en el entrenamiento, o volviendo tras un parón"),
    Occasional("Una o dos veces por semana", "Se entrena, pero sin un horario fijo"),
    Regular("Tres o cuatro veces por semana", "Una rutina que casi siempre cumples"),
    Daily("Cinco o más veces por semana", "Entrenar forma parte de casi todos los días"),
}
