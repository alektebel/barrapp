package com.barrapp.media

import android.content.Context
import android.media.MediaMetadataRetriever
import android.net.Uri
import com.barrapp.data.MotionSample
import com.barrapp.data.TrimPlan
import com.barrapp.data.TrimSuggestion
import java.io.File

/** Puntos donde el recorte puede fallar y el teléfono debe subir el clip
 *  ORIGINAL: el muestreo, el transcodificador o la espera del resultado. El
 *  recorte jamás bloquea ni hace fallar una subida. */
sealed class TrimError(message: String) : Exception(message) {
    class Sampled(cause: Throwable) : TrimError(cause.message.orEmpty())
    class Transcode(cause: Throwable) : TrimError(cause.message.orEmpty())
    class Timeout : TrimError("el recorte tardó demasiado")
}

/** Cómo se corta un clip. La abstracción existe para las pruebas: un fake la
 *  implementa sin transcodificar nada. */
interface ClipTrimmer {
    /** Corta [startS,endS) a 720p H.264 ~4 Mbit/s. Escribe en [dst]. */
    suspend fun export(src: File, dst: File, startS: Double, endS: Double)
}

/** Lo que una pasada de muestreo sabe de un clip. */
data class ClipProbe(val durationS: Double, val samples: List<MotionSample>)

/**
 * Muestreo de movimiento con [MediaMetadataRetriever]: miniaturas pequeñas
 * cada 0,5 s, diferencia media de píxeles entre fotogramas consecutivos como
 * puntuación. Suficiente para separar una caminata de una serie de dominadas;
 * nada aquí toca un número medido — el servidor mide lo que recibe.
 */
class MediaMetadataSampler {

    /** El muestreo puede fallar (códec raro, uri caducada); el llamador
     *  decide qué hacer — la regla es enviar el clip sin recortar. */
    class SamplingException(cause: Throwable) : Exception(cause.message, cause)

    fun probe(context: Context, uri: Uri): ClipProbe {
        val retriever = MediaMetadataRetriever()
        try {
            retriever.setDataSource(context, uri)
            val durationMs = retriever.extractMetadata(
                MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull() ?: 0L
            if (durationMs <= 0L) return ClipProbe(0.0, emptyList())
            val durationS = durationMs / 1000.0
            val stepS = 0.5
            // Un paso de retardo para poder comparar cada muestra con la
            // anterior: la primera puntuación útil es la del segundo paso.
            var prev: android.graphics.Bitmap? = null
            val out = mutableListOf<MotionSample>()
            var t = stepS
            while (t < durationS) {
                val bmp = retriever.getFrameAtTime(
                    (t * 1_000_000).toLong(),
                    MediaMetadataRetriever.OPTION_CLOSEST_SYNC) ?: break
                val small = downscale(bmp)
                bmp.recycle()
                prev?.let { p -> out.add(MotionSample(t, frameDifference(p, small))) }
                if (prev !== small) prev?.recycle()
                prev = small
                t += stepS
            }
            prev?.recycle()
            return ClipProbe(durationS, out)
        } catch (err: Exception) {
            throw SamplingException(err)
        } finally {
            runCatching { retriever.release() }
        }
    }

    /** El núcleo puro del plan, alimentado con las muestras del clip real. */
    fun suggest(context: Context, uri: Uri): Pair<ClipProbe, TrimSuggestion?> {
        val probe = probe(context, uri)
        return probe to TrimPlan.suggest(probe.samples, probe.durationS)
    }

    private fun downscale(bmp: android.graphics.Bitmap): android.graphics.Bitmap {
        val w = 64
        val h = (bmp.height.toLong() * w / bmp.width.toLong().coerceAtLeast(1)).toInt()
            .coerceIn(1, 64)
        return android.graphics.Bitmap.createScaledBitmap(bmp, w, h, true)
    }

    /** Diferencia media de canales entre dos bitmaps del mismo tamaño,
     *  normalizada a 0..255. */
    private fun frameDifference(a: android.graphics.Bitmap, b: android.graphics.Bitmap): Double {
        val w = minOf(a.width, b.width)
        val h = minOf(a.height, b.height)
        if (w == 0 || h == 0) return 0.0
        val pa = IntArray(w * h); a.getPixels(pa, 0, w, 0, 0, w, h)
        val pb = IntArray(w * h); b.getPixels(pb, 0, w, 0, 0, w, h)
        var sum = 0L
        for (i in pa.indices) {
            val ca = pa[i]; val cb = pb[i]
            val dr = Math.abs((ca shr 16 and 0xFF) - (cb shr 16 and 0xFF))
            val dg = Math.abs((ca shr 8 and 0xFF) - (cb shr 8 and 0xFF))
            val db = Math.abs((ca and 0xFF) - (cb and 0xFF))
            sum += dr + dg + db
        }
        return sum / (pa.size.toDouble() * 3.0)
    }
}

/** El recortador real. En pruebas se sustituye por un fake. */
class DefaultClipTrimmer(private val context: Context) : ClipTrimmer {
    override suspend fun export(src: File, dst: File, startS: Double, endS: Double) {
        try {
            Media3ClipExporter.export(context, src, dst, startS, endS)
        } catch (err: Exception) {
            throw TrimError.Transcode(err)
        }
    }
}
