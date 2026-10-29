package com.barrapp.data

/**
 * The movements an athlete can name when uploading a clip: the catalog the
 * server's pipeline measures (barra.movements.MOVEMENTS, mirrored by
 * DECLARABLE_EXERCISES in server/api/handler.py, which rejects anything else).
 * Ordered for the picker, most common first.
 *
 * Declaring is optional and per clip. Left blank the server detects the
 * movement; declared, it measures that movement and skips detection - so a
 * wrong declaration is a wrong measurement, which is why it is never
 * remembered from one upload to the next.
 */
val DECLARABLE_EXERCISE_LIST = listOf(
    "pull_up", "push_up", "dip", "squat", "muscle_up", "knee_raise",
    "split_squat", "bulgarian_split_squat", "pistol_squat",
    "front_lever", "planche",
)

val DECLARABLE_EXERCISES: Set<String> = DECLARABLE_EXERCISE_LIST.toSet()
