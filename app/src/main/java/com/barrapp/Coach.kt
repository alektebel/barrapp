package com.barrapp

import com.barrapp.data.DayEntry
import com.barrapp.data.Profile
import kotlin.math.abs

/**
 * Answers built from the measurements already on the phone.
 *
 * Deliberately not a language model call. Every sentence here is arithmetic
 * over the user's own sessions, which means the coach physically cannot invent
 * a PR, a trend, or a technique diagnosis - the failure mode a chat feature in a
 * measurement app is most likely to have, and the most damaging one.
 *
 * The server's prose model still writes the per-clip read-out, where the payload
 * it is given bounds what it can say. This is the conversational surface, and it
 * answers "how do you know that?" with the number it used.
 *
 * When a question is outside what the data supports, it says so and offers the
 * question it can answer instead. That is a better experience than a fluent
 * paragraph that happens to be fiction.
 */
object Coach {

    private const val FLOOR = 3

    /** Takes the measurements and the profile, not the UI state: the answers
     *  are arithmetic over training, and nothing here should depend on which
     *  screen happens to be open. It also makes this the one part of the app
     *  that can be type-checked without the Compose toolchain. */
    fun answer(question: String, allDays: List<DayEntry>, profile: Profile): String {
        val q = question.lowercase()
        val days = allDays.sortedBy { it.date }
        val name = profile.firstName

        if (days.isEmpty()) {
            return "Todavía no se ha medido nada, así que no hay nada que pueda decirte que " +
                "sea verdad. Añade un clip de una serie y tendré con qué trabajar."
        }

        return when {
            q.containsAny("better", "progress", "improving", "improve", "trend", "noise",
                "mejor", "progres", "tendencia", "ruido") ->
                progress(days)

            q.containsAny("last session", "last one", "latest", "yesterday", "today", "show",
                "última sesión", "ultima sesion", "última", "ayer", "hoy", "mostr", "muestr") ->
                lastSession(days)

            q.containsAny("no score", "not scored", "unmeasured", "why is", "rejected", "missing",
                "sin puntuación", "sin puntuacion", "sin medir", "por qué", "por que",
                "rechazad", "falta") ->
                whyUnscored()

            q.containsAny("film", "record", "camera", "phone", "angle", "next one",
                "grab", "cámara", "camara", "teléfono", "telefono", "ángulo", "angulo",
                "siguiente") ->
                filming(profile.repTarget)

            q.containsAny("score", "quality", "number", "mean",
                "puntuación", "puntuacion", "calidad", "número", "numero", "significa") ->
                whatTheScoreIs()

            q.containsAny("how many", "reps", "volume", "count",
                "cuántas", "cuantas", "repeticiones", "volumen", "cuenta") ->
                volume(days)

            else -> fallback(name, days)
        }
    }

    /** The questions offered as chips. Each one is worded so [answer] routes it
     *  to the branch its question is about; LogicTest pins that. */
    fun suggestions(dayCount: Int): List<String> = buildList {
        add("¿Qué mostró realmente mi última sesión?")
        if (dayCount >= 2) add("¿Estoy mejorando de verdad o es sólo ruido?")
        add("¿Por qué algunas repeticiones no tienen puntuación?")
        add("¿Cómo debería grabar la siguiente?")
    }

    private fun progress(days: List<DayEntry>): String {
        val comparable = days.filter { it.reps >= FLOOR }
        if (comparable.size < 2) {
            val have = comparable.size
            return "Todavía no, y prefiero decirlo a adivinar. Para comparar dos sesiones hace " +
                "falta que cada una tenga al menos $FLOOR repeticiones medidas; si no, la " +
                "mediana de la sesión es una o dos repeticiones y no hay forma de separar " +
                "cuánto varías de una repetición a otra de un cambio real. Tienes $have " +
                "sesion" + (if (have == 1) "" else "es") + " por encima de ese mínimo."
        }
        val measured = comparable.filter { it.measured }
        if (measured.size < 2) {
            return "Tienes ${comparable.size} sesiones con repeticiones suficientes, pero menos " +
                "de dos produjeron una puntuación. Normalmente es un problema de grabación " +
                "y no de entrenamiento: pregúntame cómo grabar la siguiente."
        }
        val first = measured.first()
        val last = measured.last()
        val delta = (last.score ?: 0) - (first.score ?: 0)
        val direction = if (delta > 0) "sube" else "baja"
        return if (abs(delta) < 8) {
            "Plano, dentro de la resolución que tiene esto. La puntuación base pasó de " +
                "${first.score} el ${shortDateEs(first.date)} a ${last.score} el ${shortDateEs(last.date)}, y una " +
                "diferencia tan pequeña queda dentro del ruido de una medida construida con " +
                "tres componentes acotados. Estable es una respuesta real, no una evasiva."
        } else {
            "La puntuación base $direction ${abs(delta)} puntos, de ${first.score} el " +
                "${shortDateEs(first.date)} a ${last.score} el ${shortDateEs(last.date)}, en ${measured.size} sesiones " +
                "medidas. Merece una mirada. No es una prueba: ese número no tiene una " +
                "distribución nula detrás, así que no se ha contrastado con tu propia " +
                "variación entre repeticiones."
        }
    }

