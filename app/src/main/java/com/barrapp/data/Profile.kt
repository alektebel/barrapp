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
    val complete: Boolean
        get() = name.isNotBlank() && age in 10..100 && activity != ActivityLevel.Unset

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
    New("Just starting", "New to training, or coming back after a break"),
    Occasional("Once or twice a week", "Training happens, but not on a schedule"),
    Regular("Three or four times a week", "A routine you mostly keep to"),
    Daily("Five or more times a week", "Training is part of most days"),
}
