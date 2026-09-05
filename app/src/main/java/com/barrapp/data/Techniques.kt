package com.barrapp.data

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/**
 * The bundled technique ledger: `assets/techniques.json`, a compact copy of
 * `data/techniques/techniques.json` built by `scripts/scrape_techniques.py`.
 *
 * Read once, kept in memory. Twenty-odd records of a few sentences each, so
 * there is nothing to page. It is bundled rather than fetched so the card
 * works offline and the sample session has something to show; the server is
 * not involved, and cannot change what the phone says a movement is for.
 */
object Techniques {
    @Volatile
    private var cache: Map<String, Technique>? = null

    fun all(context: Context): Map<String, Technique> {
        cache?.let { return it }
        val loaded = runCatching { parse(context) }.getOrDefault(emptyMap())
        cache = loaded
        return loaded
    }

    /** The record for an exercise or skill id, or null. Holds pass their
     *  skill-graph id (`Hold.skill`), which the server already resolved. */
    fun forExercise(context: Context, id: String?): Technique? {
        if (id.isNullOrBlank()) return null
        return all(context)[id]
    }

    private fun parse(context: Context): Map<String, Technique> {
        val text = context.assets.open("techniques.json").bufferedReader().use { it.readText() }
        val skills = JSONObject(text).optJSONObject("skills") ?: return emptyMap()
        return skills.keys().asSequence().mapNotNull { id ->
            val e = skills.optJSONObject(id) ?: return@mapNotNull null
            id to Technique(
                id = id,
                name = e.optString("name").ifBlank { id.replace('_', ' ') },
                cues = e.optJSONArray("cues").strings(),
                faults = e.optJSONArray("faults").strings(),
                muscles = e.optJSONArray("muscles").strings(),
                sources = (e.optJSONArray("sources") ?: JSONArray()).let { arr ->
                    (0 until arr.length()).mapNotNull { arr.optJSONObject(it) }.map { s ->
                        TechniqueSource(
                            source = s.optString("source"),
                            title = s.optString("title"),
                            url = s.optString("url"),
                            license = s.optString("license"),
                        )
                    }
                },
            )
        }.toMap()
    }

    private fun JSONArray?.strings(): List<String> {
        if (this == null) return emptyList()
        return (0 until length()).map { optString(it) }.filter { it.isNotBlank() }
    }
}
