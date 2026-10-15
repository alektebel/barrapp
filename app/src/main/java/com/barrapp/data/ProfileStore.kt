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
    private const val STANDARD = "declared_standard"
    private const val CAMERA = "declared_camera"

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

    /** The last declaration made before a clip (standard, camera), in the
     *  server's vocabulary; blank = not declared. Remembered so the record
     *  screen does not ask the same two questions before every set. */
    fun declaration(context: Context): Pair<String, String> {
        val p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        return p.getString(STANDARD, "").orEmpty() to p.getString(CAMERA, "").orEmpty()
    }

    fun saveDeclaration(context: Context, standard: String, camera: String) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit {
            putString(STANDARD, standard)
            putString(CAMERA, camera)
        }
    }

    /** Named `forget` rather than `clear` so it cannot shadow
     *  `SharedPreferences.Editor.clear()` inside an `edit { }` block. */
    fun forget(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit { clear() }
    }
}
