package com.barrapp.data

/**
 * El recorte que propone el teléfono, antes de enviar nada.
 *
 * Un clip de cámara dura 30–35 s pero la serie dura ~6 s: todo lo demás es
 * la caminata a la barra y la salida, que se sube y se procesa para nada.
 * El núcleo de la sugerencia es una función pura — puntuaciones de movimiento
 * dentro, ventana fuera — para poder probarla con puntuaciones sintéticas
 * sin decodificar vídeo: la parte Android (el muestreo) vive en
 * com.barrapp.media.MotionSampler y solo alimenta esto.
 */
/** Una muestra de movimiento: qué tanto cambió la imagen en el segundo [tS].
 *  La puntuación es adimensional; solo importa su magnitud relativa. */
data class MotionSample(val tS: Double, val score: Double)

/** La ventana de la serie, en segundos, dentro del clip completo. */
data class TrimSuggestion(
    val startS: Double,
    val endS: Double,
    val durationS: Double,
) {
    val lengthS: Double get() = (endS - startS).coerceAtLeast(0.0)
}

object TrimPlan {
    /** Aire antes y después de la serie, para no cortar la primera ni la
     *  última repetición por los bordes. */
    const val LEAD_IN_S = 2.5
    const val LEAD_OUT_S = 2.5

    /** Fracción del pico de movimiento a partir de la cual una muestra
     *  cuenta como "serie". Baja a propósito: perder una repetición cuesta
     *  más que subir unos segundos de más. */
    const val PEAK_FRACTION = 0.2

    /** Un tramo de movimiento más corto que esto (muestras) es un roce, no
     *  una serie. Con muestras cada 0,5 s son 2 s. */
    const val MIN_RUN_SAMPLES = 4

    /** Cuántas muestras por debajo del umbral se toleran DENTRO de la serie
     *  (una pausa entre repeticiones, un frame oscuro) antes de dar la serie
     *  por terminada. Con muestras cada 0,5 s son hasta 3 s de silencio. */
    const val MAX_GAP_SAMPLES = 6

    /**
     * La ventana contigua de movimiento por encima del umbral, expandida con
     * el aire de entrada/salida y sujetada a la duración del clip. Null cuando
     * no hay movimiento que localizar: un clip sin serie no se recorta.
     */
    fun suggest(samples: List<MotionSample>, durationS: Double): TrimSuggestion? {
        if (samples.isEmpty()) return null
        val peak = samples.maxOf { it.score }
        if (peak <= 0.0) return null
        val threshold = peak * PEAK_FRACTION

        // Índices por encima del umbral, agrupados en series contiguas con
        // huecos de hasta MAX_GAP_SAMPLES muestras puente adentro.
        val above = samples.withIndex().filter { it.value.score >= threshold }.map { it.index }
        if (above.isEmpty()) return null
        val runs = mutableListOf(listOf(above.first()))
        for (i in 1 until above.size) {
            val prev = above[i - 1]
            val cur = above[i]
            if (cur - prev - 1 <= MAX_GAP_SAMPLES) {
                runs[runs.size - 1] = runs.last() + cur
            } else {
                runs.add(listOf(cur))
            }
        }
        // Conservador: se conservan TODOS los tramos con entidad, del primero
        // al último, no solo el más largo. Dos series con un descanso largo
        // en medio, o una serie corta tras una larga, siguen dentro. Si
        // ningún tramo llega al mínimo, se queda el más largo.
        val real = runs.filter { it.size >= MIN_RUN_SAMPLES }
            .ifEmpty { listOf(runs.maxBy { it.size }) }
        val windowStart = samples[real.first().first()].tS
        val windowEnd = samples[real.last().last()].tS

        val startS = (windowStart - LEAD_IN_S).coerceIn(0.0, durationS)
        val endS = (windowEnd + LEAD_OUT_S).coerceIn(startS, durationS)
        return TrimSuggestion(startS, endS, durationS)
    }

    /**
     * ¿Merece la pena recortar? Solo cuando la sugerencia existe y deja fuera
     * una parte sustancial del clip: recortar un clip que ya es casi todo
     * serie re-encodea para nada y arriesga la subida.
     */
    fun shouldTrim(suggestion: TrimSuggestion?, durationS: Double): Boolean {
        if (suggestion == null || durationS <= 0.0) return false
        if (suggestion.lengthS <= 0.0) return false
        return suggestion.lengthS < 0.8 * durationS
    }
}
