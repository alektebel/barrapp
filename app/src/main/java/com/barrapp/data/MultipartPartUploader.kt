package com.barrapp.data

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.channels.Channel
import okio.BufferedSink
import java.io.EOFException
import java.io.InputStream

internal const val MULTIPART_UPLOAD_CONCURRENCY = 3
internal const val DEFAULT_SINGLE_PUT_MAX_BYTES = 8L * 1024 * 1024

internal fun chooseUploadMode(
    clipBytes: Long,
    singlePutMaxBytes: Long,
    uploadUrl: String?,
    uploadMethod: String?,
): String {
    require(clipBytes >= 0 && singlePutMaxBytes >= 0) {
        "clip size and single-PUT limit must be non-negative"
    }
    return if (clipBytes <= singlePutMaxBytes && !uploadUrl.isNullOrBlank()
        && uploadMethod.equals("PUT", ignoreCase = true)) "single" else "multipart"
}

/** Copy exactly one file range; InputStream.skip/read are allowed to advance
 * less than requested, so the range is verified before the request completes. */
internal fun copyInputRangeToSink(
    input: InputStream,
    sink: BufferedSink,
    offset: Long,
    length: Long,
) {
    require(offset >= 0 && length >= 0) { "offset and length must be non-negative" }
    var toSkip = offset
    while (toSkip > 0) {
        val skipped = input.skip(toSkip)
        if (skipped > 0) {
            toSkip -= minOf(skipped, toSkip)
        } else {
            if (input.read() < 0) throw EOFException("source ended before part offset")
            toSkip--
        }
    }

    val buffer = ByteArray(1 shl 20)
    var remaining = length
    while (remaining > 0) {
        val count = input.read(buffer, 0, minOf(buffer.size.toLong(), remaining).toInt())
        when {
            count < 0 -> throw EOFException("source ended before part length")
            count == 0 -> {
                val one = input.read()
                if (one < 0) throw EOFException("source ended before part length")
                sink.writeByte(one)
                remaining--
            }
            else -> {
                sink.write(buffer, 0, count)
                remaining -= count
            }
        }
    }
}

/** Upload a bounded batch in parallel, then persist every successful part
 * before propagating any sibling failure. Missing parts remain resumable. */
internal suspend fun uploadPartsBatched(
    partNumbers: List<Int>,
    maxConcurrency: Int,
    uploadPart: suspend (Int) -> String?,
    onUploaded: suspend (Int, String?) -> Unit,
) {
    require(maxConcurrency > 0) { "maxConcurrency must be positive" }
    for (batch in partNumbers.chunked(maxConcurrency)) {
        var failure: Exception? = null
        coroutineScope {
            val completed = Channel<Pair<Int, Result<String?>>>(batch.size)
            val tasks = batch.map { part ->
                async {
                    val result = try {
                        Result.success(uploadPart(part))
                    } catch (cancelled: CancellationException) {
                        throw cancelled
                    } catch (error: Exception) {
                        Result.failure(error)
                    }
                    completed.send(part to result)
                }
            }
            repeat(batch.size) {
                val (part, result) = completed.receive()
                result.fold(
                    onSuccess = { etag -> onUploaded(part, etag) },
                    onFailure = { error -> if (failure == null) failure = error as? Exception
                        ?: RuntimeException(error) },
                )
            }
            tasks.awaitAll()
            completed.close()
        }
        failure?.let { throw it }
    }
}
