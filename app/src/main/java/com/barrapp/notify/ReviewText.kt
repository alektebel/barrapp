package com.barrapp.notify

import com.barrapp.Progression
import com.barrapp.data.DayEntry
import com.barrapp.data.Profile
import java.util.Calendar

/**
 * The weekly review, as arithmetic over plain data.
 *
 * Deliberately free of Android: no Context, no Worker, no notification. That is
 * partly good structure and partly the only way to test it - the Compose and
 * androidx toolchain cannot be fetched in this environment, so anything that
 * touches it can be parsed but never run. This can be run.
 *
 * It only produces a review when there is something to report. A notification
 * that arrives every Monday whether or not you trained is one people turn off
 * in a fortnight.
 */
object ReviewText {

    const val FLOOR = 3

    /** Below this the difference is inside the noise of a proxy built from
     *  three bounded components; calling it a trend would be an invention. */
    const val MIN_MEANINGFUL_DELTA = 8

    data class Review(val title: String, val body: String)

    fun compose(profile: Profile, all: List<DayEntry>, since: String = weekAgo()): Review? {
        val week = all.filter { it.date >= since }
        if (week.isEmpty()) return null

        val reps = week.sumOf { it.reps }
        val comparable = week.count { it.reps >= FLOOR }
        val measured = week.filter { it.measured }
        val name = profile.firstName

        val title = "$name \u2014 ${week.size} sesi${if (week.size == 1) "ón" else "ones"} esta semana"
        val body = buildString {
            append("$reps repetici${if (reps == 1) "ón medida" else "ones medidas"} en ")
            append("${week.size} día${if (week.size == 1) "" else "s"}. ")
            whatYouTrained(week)?.let { append("$it ") }
            when (comparable) {
                0 -> append(
                    "Ninguna llegó a $FLOOR repeticiones medidas, así que todavía no se puede comparar " +
                        "ninguna con otra sesión. Apunta a ${profile.repTarget} en una serie."
                )
                1 -> append(
                    "Una sesión llegó al mínimo de $FLOOR repeticiones. Con una más ya hay " +
                        "algo con lo que compararla."
                )
                else -> {
                    append("$comparable sesiones superaron el mínimo de $FLOOR repeticiones. ")
                    append(trendSentence(measured)
                        ?: "Las puntuaciones se mantuvieron estables dentro de su propia dispersión.")
                }
            }
            bestDay(measured)?.let { append(" $it") }
            progressionSentence(all)?.let { append(" $it") }
            volumeSentence(all, week, since)?.let { append(" $it") }
            unmeasuredSentence(week)?.let { append(" $it") }
        }
        return Review(title, body)
    }

    /** What the week actually consisted of, heaviest movement first. Without
     *  this the report is a rep count with no idea what the reps were. */
    fun whatYouTrained(week: List<DayEntry>): String? {
        val byMovement = week.filter { it.reps > 0 && it.exerciseLabel.isNotBlank() }
            .groupBy { com.barrapp.movementEs(it.exercise, it.exerciseLabel) }
        if (byMovement.isEmpty()) return null
        val parts = byMovement.entries
            .map { (label, days) -> Triple(label, days.size, days.sumOf { it.reps }) }
            .sortedByDescending { it.third }
            .map { (label, days, reps) ->
                "${label.lowercase()} ($reps repetici${if (reps == 1) "ón" else "ones"} en " +
                    "$days día${if (days == 1) "" else "s"})"
            }
        return when (parts.size) {
            1 -> "Todo fue ${parts[0]}."
            2 -> "${parts[0].replaceFirstChar { it.uppercase() }} y ${parts[1]}."
            else -> parts.dropLast(1).joinToString(", ")
                .replaceFirstChar { it.uppercase() } + " y ${parts.last()}."
        }
    }

    /**
     * Where the week left the progression the athlete is actually working.
     *
     * This is the line the review exists for. Everything else in it is a
     * summary of what happened; this is the one thing that says what it was
     * for. It never asserts readiness on its own authority - it reports the
     * standard and the evidence, and lets those speak.
     */
    fun progressionSentence(all: List<DayEntry>): String? {
        val v = Progression.focus(all) ?: return null
        val step = v.step ?: return null
        return if (v.ready)
            "Has superado el estándar de ${step.towardsLabel.lowercase()}: " +
                "${v.standard.replaceFirstChar { it.lowercase() }} " +
                "Logrado el ${v.qualifyingDays.joinToString(" y el ") { pretty(it) }}."
        else
            "Camino de ${step.towardsLabel.lowercase()}: ${v.missing.replaceFirstChar { it.lowercase() }}"
    }

