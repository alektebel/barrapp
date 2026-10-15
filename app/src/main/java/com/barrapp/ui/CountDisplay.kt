package com.barrapp.ui

/** Describe what the count source can support; a failed count is not a
 * measured zero, and a sparse vision count is not a geometric measurement. */
internal fun countSummary(status: String, reps: Int, candidates: Int): String = when (status) {
    "vision" -> "$reps reps estimated from frames"
    "unmeasured" -> "Rep count unavailable"
    "hold" -> "$reps hold attempt${if (reps == 1) "" else "s"} measured"
    else -> "$reps rep${if (reps == 1) "" else "s"} measured" +
        if (candidates > reps) " of $candidates found" else ""
}
