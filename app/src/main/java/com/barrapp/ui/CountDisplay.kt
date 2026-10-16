package com.barrapp.ui

/** Describe what the count source can support; a failed count is not a
 * measured zero, and a sparse vision count is not a geometric measurement. */
internal fun countSummary(status: String, reps: Int, candidates: Int): String = when (status) {
    "vision" -> if (reps == 1) "1 repetición estimada a partir de fotogramas" else "$reps repeticiones estimadas a partir de fotogramas"
    "unmeasured" -> "Recuento de repeticiones no disponible"
    "hold" -> "$reps intento${if (reps == 1) "" else "s"} de mantenimiento medido${if (reps == 1) "" else "s"}"
    else -> "$reps repetici${if (reps == 1) "ón medida" else "ones medidas"}" +
        if (candidates > reps) " de $candidates encontradas" else ""
}
