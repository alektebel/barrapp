package com.barrapp.data

import android.content.Context
import org.json.JSONObject

/**
 * The calisthenics skill graph, as barra/skills.py defines it, shipped as
 * assets/skills.json (scripts/export_skills.py; a test fails if it is stale).
 *
 * States mirror skills.state() exactly (SkillGraphTest checks them against
 * values Python generated):
 *   VERIFIED   barra measured it: a measurable skill whose standard was met
 *   CLAIMED    implied by something done (its prerequisites), never evidence
 *   AVAILABLE  every prerequisite done - what to work on
 *   LOCKED     something upstream is not done yet
 */
class SkillGraph(private val nodes: Map<String, SkillNode>, val families: Map<String, String>) {

    data class Standard(val reps: Int, val quality: Int, val days: Int)

    data class SkillNode(
        val id: String,
        val name: String,
        val family: String,
        /** barra's English name: the tie-break order of next_up, not for display. */
        val nameEn: String,
        val requires: List<String>,
        val tier: Int,
        val measurable: Boolean,
        val standard: Standard?,
    )

    val size: Int get() = nodes.size
    operator fun get(id: String): SkillNode? = nodes[id]

    fun ancestors(id: String): Set<String> {
        val out = mutableSetOf<String>()
        val stack = ArrayDeque(nodes[id]?.requires.orEmpty())
        while (stack.isNotEmpty()) {
            val cur = stack.removeLast()
            if (cur in out || cur !in nodes) continue
            out += cur
            stack.addAll(nodes.getValue(cur).requires)
        }
        return out
    }

    /** Every skill's state. Mirrors barra/skills.py state(). */
    fun state(verified: Set<String>, claimed: Set<String>): Map<String, String> {
        val implied = (verified + claimed).filter { it in nodes }.flatMap { ancestors(it) }.toSet()
        val allClaimed = claimed + (implied - verified)
        val done = verified + allClaimed
        return nodes.mapValues { (id, skill) ->
            when {
                id in verified -> VERIFIED
                id in allClaimed -> CLAIMED
                skill.requires.all { it in done } -> AVAILABLE
                else -> LOCKED
            }
        }
    }

    /** The target and everything it needs, shallowest first, target last. */
    fun path(target: String): List<SkillNode> {
        val t = nodes[target] ?: return emptyList()
        val ids = ancestors(target)
        return ids.map { nodes.getValue(it) }.sortedWith(compareBy({ it.tier }, { it.name })) + t
    }

    /**
     * What to work on next for this target: an AVAILABLE skill on its path,
     * the ones barra can verify first, then shallowest, then by name - the
     * order of barra/skills.py next_up().
     */
    fun nextOnPath(target: String, verified: Set<String>, claimed: Set<String>): SkillNode? {
        val st = state(verified, claimed)
        val onPath = path(target).map { it.id }.toSet()
        return nodes.values
            .filter { it.id in onPath && st[it.id] == AVAILABLE }
            .sortedWith(compareBy({ !it.measurable }, { it.tier }, { it.nameEn }))
            .firstOrNull()
    }

    /**
     * Skills barra has verified: measurable ones whose standard - reps at a
     * quality, on enough separate days - the athlete's measured sessions met.
     */
    fun verifiedFrom(days: List<DayEntry>): Set<String> =
        nodes.values.filter { it.measurable && it.standard != null }.filter { skill ->
            val std = skill.standard!!
            days.count { d ->
                val m = d.byMovement[skill.id]
                m != null && m.reps >= std.reps && (m.score ?: -1) >= std.quality
            } >= std.days
        }.map { it.id }.toSet()

    companion object {
        const val VERIFIED = "verified"
        const val CLAIMED = "claimed"
        const val AVAILABLE = "available"
        const val LOCKED = "locked"

        @Volatile private var cached: SkillGraph? = null

        fun load(context: Context): SkillGraph = cached ?: synchronized(this) {
            cached ?: parse(context.assets.open("skills.json").bufferedReader().readText())
                .also { cached = it }
        }

        fun parse(text: String): SkillGraph {
            val root = JSONObject(text)
            val fam = root.optJSONObject("families")
            val families = fam?.keys()?.asSequence()?.associateWith { fam.getString(it) }.orEmpty()
            val arr = root.getJSONArray("skills")
            val nodes = (0 until arr.length()).map { i ->
                val o = arr.getJSONObject(i)
                val req = o.getJSONArray("requires")
                val std = o.optJSONObject("standard")
                SkillNode(
                    id = o.getString("id"),
                    name = o.getString("name"),
                    family = o.getString("family"),
                    nameEn = o.optString("nameEn", o.getString("name")),
                    requires = (0 until req.length()).map { req.getString(it) },
                    tier = o.getInt("tier"),
                    measurable = o.getBoolean("measurable"),
                    standard = std?.let { Standard(it.getInt("reps"), it.getInt("quality"), it.getInt("days")) },
                )
            }.associateBy { it.id }
            return SkillGraph(nodes, families)
        }
    }
}
