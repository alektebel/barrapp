package com.barrapp.ui.tracker

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
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
import com.barrapp.data.DayEntry
import com.barrapp.data.SkillGraph
import com.barrapp.ui.theme.T
import com.barrapp.ui.theme.Tk
import com.barrapp.ui.theme.body
import com.barrapp.ui.theme.mono

/** One skill on the path, ready to draw. */
data class SkillNodeUi(val id: String, val name: String, val state: String, val next: Boolean)

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
 * own: VERIFIED only from measured sessions) and the next skill to work on
 * (docs/UX-PLAN.md B2-B3).
 */
fun skillPathData(graph: SkillGraph, target: String, verified: Set<String>,
                  goal: String? = null): SkillPathData? {
    val path = graph.path(target)
    if (path.isEmpty()) return null
    val st = graph.state(verified, emptySet())
    val next = graph.nextOnPath(target, verified, emptySet())
    val onPath = path.map { it.id }.toSet()
    val ui = path.associate {
        it.id to SkillNodeUi(it.id, it.name, st[it.id] ?: SkillGraph.LOCKED, it.id == next?.id)
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

/** One step of the vertical path - design 2d's CAMINO DE SKILLS. */
data class PathStep(
    val id: String,
    val name: String,
    /** The human line under the name ("Completado", "Ahora: 5 reps …"). */
    val note: String = "",
    /** The SkillGraph state of this step. */
    val state: String = SkillGraph.LOCKED,
    /** The step to work on now: the path's one orange dot. */
    val next: Boolean = false,
    /**
     * What is still missing to meet this step, in words, without the
     * "Te falta: " prefix - the path adds it here, once in the whole app
     * (the design notes' B2). Null when nothing honest can be said.
     */
    val missing: String? = null,
)

/**
 * The graph's path as design 2d reads it: shallowest first, one human line
 * each, the next step marked. The standard of the next skill is already the
 * note; `missingFor` (see [missingForNext]) adds the "Te falta" line when the
 * caller can compute the real gap from the athlete's days.
 */
fun pathSteps(data: SkillPathData, missingFor: String? = null): List<PathStep> =
    data.rows.flatten().map { n ->
        val standard = if (n.next) data.nextStandard else null
        PathStep(
            id = n.id,
            name = n.name,
            note = when {
                n.state == SkillGraph.VERIFIED -> "Completado"
                n.state == SkillGraph.CLAIMED -> "Hecho"
                n.next -> when {
                    standard == null -> "Ahora"
                    standard.startsWith("barra todavía no mide") ->
                        "Ahora: barra todavía no la mide; trabájala en tus series"
                    else -> "Ahora: ${standard.substringBefore(". barra lo verifica")}"
                }
                else -> "Bloqueado hasta completar el anterior"
            },
            state = n.state,
            next = n.next,
            missing = if (n.next) missingFor else null,
        )
    }

/**
 * The gap to the next skill, from the athlete's measured days, in words: what
 * its standard still asks that the days do not show yet. Null when the step is
 * verified, has no measurable standard, or nothing is missing - the path stays
 * quiet instead of inventing a gap.
 */
fun missingForNext(graph: SkillGraph, next: SkillNodeUi?, days: List<DayEntry>): String? {
    val node = next?.let { graph[it.id] } ?: return null
    val std = node.standard?.takeIf { node.measurable } ?: return null
    if (next.state == SkillGraph.VERIFIED) return null
    val onDays = days.mapNotNull { it.byMovement[node.id] }
    val mostReps = onDays.maxOfOrNull { it.reps } ?: 0
    val bestScore = onDays.mapNotNull { it.score }.maxOrNull()
    val qualifying = onDays.count { it.reps >= std.reps && (it.score ?: -1) >= std.quality }
    val gaps = mutableListOf<String>()
    if (onDays.isEmpty()) {
        gaps += "todavía no hay repeticiones medidas de esta habilidad"
    } else {
        if (mostReps < std.reps) {
            val short = std.reps - mostReps
            gaps += "${if (short == 1) "1 repetición más" else "$short repeticiones más"} en una sesión (vas por $mostReps)"
        }
        if ((bestScore ?: -1) < std.quality) {
            gaps += "calidad ${std.quality} o más (mejor hasta ahora: ${bestScore ?: "sin puntuar"})"
        }
    }
    if (qualifying < std.days && onDays.isNotEmpty()) {
        val short = std.days - qualifying
        gaps += if (short == 1) "1 día más que cumpla" else "$short días más que cumplan"
    }
    if (gaps.isEmpty()) return null
    return gaps.joinToString(", y ")
}

/**
 * Order the nodes of each row to cut edge crossings: the barycenter heuristic
 * (each node goes under the mean position of its prerequisites in the rows
 * above), one pass down then one up, keeping the original order on ties.
 */internal fun orderRows(rows: List<List<String>>, edges: List<Pair<String, String>>): List<List<String>> {
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

private fun stateColor(state: String): Color = when (state) {
    SkillGraph.VERIFIED -> Tk.teal
    SkillGraph.CLAIMED -> Tk.tealA(0.45f)
    SkillGraph.AVAILABLE -> Tk.primary
    else -> Tk.faint
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
                    name, style = mono(10, 0.03f, if (on) Tk.onInk else Tk.ink),
                    modifier = Modifier.clip(RoundedCornerShape(50))
                        .background(if (on) Tk.ink else Tk.surface)
                        .border(1.5.dp, Tk.border, RoundedCornerShape(50))
                        .noRipple { onTarget(id) }
                        .padding(horizontal = 12.dp, vertical = 7.dp),
                )
            }
        }

        // Next step
        data.next?.let { n ->
            TkCard(modifier = Modifier.padding(top = 16.dp)) {
                Eyebrow("Siguiente paso")
                Text(n.name, style = T.cardHeadline, modifier = Modifier.padding(top = 6.dp))
                data.nextStandard?.let { Text(it, style = T.bodyS, modifier = Modifier.padding(top = 4.dp)) }
            }
        } ?: if (data.rows.lastOrNull()?.lastOrNull()?.state == SkillGraph.VERIFIED) {
            TkCard(modifier = Modifier.padding(top = 16.dp)) {
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
    }
}

private fun stepDot(s: PathStep): Color = when {
    s.state == SkillGraph.VERIFIED || s.state == SkillGraph.CLAIMED -> Tk.ink
    s.next -> Tk.primary
    else -> Tk.bg
}

/**
 * Design 2d's CAMINO DE SKILLS: the path as a vertical line of steps, each
 * with its mark - done (ink dot, check), next (the one orange dot) or locked
 * (paper dot, muted name). The next step carries the app's single
 * "Te falta: …" line; nothing else says it.
 */
@Composable
fun SkillPathSteps(steps: List<PathStep>, modifier: Modifier = Modifier) {
    Column(modifier.fillMaxWidth()) {
        steps.forEachIndexed { i, s ->
            Row(
                Modifier.fillMaxWidth().height(IntrinsicSize.Min),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Column(
                    Modifier.width(24.dp).fillMaxHeight(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Box(
                        Modifier.size(20.dp)
                            .clip(CircleShape)
                            .background(stepDot(s))
                            .border(2.dp, Tk.border, CircleShape),
                        contentAlignment = Alignment.Center,
                    ) {
                        if (s.state == SkillGraph.VERIFIED || s.state == SkillGraph.CLAIMED) {
                            Text("✓", style = mono(11, 0f, Tk.onInk, FontWeight.SemiBold))
                        }
                    }
                    if (i < steps.size - 1) {
                        Box(
                            Modifier.width(2.dp).weight(1f)
                                .background(if (s.state == SkillGraph.LOCKED) Tk.line else Tk.ink),
                        )
                    }
                }
                Column(Modifier.weight(1f).padding(bottom = 12.dp)) {
                    Text(
                        s.name,
                        style = T.rowTitle.copy(
                            color = if (s.state == SkillGraph.LOCKED) Tk.muted else Tk.ink,
                        ),
                    )
                    if (s.note.isNotBlank()) {
                        Text(s.note, style = body(13), modifier = Modifier.padding(top = 2.dp))
                    }
                    if (s.next && !s.missing.isNullOrBlank()) {
                        Text("Te falta: ${s.missing}", style = T.itemTitleSmall,
                            modifier = Modifier.padding(top = 3.dp))
                    }
                }
            }
        }
    }
}
