package com.barrapp.data

import android.content.Context
import androidx.core.content.edit

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

object ProfileStore {
    private const val PREFS = "barrapp_profile"
    private const val NAME = "name"
    private const val AGE = "age"
    private const val ACTIVITY = "activity"

    fun load(context: Context): Profile {
        val p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val stored = p.getString(ACTIVITY, ActivityLevel.Unset.name) ?: ActivityLevel.Unset.name
        val activity = ActivityLevel.entries.firstOrNull { it.name == stored } ?: ActivityLevel.Unset
        return Profile(
            name = p.getString(NAME, "").orEmpty(),
            age = p.getInt(AGE, 0),
            activity = activity,
        )
    }

    fun save(context: Context, profile: Profile) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit {
            putString(NAME, profile.name)
            putInt(AGE, profile.age)
            putString(ACTIVITY, profile.activity.name)
        }
    }

    /** Named `forget` rather than `clear` so it cannot shadow
     *  `SharedPreferences.Editor.clear()` inside an `edit { }` block. */
    fun forget(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit { clear() }
    }
}
