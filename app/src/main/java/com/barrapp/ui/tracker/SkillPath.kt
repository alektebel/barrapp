package com.barrapp.ui.tracker

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.LayoutCoordinates
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.barrapp.data.SkillGraph
import com.barrapp.data.DayEntry

import com.barrapp.ui.theme.T
import com.barrapp.ui.theme.Tk
import com.barrapp.ui.theme.mono

data class SkillNodeUi(
    val id: String,
    val name: String,
    val state: String,
    val next: Boolean,
    /** The skill's own estimated progression, when barra can measure it. */
    val progress: SkillProgressUi? = null,
)

/**
 * The progression towards one measurable skill: its standard, and where the
 * athlete stands against it from measured sessions only. `qualifyingDays`
 * counts only sessions with enough reps at the quality bar; `bestReps` and
 * `bestScore` are the best session so far, whatever the quality.
 */
data class SkillProgressUi(
    val reps: Int,
    val quality: Int,
    val days: Int,
    val qualifyingDays: Int,
    val bestReps: Int,
    val bestScore: Int?,
) {
    val done: Boolean get() = qualifyingDays >= days
}

data class SkillPathData(
    val targetId: String,
    val targetName: String,
    /** Rows by tier, shallowest first; the target is in the last row. */
    val rows: List<List<SkillNodeUi>>,
    /** (prerequisite, skill) - both on the path. */
    val edges: List<Pair<String, String>>,
    val next: SkillNodeUi?,
    /** What owning the next skill means, in words. */
    val nextStandard: String?,
    val targets: List<Pair<String, String>>,
)

/** Targets offered on the screen: the athlete's goal first, then the classics. */
private val CLASSIC_TARGETS = listOf(
    "muscle_up", "front_lever", "full_planche", "human_flag", "one_arm_pull_up",
    "freestanding_handstand", "pistol_squat", "one_arm_push_up",
)

/**
 * The path to `target`: every prerequisite, by tier, with its state (barra's
 * own: VERIFIED only from measured sessions), the next skill to work on, and
 * each measurable skill's estimated progression against its standard
 * (docs/UX-PLAN.md B2-B3).
 */
fun skillPathData(graph: SkillGraph, target: String, verified: Set<String>,
                  goal: String? = null,
                  all: List<DayEntry> = emptyList()): SkillPathData? {
    val path = graph.path(target)
    if (path.isEmpty()) return null
    val st = graph.state(verified, emptySet())
    val next = graph.nextOnPath(target, verified, emptySet())
    val onPath = path.map { it.id }.toSet()
    val ui = path.associate { s ->
        s.id to SkillNodeUi(s.id, s.name, st[s.id] ?: SkillGraph.LOCKED,
            s.id == next?.id, skillProgress(s, all))
    }
    val edges = path.flatMap { s -> s.requires.filter { it in onPath }.map { it to s.id } }
    val rows = orderRows(path.groupBy { it.tier }.toSortedMap().values.map { t -> t.map { it.id } }, edges)
        .map { row -> row.map { ui.getValue(it) } }
    val standard = next?.let { n ->
        val std = n.standard
        if (n.measurable && std != null)
            "${std.reps} repeticiones con calidad ${std.quality} o más, en ${std.days} días distintos. barra lo verifica con tus vídeos."
        else "barra todavía no mide esta habilidad: trabájala y sigue con el camino."
    }
    val targets = (listOfNotNull(goal) + CLASSIC_TARGETS).distinct()
        .mapNotNull { id -> graph[id]?.let { id to it.name } }
    return SkillPathData(target, graph[target]!!.name, rows, edges, next?.let { ui[it.id] }, standard, targets)
}

/**
 * One measurable skill's progression, from the athlete's measured days only.
 * A day qualifies when its verified reps meet the standard's volume at its
 * quality bar - the same rule SkillGraph.verifiedFrom referees with.
 */
internal fun skillProgress(skill: SkillGraph.SkillNode,
                           all: List<DayEntry>): SkillProgressUi? {
    val std = skill.standard ?: return null
    if (!skill.measurable) return null
    val days = all.mapNotNull { d -> d.byMovement[skill.id]?.let { it to (d.date to it) } }
        .map { it.first }.filter { it.verified > 0 }
    val best = days.maxByOrNull { it.verified * 1000 + (it.score ?: 0) }
    return SkillProgressUi(
        reps = std.reps, quality = std.quality, days = std.days,
        qualifyingDays = days.count { it.verified >= std.reps && (it.score ?: 0) >= std.quality },
        bestReps = best?.verified ?: 0,
        bestScore = best?.score,
    )
}

