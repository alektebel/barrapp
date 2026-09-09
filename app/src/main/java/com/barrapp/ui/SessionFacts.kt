package com.barrapp.ui

import com.barrapp.data.Analysis
import com.barrapp.data.Assessment
import com.barrapp.data.RepRow
import com.barrapp.data.Variant

/**
 * Pure mappings from the server's assessment records to what the session
 * page shows. No Compose in here, so `LogicTest` can pin the wording.
 */

/** Every check on one rep, flagged first, then clean, then the ones that
 *  could not be made. Older payloads (no assessments) fall back to the
 *  measured faults, so a v1 session still lists what was flagged. */
fun repChecks(rep: RepRow): List<RepCheck> {
    if (rep.assessments.isEmpty()) {
        return rep.faults.map { f ->
            RepCheck(
                name = f.name.replaceFirstChar { it.uppercase() },
                status = Assessment.OBSERVED,
                where = where(f.phase, f.intervalS),
                detail = f.evidence(),
            )
        }
    }
    val order = mapOf(Assessment.OBSERVED to 0, Assessment.NOT_OBSERVED to 1)
    return rep.assessments
        .sortedBy { order[it.status] ?: 2 }
        .map { a ->
            RepCheck(
                name = a.name.replaceFirstChar { it.uppercase() } +
                    if (a.variantDependent && a.observed) " (variant not declared)" else "",
                status = a.status,
                where = if (a.status == Assessment.UNOBSERVABLE) "" else where(a.phase, a.intervalS),
                detail = when (a.status) {
                    Assessment.UNOBSERVABLE -> a.reasonLabel()
                    else -> evidence(a)
                },
            )
        }
}

/** The standard the checks were applied under, in one line. Blank when the
 *  payload predates variants, so nothing is claimed about an older run. */
fun standardLine(a: Analysis): String {
    if (a.measurementVersion < 2) return ""
    val v = a.variant
    val movement = a.exercise.replace('_', ' ').ifBlank { "this movement" }
    // Only movements with a variant-dependent check have a standard to
    // declare; a push-up set says nothing about one.
    val dependsOnVariant = a.reps.any { r -> r.assessments.any { it.variantDependent } }
    return when {
        v.isSpecified && v.source == "declared" ->
            "Judged to the ${v.name.replace('_', ' ')} standard you declared."
        v.isSpecified -> "Judged to the ${v.name.replace('_', ' ')} standard."
        v.declared != null && v.declared != Variant.UNSPECIFIED ->
            "You declared \"${v.declared.replace('_', ' ')}\", which is not a standard " +
                "for a $movement, so the set was judged without one."
        dependsOnVariant ->
            "No standard declared. Checks that depend on strict or kipping form " +
                "are marked, not assumed. Declare one on the upload page next time."
        else -> ""
    }
}

private fun where(phase: String, interval: List<Double>): String {
    val p = phase.replace('_', ' ')
    return when {
        interval.size >= 2 -> "%s · %.1f–%.1fs".format(p, interval[0], interval[1])
        else -> p
    }
}

private fun evidence(a: Assessment): String {
    val v = a.value ?: return ""
    val needs = if (a.comparison.startsWith("<")) "needs" else "limit"
    return "${fmt(v)}${suffix(a.unit)}, $needs ${fmt(a.threshold)}${suffix(a.unit)}"
}

private fun suffix(unit: String) = if (unit.isBlank()) "" else " $unit"

private fun fmt(d: Double): String =
    if (d >= 10 || d == d.toLong().toDouble()) d.toLong().toString()
    else String.format("%.2f", d)
