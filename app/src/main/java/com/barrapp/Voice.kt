package com.barrapp

/**
 * How the app talks.
 *
 * Barrapp is an instrument with opinions about evidence and none about you.
 * That is the whole personality: dry, exact, occasionally funny, and never
 * once claiming to have measured something it did not. Every line here is
 * chosen under one rule - it must be true whatever the clip turns out to show.
 * "Counting reps" is safe. "Looking good" is not, because it may not be.
 *
 * Lines rotate so the fourth upload does not read like the first, and they
 * are seeded from something stable (the job id, the day) rather than from a
 * random number, so a screen does not change its mind while you look at it.
 *
 * Deliberately free of Android so it can be run rather than only parsed:
 * `tools/run_logic_tests.sh` executes every table here and checks the rules
 * below hold for every line.
 */
object Voice {

    /** The four stages of an upload, in order, keyed by the stage constants
     *  in [BarrappViewModel]. Each carries the rotating lines the processing
     *  screen shows under the stage name while it is the active one. */
    data class Stage(val name: String, val lines: List<String>)

    val STAGES: List<Stage> = listOf(
        Stage(
            "Uploading the clip",
            listOf(
                "Sending the footage. This is the only part that depends on your Wi-Fi.",
                "The clip is leaving the phone. Everything after this happens on the server.",
                "Uploading. No percentage, because the server does not report one and a bar stuck at 90% is a lie.",
            ),
        ),
        Stage(
            "Finding the exercise",
            listOf(
                "Looking for hands on something that does not move.",
                "Working out what you did from where your hands were. You did not have to tell it, and it will not guess.",
                "Deciding between six movements and a hold, geometrically. No model was trained for this.",
                "Checking whether the shoulders ever finish above the hands. That one line is the whole pull-up / muscle-up split.",
            ),
        ),
        Stage(
            "Trimming to the working set",
            listOf(
                "Cutting the walk to the bar and the walk away. They are not the exercise.",
                "Finding where the set starts and where it stops. The rest is footage.",
                "Trimming. If you were still walking when the reps happened, this is where it notices.",
            ),
        ),
        Stage(
            "Counting and measuring the reps",
            listOf(
                "Counting reps. Counting them honestly, which sometimes means fewer.",
                "Measuring each rep against your own reach, not a chart.",
                "A rep it cannot measure gets a dash, not a low score. That is on purpose.",
                "Range, control, smoothness. Swing is measured too, but kept out of the number - it depends on where the phone stood.",
            ),
        ),
    )

    /** The line to show under a stage right now. `tick` advances on a timer
     *  so a long wait cycles through the stage's lines; `seed` keeps the
     *  first line stable per upload. */
    fun stageLine(stage: String, tick: Int, seed: Int = 0): String {
        val s = STAGES.firstOrNull { it.name.equals(stage, ignoreCase = true) }
            ?: return ""
        return pick(s.lines, tick + seed)
    }

    /** Greeting, keyed by hour. One line per part of the day, plus a few
     *  that rotate by day so the header is not identical every morning. */
    fun greeting(name: String, hour: Int, dayOfYear: Int = 0): String {
        val part = when (hour) {
            in 5..11 -> "Morning"
            in 12..17 -> "Afternoon"
            in 18..23 -> "Evening"
            else -> "Late"
        }
        val tails = listOf(
            "",
            " · the bar has not moved since yesterday",
            " · one set, filmed properly, beats three filmed badly",
            " · the tripod spot on the floor is still the best upgrade there is",
            " · nothing here is a chart of other people",
        )
        return "$part, $name" + pick(tails, dayOfYear)
    }

    /** The empty state: what the app is for, without pretending it has
     *  something to say yet. */
    val EMPTY_TITLE = "Nothing measured yet"
    val EMPTY_LINES: List<String> = listOf(
        "That is not a judgement. It is an empty calendar.",
        "Add a clip of one set. It works out what you did, counts the reps it can " +
            "see, and says which ones it could not.",
        "It compares you with you. There is no leaderboard in here, on purpose.",
    )

    /** The line that appears as a measured session arrives. Only says what
     *  the payload proves: a count, and whether anything scored. */
    fun arrival(reps: Int, scored: Boolean, label: String?): String {
        val what = label?.lowercase()?.let { " of $it" }.orEmpty()
        return when {
            reps == 0 -> "Measured. Nothing counted$what - the reason is on the card."
            !scored -> "$reps rep${if (reps == 1) "" else "s"}$what found. None could be scored, and it says why."
            reps == 1 -> "One rep$what measured. One is an observation, not a session."
            reps < 3 -> "$reps reps$what measured. Three is the floor for a session median."
            else -> "$reps reps$what measured and scored."
        }
    }

    /** A held position arrived instead of a set. */
    fun holdArrival(label: String, seconds: Double): String =
        "${label.replaceFirstChar { it.uppercase() }} held for ${seconds.toInt()} s. " +
            "Time held is the measurement; how straight it was is not scored."

    /** What to say while the coach is composing an answer. */
    val COACH_THINKING: List<String> = listOf(
        "Reading your sessions…",
        "Doing arithmetic, not guessing…",
        "Checking what the numbers can actually support…",
    )

    /** Errors, kept human. The technical message goes to Diagnostics. */
    fun failure(message: String?): String {
        val m = message.orEmpty()
        return when {
            m.contains("timed out", true) || m.contains("longer than usual", true) ->
                "The server is slow today. The clip is still queued and will appear on your calendar when it lands."
            m.contains("could not be sent", true) || m.contains("Unable to resolve", true) ||
                m.contains("Failed to connect", true) || m.contains("connect", true) ->
                "The clip never left the phone. Check the connection and try again - nothing was lost."
            m.isBlank() -> "That did not work, and the app is not going to pretend otherwise. Diagnostics has the details."
            else -> m
        }
    }

    /** Titles for the processing screen, one per upload. */
    val PROCESSING_TITLES: List<String> = listOf(
        "Measuring",
        "Working on it",
        "Reading the set",
        "Looking at the footage",
    )

    fun processingTitle(seed: Int): String = pick(PROCESSING_TITLES, seed)

    private fun pick(lines: List<String>, index: Int): String {
        if (lines.isEmpty()) return ""
        val i = ((index % lines.size) + lines.size) % lines.size
        return lines[i]
    }

    /**
     * The words a line must never use, because every one of them is a claim
     * about the clip that the app cannot have verified while the line is on
     * screen. Checked by the logic tests over every table above.
     */
    val FORBIDDEN: List<String> = listOf(
        "great", "perfect", "awesome", "looking good", "well done", "nice form",
        "good form", "improving", "you're ready", "you are ready", "new record",
    )
}
