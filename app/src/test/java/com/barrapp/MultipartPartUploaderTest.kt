package com.barrapp

import com.barrapp.data.uploadPartsBatched
import com.barrapp.data.copyInputRangeToSink
import com.barrapp.data.chooseUploadMode
import com.barrapp.data.DEFAULT_SINGLE_PUT_MAX_BYTES
import kotlinx.coroutines.delay
import kotlinx.coroutines.test.runTest
import okio.Buffer
import java.io.ByteArrayInputStream
import java.io.EOFException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MultipartPartUploaderTest {
    @Test fun `single-put cutoff is configurable while default remains 8 MiB`() {
        val prepared30sBytes = 14_610_000L
        val defaultCutoff = DEFAULT_SINGLE_PUT_MAX_BYTES
        val candidateCutoff = 16L * 1024 * 1024

        assertEquals(8L * 1024 * 1024, defaultCutoff)
        assertEquals("multipart", chooseUploadMode(
            prepared30sBytes, defaultCutoff, "https://upload", "PUT"))
        assertEquals("single", chooseUploadMode(
            prepared30sBytes, candidateCutoff, "https://upload", "PUT"))
        assertEquals("multipart", chooseUploadMode(
            prepared30sBytes, candidateCutoff, "https://upload", "POST"))
        assertEquals("multipart", chooseUploadMode(
            prepared30sBytes, candidateCutoff, null, "PUT"))
    }

    @Test fun `part reader handles short skips and copies the exact requested range`() {
        val input = object : ByteArrayInputStream("abcdefghij".toByteArray()) {
            override fun skip(n: Long): Long = super.skip(minOf(n, 2L))
        }
        val sink = Buffer()

        copyInputRangeToSink(input, sink, offset = 5, length = 3)

        assertEquals("fgh", sink.readUtf8())
    }

    @Test fun `part reader rejects a source shorter than its requested range`() {
        val input = ByteArrayInputStream("abc".toByteArray())
        val sink = Buffer()

        try {
            copyInputRangeToSink(input, sink, offset = 2, length = 2)
            throw AssertionError("expected truncated source failure")
        } catch (_: EOFException) {
            assertEquals("c", sink.readUtf8())
        }
    }

    @Test fun `uploads parts with bounded parallelism and ordered persistence`() = runTest {
        var active = 0
        var peak = 0
        val persisted = mutableListOf<Int>()
        uploadPartsBatched(
            partNumbers = (1..7).toList(), maxConcurrency = 3,
            uploadPart = { part ->
                active++
                peak = maxOf(peak, active)
                delay((8 - part).toLong())
                active--
                "etag-$part"
            },
            onUploaded = { part, etag ->
                assertEquals("etag-$part", etag)
                persisted.add(part)
            },
        )
        assertEquals(3, peak)
        assertEquals((1..7).toList(), persisted.sorted())
    }

    @Test fun `persists successful siblings before surfacing a failed part`() = runTest {
        val persisted = mutableListOf<Int>()
        val failure = try {
            uploadPartsBatched(
                partNumbers = listOf(1, 2, 3), maxConcurrency = 3,
                uploadPart = { part ->
                    if (part == 2) error("network reset")
                    "etag-$part"
                },
                onUploaded = { part, _ -> persisted.add(part) },
            )
            null
        } catch (err: Exception) {
            err
            }
        assertTrue(failure is IllegalStateException)
        assertEquals(listOf(1, 3), persisted)
    }
}