private fun stateColor(state: String): Color = when (state) {
    SkillGraph.VERIFIED -> Tk.teal
    SkillGraph.CLAIMED -> Tk.tealA(0.45f)
    SkillGraph.AVAILABLE -> Tk.primary
    else -> Tk.faint
}

/**
 * Order the nodes of each row to cut edge crossings: the barycenter heuristic
 * (each node goes under the mean position of its prerequisites in the rows
 * above), one pass down then one up, keeping the original order on ties.
 */
internal fun orderRows(rows: List<List<String>>, edges: List<Pair<String, String>>): List<List<String>> {
    val parents = edges.groupBy({ it.second }, { it.first })
    val children = edges.groupBy({ it.first }, { it.second })
    val out = rows.map { it.toMutableList() }.toMutableList()
    fun pos(): Map<String, Double> = out.flatMap { r ->
        r.mapIndexed { i, id -> id to (i + 0.5) / r.size }
    }.toMap()
    fun sweep(range: IntProgression, links: Map<String, List<String>>) {
        for (i in range) {
            val p = pos()
            val keyed = out[i].mapIndexed { idx, id ->
                val ref = links[id].orEmpty().mapNotNull { p[it] }
                Triple(id, if (ref.isEmpty()) p.getValue(id) else ref.average(), idx)
            }
            out[i] = keyed.sortedWith(compareBy({ it.second }, { it.third })).map { it.first }.toMutableList()
        }
    }
    sweep(1 until out.size, parents)
    sweep(out.size - 2 downTo 0, children)
    return out
}

/** How many pairs of edges between consecutive rows cross. For tests. */
internal fun crossings(rows: List<List<String>>, edges: List<Pair<String, String>>): Int {
    val where = rows.flatMapIndexed { r, row -> row.mapIndexed { i, id -> id to (r to (i + 0.5) / row.size) } }.toMap()
    val segs = edges.mapNotNull { (a, b) ->
        val pa = where[a] ?: return@mapNotNull null
        val pb = where[b] ?: return@mapNotNull null
        if (pb.first - pa.first == 1) Triple(pa.first, pa.second, pb.second) else null
    }
    var n = 0
    for (i in segs.indices) for (j in i + 1 until segs.size) {
        val (r1, a1, b1) = segs[i]; val (r2, a2, b2) = segs[j]
        if (r1 == r2 && (a1 - a2) * (b1 - b2) < 0) n++
    }
    return n
}


private fun stateLabel(state: String): String = when (state) {
    SkillGraph.VERIFIED -> "Verificada"
    SkillGraph.CLAIMED -> "Hecha"
    SkillGraph.AVAILABLE -> "Para trabajar"
    else -> "Bloqueada"
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun SkillPathScreen(data: SkillPathData, onTarget: (String) -> Unit, onClose: () -> Unit) {
    Column(Modifier.fillMaxWidth()) {
        Eyebrow("Camino a")
        Text(data.targetName.uppercase(), style = T.cardHeadline, modifier = Modifier.padding(top = 4.dp))

        // Target chips
        Row(
            Modifier.padding(top = 12.dp).horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            data.targets.forEach { (id, name) ->
                val on = id == data.targetId
                Text(
                    name, style = mono(10, 0.03f, if (on) Tk.bg else Tk.primaryLight),
                    modifier = Modifier.clip(RoundedCornerShape(50))
                        .background(if (on) Tk.primary else Tk.surface)
                        .border(1.dp, if (on) Tk.primary else Tk.border, RoundedCornerShape(50))
                        .noRipple { onTarget(id) }
                        .padding(horizontal = 12.dp, vertical = 7.dp),
                )
            }
        }

        // Next step
        data.next?.let { n ->
            TkCard(accent = true, modifier = Modifier.padding(top = 16.dp)) {
                Eyebrow("Siguiente paso")
                Text(n.name, style = T.cardHeadline, modifier = Modifier.padding(top = 6.dp))
                data.nextStandard?.let { Text(it, style = T.bodyS, modifier = Modifier.padding(top = 4.dp)) }
            }
        } ?: if (data.rows.lastOrNull()?.lastOrNull()?.state == SkillGraph.VERIFIED) {
            TkCard(accent = true, modifier = Modifier.padding(top = 16.dp)) {
                Text("Ya tienes ${data.targetName} verificada.", style = T.bodyInk)
            }
        } else Unit

        // The graph: rows by tier, edges drawn behind from each node's real bounds.
        var container by remember { mutableStateOf<LayoutCoordinates?>(null) }
        val bounds = remember(data.targetId) { mutableStateMapOf<String, Rect>() }
        Box(
            Modifier.padding(top = 20.dp).fillMaxWidth()
                .onGloballyPositioned { container = it }
                .drawBehind {
                    data.edges.forEach { (from, to) ->
                        val a = bounds[from] ?: return@forEach
                        val b = bounds[to] ?: return@forEach
                        drawLine(
                            color = if (from in bounds && data.rows.flatten().first { it.id == from }.state
                                in setOf(SkillGraph.VERIFIED, SkillGraph.CLAIMED)) Tk.tealA(0.5f) else Tk.border,
                            start = Offset(a.center.x, a.bottom),
                            end = Offset(b.center.x, b.top),
                            strokeWidth = 2.dp.toPx(),
                        )
                    }
                },
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(28.dp)) {
                data.rows.forEach { row ->
                    FlowRow(
                        Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceEvenly,
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        row.forEach { node ->
                            SkillChip(node, Modifier.onGloballyPositioned { c ->
                                container?.let { bounds[node.id] = it.localBoundingBoxOf(c) }
                            })
                        }
                    }
                }
            }
        }

        // Legend
        Row(Modifier.padding(top = 20.dp), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
            listOf(SkillGraph.VERIFIED, SkillGraph.CLAIMED, SkillGraph.AVAILABLE, SkillGraph.LOCKED).forEach { s ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(8.dp).clip(CircleShape).background(stateColor(s)))
                    Spacer(Modifier.size(5.dp))
                    Text(stateLabel(s), style = mono(9, 0.03f, Tk.muted))
                }
            }
        }
        Spacer(Modifier.height(20.dp))
        TkSecondaryButton("Volver", onClose)
    }
}

