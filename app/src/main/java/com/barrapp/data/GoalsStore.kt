package com.barrapp.data

import android.content.Context
import androidx.core.content.edit

/**
 * Where the objectives are kept, separate from the profile so a goal can be
 * edited later without touching the three onboarding fields.
 */
object GoalsStore {
    private const val PREFS = "barrapp_goals"
    private const val GOAL = "goal"
    private const val FOCUS = "focus_exercise"

    fun load(context: Context): Goals {
        val p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        return Goals(
            goal = p.getString(GOAL, "").orEmpty(),
            focusExercise = p.getString(FOCUS, "").orEmpty(),
        )
    }

    fun save(context: Context, goals: Goals) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit {
            putString(GOAL, goals.goal)
            putString(FOCUS, goals.focusExercise)
        }
    }
}
