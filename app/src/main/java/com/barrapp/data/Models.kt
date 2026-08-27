package com.barrapp.data

data class CreatedJob(
    val job: Job,
    val uploadUrl: String,
    val uploadMethod: String,
)

data class Job(
    val id: String,
    val status: String,
    val exercise: String,
    val createdAt: String,
    val result: Analysis? = null,
    val error: String? = null,
)

data class Analysis(
    val headline: String,
    val narrative: String,
    val sessions: List<SessionRow>,
    val reps: List<RepRow>,
    val blockers: List<String>,
    val nextSession: String,
)

data class SessionRow(
    val date: String,
    val reps: Int,
    val note: String,
)

data class MetricLine(
    val name: String,
    val value: String,
    val cls: String,
)

data class RepRow(
    val session: String,
    val label: String,
    val transitionS: String,
    val totalS: String,
    val cls: String,
    val metrics: List<MetricLine> = emptyList(),
    val problems: List<String> = emptyList(),
    val plausible: Boolean = true,
)
