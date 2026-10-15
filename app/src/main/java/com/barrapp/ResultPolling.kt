package com.barrapp

private const val ROUND2_FAST_POLL_WINDOW_MS = 15_000L
private const val FAST_RESULT_POLL_MS = 250L
private const val NORMAL_RESULT_POLL_MS = 1_000L

internal fun resultPollDelayMs(elapsedSinceAttemptStartMs: Long): Long =
    if (elapsedSinceAttemptStartMs < ROUND2_FAST_POLL_WINDOW_MS)
        FAST_RESULT_POLL_MS else NORMAL_RESULT_POLL_MS
