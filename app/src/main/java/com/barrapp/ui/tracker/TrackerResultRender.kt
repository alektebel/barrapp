package com.barrapp.ui.tracker

internal fun shouldMarkResultRendered(
    phase: RecordPhase,
    hasResult: Boolean,
    jobId: String?,
    resultTraceId: String?,
    currentTraceId: String?,
): Boolean = phase == RecordPhase.RESULTS && hasResult &&
    !jobId.isNullOrBlank() &&
    !resultTraceId.isNullOrBlank() &&
    resultTraceId == currentTraceId
