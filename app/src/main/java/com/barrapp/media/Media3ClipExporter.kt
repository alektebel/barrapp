package com.barrapp.media

import android.content.Context
import android.net.Uri
import java.io.File
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.effect.Presentation
import androidx.media3.transformer.EditedMediaItem
import androidx.media3.transformer.Effects
import androidx.media3.transformer.ExportException
import androidx.media3.transformer.ExportResult
import androidx.media3.transformer.DefaultEncoderFactory
import androidx.media3.transformer.Transformer
import androidx.media3.transformer.TransformationRequest
import androidx.media3.transformer.VideoEncoderSettings

/**
 * El corte real, con Media3 Transformer: [startS,endS) del clip a 720p
 * H.264. El worker del servidor ya reescala a 640 px de ancho, así que 720p
 * no le quita información: solo le quita segundos al envío.
 *
 * Corre en un hilo de E/S y devuelve cuando el fichero está escrito. Cualquier
 * fallo (códec no soportado, sin espacio, excepción, más de 3 minutos) sube
 * como excepción; el llamador la convierte en "sube el clip original", así
 * que el recorte nunca bloquea ni hace fallar una subida.
 */
object Media3ClipExporter {

    private const val TIMEOUT_MS = 3L * 60 * 1000
    private const val TARGET_HEIGHT = 720
    private const val TARGET_VIDEO_BITRATE_BPS = 4_000_000

    /** Cualquier fallo del transcodificador, con su causa dentro. */
    class ExportFailed(cause: Throwable) : Exception(cause.message, cause)

    @androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
    suspend fun export(context: Context, src: File, dst: File, startS: Double, endS: Double): Int? {
        return withContext(Dispatchers.IO) {
            dst.parentFile?.mkdirs()
            dst.delete()

            val request = TransformationRequest.Builder()
                .setVideoMimeType(MimeTypes.VIDEO_H264)
                .setAudioMimeType(MimeTypes.AUDIO_AAC)
                .build()

            val clipped = MediaItem.fromUri(Uri.fromFile(src)).buildUpon()
                .setClippingConfiguration(
                    MediaItem.ClippingConfiguration.Builder()
                        .setStartPositionMs((startS * 1000).toLong())
                        .setEndPositionMs((endS * 1000).toLong())
                        .build())
                .build()

            // El efecto de presentación ajusta el vídeo a 720p de alto
            // manteniendo el aspecto.
            val item = EditedMediaItem.Builder(clipped)
                .setEffects(Effects(emptyList(),
                    listOf(Presentation.createForHeight(TARGET_HEIGHT))))
                .build()

            val encoderFactory = DefaultEncoderFactory.Builder(context)
                .setRequestedVideoEncoderSettings(VideoEncoderSettings.Builder()
                    .setBitrate(TARGET_VIDEO_BITRATE_BPS)
                    .build())
                .build()
            val transformer = Transformer.Builder(context)
                .setTransformationRequest(request)
                .setEncoderFactory(encoderFactory)
                .build()

            try {
                val result = withTimeoutOrNull(TIMEOUT_MS) {
                    kotlinx.coroutines.suspendCancellableCoroutine<ExportResult> { cont ->
                        transformer.addListener(object : Transformer.Listener {
                            override fun onCompleted(
                                composition: androidx.media3.transformer.Composition,
                                exportResult: ExportResult,
                            ) { if (cont.isActive) cont.resume(exportResult) }

                            override fun onError(
                                composition: androidx.media3.transformer.Composition,
                                exportResult: ExportResult,
                                exportException: ExportException,
                            ) { if (cont.isActive) cont.resumeWithException(exportException) }
                        })
                        transformer.start(item, Uri.fromFile(dst).toString())
                        cont.invokeOnCancellation { runCatching { transformer.cancel() } }
                    }
                } ?: throw java.util.concurrent.TimeoutException(
                    "el recorte superó los 3 minutos")
                result.averageVideoBitrate.takeIf { it > 0 }
            } catch (err: Throwable) {
                runCatching { transformer.cancel() }
                dst.delete()
                throw ExportFailed(err)
            }
        }
    }
}