    private fun lastSession(days: List<DayEntry>): String {
        val day = days.last()
        // The last CLIP, not the day's total: a day can hold a muscle-up and
        // a push-up set, and adding them answers about neither.
        val job = day.last
        val movement = movementEs(job?.exercise ?: day.exercise, job?.label ?: day.exerciseLabel)
        val reps = job?.reps ?: day.reps
        val judged = job?.verified ?: day.verifiedReps
        val score = if (job != null) job.score else day.score
        val band = if (job != null) bandOf(score) else day.band
        val head = "${shortDateEs(day.date)}: $movement, " +
            "$reps repetici${if (reps == 1) "ón contada" else "ones contadas"}"
        return when {
            reps == 0 -> "${shortDateEs(day.date)}: $movement, no se contó ninguna repetición."
            judged == 0 || score == null ->
                "$head, sin puntuar. Se contaron pero ninguna se pudo juzgar: abre la sesión " +
                    "y el motivo está escrito en cada una."
            else ->
                "$head, $judged juzgada${if (judged == 1) "" else "s"}; puntuación base " +
                    "$score (${bandEs(band)}). " +
                    if (judged >= FLOOR)
                        "Son repeticiones suficientes para que la sesión entre en una comparación."
                    else
                        "Está por debajo del mínimo de $FLOOR repeticiones, así que todavía no " +
                            "se puede comparar con otra sesión."
        }
    }

    private fun bandOf(score: Int?): String = when {
        score == null -> "unmeasured"
        score >= Progression.STRONG -> "strong"
        score >= Progression.SOLID -> "solid"
        score >= Progression.SHAKY -> "shaky"
        else -> "broken down"
    }

    internal fun bandEs(band: String): String = when (band.lowercase()) {
        "strong" -> "fuerte"
        "solid" -> "sólido"
        "shaky" -> "inestable"
        "broken", "broken down" -> "se rompió"
        "unmeasured", "" -> "sin medir"
        else -> band
    }

    private fun whyUnscored(): String =
        "Una repetición se queda sin puntuación cuando la estimación de la pose no es " +
            "físicamente posible o se siguió muy poco de ella. La causa más común es estar " +
            "demasiado lejos de la cámara: el estimador devuelve disparates con seguridad en " +
            "lugar de admitir que no te ve. Se muestra como un guion largo y no como una " +
            "puntuación baja a propósito: un fallo de grabación no es mala técnica, y marcarlo " +
            "como tal sería lo más engañoso que esta app podría hacer."

    private fun filming(target: Int): String =
        "Cinco cosas, en el orden en que te cuestan:\n\n" +
            "1. Llena el encuadre y mantén en él la parte alta de la repetición. Una " +
            "repetición cuyo cambio de sentido no se ve se descarta entera.\n" +
            "2. Teléfono en trípode, con la posición marcada en el suelo. Una cámara que se " +
            "mueve unos grados entre sesiones desplaza la medida más que un cambio real de " +
            "técnica.\n" +
            "3. El mismo lado en cada sesión. De frente y por detrás son imágenes especulares " +
            "y no se pueden juntar.\n" +
            "4. $target repeticiones en una serie, por encima del mínimo de $FLOOR con margen.\n" +
            "5. Empieza a grabar al estirarte hacia arriba y para cuando te sueltes."

    private fun whatTheScoreIs(): String =
        "Es una puntuación base, no una nota de técnica. Tiene tres partes: cuánto del " +
            "recorrido que permite la longitud de tu brazo has usado (40 %), si la bajada fue " +
            "controlada o se dejó caer (25 %) y si la subida se atascó (35 %). Abre cualquier " +
            "repetición y verás las tres con sus propios números.\n\n" +
            "El balanceo y la asimetría izquierda-derecha se miden pero se dejan fuera a " +
            "propósito. Son horizontales, así que incluirlos haría que el número dependiera " +
            "de dónde pusiste el teléfono."

    private fun volume(days: List<DayEntry>): String {
        val total = days.sumOf { it.reps }
        val judged = days.sumOf { it.verifiedReps }
        val ready = days.count { it.verifiedReps >= FLOOR }
        return "$total repetici${if (total == 1) "ón contada" else "ones contadas"} en " +
            "${days.size} día${if (days.size == 1) "" else "s"}, $judged con puntuación. " +
            "$ready de esos días llegaron al mínimo de $FLOOR repeticiones puntuadas que " +
            "necesita una comparación."
    }

    private fun fallback(name: String, days: List<DayEntry>): String =
        "Sólo respondo con lo que se ha medido, $name, y no lo veo en tus " +
            "${days.size} sesion${if (days.size == 1) "" else "es"} registrada${if (days.size == 1) "" else "s"}. " +
            "Puedo responder: qué mostró tu última sesión, si un cambio es real o ruido, por " +
            "qué una repetición no tiene puntuación, de qué se compone la puntuación y cómo " +
            "grabar la siguiente."

    private fun String.containsAny(vararg needles: String): Boolean =
        needles.any { this.contains(it) }
}

private val MONTHS_ES = listOf("ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic")

/** "2026-10-16" -> "16 oct". Fixed table: the platform's month names differ
 *  between the JVM and Android ("oct" vs "oct."). Anything else comes back as is. */
fun shortDateEs(iso: String): String {
    val p = iso.split("-")
    val m = p.getOrNull(1)?.toIntOrNull()
    val d = p.getOrNull(2)?.toIntOrNull()
    if (p.size != 3 || m == null || d == null || m !in 1..12) return iso
    return "$d ${MONTHS_ES[m - 1]}"
}