    /** The single best day, so the week has a high point to point at. */
    fun bestDay(measured: List<DayEntry>): String? {
        val best = measured.filter { it.reps >= FLOOR }.maxByOrNull { it.score ?: 0 }
            ?: return null
        val score = best.score ?: return null
        return "El mejor día fue el ${pretty(best.date)}, con $score (${com.barrapp.Coach.bandEs(best.band)})."
    }

    /**
     * Volume against the week before. Reps are a count, not a proxy, so this
     * comparison is sound in a way the score comparison is not - but it is
     * still only reported when the previous week has something in it, because
     * "up 100%" from a week you did not train is not information.
     */
    fun volumeSentence(all: List<DayEntry>, week: List<DayEntry>, since: String): String? {
        val priorStart = shiftDays(since, -7)
        val prior = all.filter { it.date >= priorStart && it.date < since }
        if (prior.isEmpty()) return null
        val now = week.sumOf { it.reps }
        val before = prior.sumOf { it.reps }
        if (before == 0) return null
        val delta = now - before
        return when {
            delta > 0 -> "El volumen sube desde las $before repeticiones de la semana anterior."
            delta < 0 -> "El volumen baja desde las $before repeticiones de la semana anterior."
            else -> "El volumen fue exactamente el de la semana anterior."
        }
    }

    /** Sessions that produced nothing. These are a filming problem, and saying
     *  so is the only way they stop happening. */
    fun unmeasuredSentence(week: List<DayEntry>): String? {
        val blank = week.count { !it.measured }
        if (blank == 0) return null
        return if (blank == 1)
            "1 sesión no produjo repeticiones medibles \u2014 conviene revisar el encuadre de ese clip."
        else "$blank sesiones no produjeron repeticiones medibles \u2014 conviene revisar el encuadre de esos clips."
    }

    /** "2026-08-19" -> "19 Aug". Hand-rolled because this file stays free of
     *  Android, and java.text formatters drag locale behaviour in with them. */
    fun pretty(date: String): String {
        val p = date.split("-")
        if (p.size != 3) return date
        val month = p[1].toIntOrNull() ?: return date
        val names = listOf("ene", "feb", "mar", "abr", "may", "jun",
                           "jul", "ago", "sep", "oct", "nov", "dic")
        if (month !in 1..12) return date
        return "${p[2].trimStart('0')} ${names[month - 1]}"
    }

    /** Date arithmetic on the "YYYY-MM-DD" strings the store uses. */
    fun shiftDays(date: String, days: Int): String {
        val p = date.split("-").mapNotNull { it.toIntOrNull() }
        if (p.size != 3) return date
        val c = Calendar.getInstance()
        c.clear()
        c.set(p[0], p[1] - 1, p[2])
        c.add(Calendar.DAY_OF_YEAR, days)
        return "%04d-%02d-%02d".format(
            c.get(Calendar.YEAR), c.get(Calendar.MONTH) + 1, c.get(Calendar.DAY_OF_MONTH)
        )
    }

    fun trendSentence(measured: List<DayEntry>): String? {
        if (measured.size < 2) return null
        val ordered = measured.sortedBy { it.date }
        val delta = (ordered.last().score ?: 0) - (ordered.first().score ?: 0)
        if (kotlin.math.abs(delta) < MIN_MEANINGFUL_DELTA) return null
        return if (delta > 0)
            "La puntuación base sube $delta puntos a lo largo de la semana. Merece una mirada, " +
                "pero no se ha contrastado con tu propia variación entre repeticiones."
        else
            "La puntuación base baja ${-delta} puntos a lo largo de la semana."
    }

    fun weekAgo(): String {
        val c = Calendar.getInstance()
        c.add(Calendar.DAY_OF_YEAR, -7)
        return "%04d-%02d-%02d".format(
            c.get(Calendar.YEAR), c.get(Calendar.MONTH) + 1, c.get(Calendar.DAY_OF_MONTH)
        )
    }
}