@Composable
private fun SkillChip(node: SkillNodeUi, modifier: Modifier = Modifier) {
    val color = stateColor(node.state)
    val filled = node.state == SkillGraph.VERIFIED || node.state == SkillGraph.CLAIMED
    Column(
        modifier.widthIn(max = 104.dp)
            .clip(RoundedCornerShape(8.dp))
            .background(if (filled) color.copy(alpha = 0.18f) else Tk.surface)
            .border(if (node.next) 2.dp else 1.dp, if (node.next) Tk.amber else color, RoundedCornerShape(8.dp))
            .padding(horizontal = 7.dp, vertical = 5.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        if (node.next) Text("SIGUIENTE", style = mono(8, 0.08f, Tk.amber))
        Text(
            node.name, textAlign = TextAlign.Center,
            style = T.bodyS.copy(
                color = if (node.state == SkillGraph.LOCKED) Tk.muted else Tk.ink,
                fontWeight = if (node.next) FontWeight.SemiBold else FontWeight.Normal,
                fontSize = androidx.compose.ui.unit.TextUnit(11f, androidx.compose.ui.unit.TextUnitType.Sp),
                lineHeight = androidx.compose.ui.unit.TextUnit(13f, androidx.compose.ui.unit.TextUnitType.Sp),
            ),
        )
        // The skill's own estimated progression, from measured sessions only.
        // Skills barra cannot measure show nothing: no invented bar.
        node.progress?.let { p ->
            Spacer(Modifier.height(4.dp))
            if (p.done) {
                Text("✓", style = mono(9, 0f, Tk.teal))
            } else if (p.bestReps > 0) {
                Text(
                    "${p.bestReps}/${p.reps} reps · ${p.qualifyingDays}/${p.days} días",
                    style = mono(8, 0.02f, if (node.state == SkillGraph.LOCKED) Tk.muted else Tk.primaryLight),
                )
            } else {
                Text(
                    "${p.reps} reps · ${p.days} días",
                    style = mono(8, 0.02f, if (node.state == SkillGraph.LOCKED) Tk.muted else Tk.faint),
                )
            }
            ProgressDots(p)
        }
    }
}

/** One dot per standard day: filled when the measured sessions earned it. */
@Composable
private fun ProgressDots(p: SkillProgressUi) {
    Row(horizontalArrangement = Arrangement.spacedBy(3.dp), modifier = Modifier.padding(top = 3.dp)) {
        repeat(p.days) { i ->
            Box(
                Modifier.width(7.dp).height(4.dp).clip(RoundedCornerShape(2.dp))
                    .background(if (i < p.qualifyingDays) Tk.teal else Tk.border),
            )
        }
    }
}
