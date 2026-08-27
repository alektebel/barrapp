package com.barrapp.data

import android.content.Context
import androidx.core.content.edit

/**
 * Where the profile is kept.
 *
 * Split from [Profile] so the model itself depends on nothing Android-specific.
 * That is what lets the logic that consumes it be compiled and RUN on a plain
 * JVM, which in this environment is the only way any of this Kotlin gets
 * executed at all.
 */
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
