#!/usr/bin/env python3
"""Render the skill graph as a standalone page.

Generated from barra/skills.py rather than hand-drawn, so the picture cannot
drift from the graph the app actually reasons over - a skill tree that has
quietly stopped matching the code is worse than no picture.

    python scripts/skill_tree.py [out.html]

Layout is a layered DAG: tier left to right (tier is the longest path from a
root, so nothing sits before its own prerequisite), family in horizontal bands.
Drawn as a transit map rather than the usual constellation-of-glowing-orbs,
because that is what the thing actually is - named stations, fixed routes, and
interchanges where two lines meet.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from barra.skills import (MEASURED, SKILLS, families, state, tiers,  # noqa: E402
                          unlocks, validate)

FAMILY_ORDER = ["push", "pull", "bar", "core", "balance", "legs"]
FAMILY_NAME = {"push": "Push", "pull": "Pull", "bar": "Bar",
               "core": "Core & levers", "balance": "Balance", "legs": "Legs"}

COL_W, ROW_H, BAND_GAP = 196, 44, 34
PAD_X, PAD_Y = 150, 56
# The deepest tier's labels extend to the RIGHT of their marker, so the
# canvas needs room for a name, not just for the node.
LABEL_ROOM = 210

# An example athlete, clearly labelled as one on the page. The real corpus has
# nothing verified yet, and a page whose first frame is 88 grey dots shows
# nothing about what it does.
EXAMPLE_VERIFIED = ["push_up", "pull_up", "dip", "squat"]
EXAMPLE_CLAIMED = ["chest_to_bar", "l_sit", "explosive_pull_up",
                   "chest_to_wall_handstand", "skin_the_cat"]


def layout() -> tuple[dict, int, int, list[dict]]:
    t = tiers()
    fams = families()
    max_tier = max(t.values())

    bands, y = [], PAD_Y
    pos: dict[str, tuple[float, float]] = {}
    for fam in FAMILY_ORDER:
        ids = fams.get(fam, [])
        by_tier: dict[int, list[str]] = {}
        for sid in ids:
            by_tier.setdefault(t[sid], []).append(sid)
        for col in by_tier.values():
            col.sort(key=lambda s: SKILLS[s].name)
        rows = max((len(v) for v in by_tier.values()), default=1)
        height = rows * ROW_H
        for tier, col in by_tier.items():
            # Centre each tier's nodes inside the band so a lone skill sits on
            # the band's spine rather than pinned to its top edge.
            top = y + (height - len(col) * ROW_H) / 2
            for i, sid in enumerate(col):
                pos[sid] = (PAD_X + tier * COL_W, top + i * ROW_H + ROW_H / 2)
        bands.append({"family": fam, "name": FAMILY_NAME[fam],
                      "top": y - 14, "height": height + 28})
        y += height + BAND_GAP

    width = PAD_X + max_tier * COL_W + LABEL_ROOM
    return pos, width, int(y + PAD_Y - BAND_GAP), bands


def build() -> dict:
    problems = validate()
    if problems:
        raise SystemExit("skill graph is not sound:\n  " + "\n  ".join(problems))

    pos, width, height, bands = layout()
    t, rev = tiers(), unlocks()
    nodes = [{
        "id": s.id, "name": s.name, "family": s.family, "tier": t[s.id],
        "x": round(pos[s.id][0], 1), "y": round(pos[s.id][1], 1),
        "measurable": s.measurable,
        "standard": (f"{s.standard.reps} verified reps at {s.standard.quality}+ "
                     f"on {s.standard.days} separate days") if s.standard else None,
        "requires": list(s.requires), "unlocks": list(rev[s.id]), "note": s.note,
    } for s in SKILLS.values()]
    edges = [{"from": r, "to": s.id, "family": SKILLS[r].family}
             for s in SKILLS.values() for r in s.requires]
    return {"nodes": nodes, "edges": edges, "bands": bands,
            "width": width, "height": height,
            "measured": list(MEASURED),
            "example": {"verified": EXAMPLE_VERIFIED, "claimed": EXAMPLE_CLAIMED}}


PAGE = """<title>Calisthenics Skill Graph</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700&family=Archivo+Narrow:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
:root {
  --ground:#F3F6F8; --surface:#FFFFFF; --sunk:#E7ECF1;
  --line:#C4CDD6; --ink:#121B23; --muted:#4C5B69; --faint:#8A99A8;
  --verified:#14618E; --verified-ink:#FFFFFF;
  --f-push:#A9503A; --f-pull:#14618E; --f-bar:#6E4894;
  --f-core:#1B6E60; --f-balance:#96701C; --f-legs:#55646F;
  --shadow:0 1px 2px rgba(18,27,35,.08), 0 8px 24px rgba(18,27,35,.06);
}
:root:not([data-theme="light"]) { }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --ground:#0C1218; --surface:#141D25; --sunk:#1D2933;
    --line:#2B3945; --ink:#DEE6ED; --muted:#9AACBB; --faint:#6B7C8B;
    --verified:#74B7E0; --verified-ink:#04202D;
    --f-push:#DE8F76; --f-pull:#74B7E0; --f-bar:#B394D6;
    --f-core:#5FB8A8; --f-balance:#D6B15C; --f-legs:#93A4B2;
    --shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.35);
  }
}
:root[data-theme="dark"] {
  --ground:#0C1218; --surface:#141D25; --sunk:#1D2933;
  --line:#2B3945; --ink:#DEE6ED; --muted:#9AACBB; --faint:#6B7C8B;
  --verified:#74B7E0; --verified-ink:#04202D;
  --f-push:#DE8F76; --f-pull:#74B7E0; --f-bar:#B394D6;
  --f-core:#5FB8A8; --f-balance:#D6B15C; --f-legs:#93A4B2;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.35);
}

* { box-sizing:border-box; }
body { margin:0; background:var(--ground); color:var(--ink);
  font-family:Archivo,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  font-size:15px; line-height:1.5; }
.wrap { max-width:1500px; margin:0 auto; padding:34px 26px 60px; }

header { display:flex; flex-wrap:wrap; gap:26px 40px; align-items:flex-end;
  justify-content:space-between; padding-bottom:20px;
  border-bottom:1px solid var(--line); }
.eyebrow { font-family:"Archivo Narrow",Archivo,sans-serif; font-size:12px;
  font-weight:600; letter-spacing:.14em; text-transform:uppercase;
  color:var(--faint); margin:0 0 6px; }
h1 { font-size:clamp(28px,4vw,40px); font-weight:700; letter-spacing:-.02em;
  margin:0; text-wrap:balance; }
.sub { color:var(--muted); margin:8px 0 0; max-width:60ch; }

.counts { display:flex; gap:28px; }
.count b { display:block; font-family:"JetBrains Mono",monospace;
  font-size:26px; font-weight:500; font-variant-numeric:tabular-nums;
  letter-spacing:-.02em; }
.count span { font-family:"Archivo Narrow",Archivo,sans-serif; font-size:11px;
  font-weight:600; letter-spacing:.12em; text-transform:uppercase;
  color:var(--faint); }
.count.hero b { color:var(--verified); }

/* The claim this page must not let anyone misread. */
.premise { margin:22px 0 0; padding:14px 18px; background:var(--sunk);
  border-left:3px solid var(--verified); border-radius:0 6px 6px 0;
  color:var(--muted); font-size:14px; max-width:88ch; }
.premise b { color:var(--ink); }

.bar { display:flex; flex-wrap:wrap; gap:10px 18px; align-items:center;
  margin:22px 0 14px; }
.seg { display:flex; background:var(--sunk); border-radius:7px; padding:3px;
  gap:3px; }
.seg button { font:inherit; font-size:13px; font-weight:500; border:0;
  background:transparent; color:var(--muted); padding:6px 14px;
  border-radius:5px; cursor:pointer; }
.seg button[aria-pressed="true"] { background:var(--surface); color:var(--ink);
  box-shadow:0 1px 2px rgba(0,0,0,.12); }
.seg button:focus-visible { outline:2px solid var(--verified); outline-offset:1px; }
.hint { color:var(--faint); font-size:13px; }

.legend { display:flex; flex-wrap:wrap; gap:8px 20px; align-items:center;
  font-size:13px; color:var(--muted); }
.key { display:flex; align-items:center; gap:7px; }
.key i { width:15px; height:15px; border-radius:50%; flex:none; display:block; }
.k-ver { background:var(--verified); box-shadow:0 0 0 3px var(--ground),0 0 0 4.5px var(--verified); }
.k-cla { background:var(--surface); border:2.5px solid var(--muted); }
.k-ava { background:var(--surface); border:2px dashed var(--faint); }
.k-loc { background:var(--line); width:9px; height:9px; margin:0 3px; }

.stage { position:relative; margin-top:8px; border:1px solid var(--line);
  border-radius:10px; background:var(--surface); overflow-x:auto;
  overflow-y:hidden; box-shadow:var(--shadow); }
svg { display:block; }
.band rect { fill:var(--sunk); opacity:.5; }
.band text { fill:var(--faint); font-family:"Archivo Narrow",Archivo,sans-serif;
  font-size:11px; font-weight:600; letter-spacing:.13em; text-transform:uppercase; }
.tick { fill:var(--faint); font-family:"JetBrains Mono",monospace; font-size:10px; }
.edge { fill:none; stroke-width:1.5; opacity:.24; }
.edge.lit { opacity:1; stroke-width:2.6; }
.edge.dim { opacity:.07; }
.node { cursor:pointer; }
.node .hit { fill:transparent; }
.node .dot { stroke-width:2.2; }
.node text { font-family:"Archivo Narrow",Archivo,sans-serif; font-size:11.5px;
  font-weight:500; fill:var(--ink);
  /* Routes pass behind the names; a halo in the surface colour keeps them
     readable without hiding the line. */
  paint-order:stroke; stroke:var(--surface); stroke-width:3.5px;
  stroke-linejoin:round; }
.node.locked text { fill:var(--faint); }
.node.dim { opacity:.16; }
.node.sel text { font-weight:600; }
.node:focus { outline:none; }
.node:focus-visible .dot { stroke:var(--ink); stroke-width:3; }
.ring { fill:none; stroke:var(--verified); stroke-width:1.6; opacity:.9; }

.panel { margin-top:16px; display:grid; gap:14px;
  grid-template-columns:repeat(auto-fit,minmax(270px,1fr)); }
.card { background:var(--surface); border:1px solid var(--line);
  border-radius:9px; padding:16px 18px; }
.card h3 { margin:0 0 3px; font-size:17px; font-weight:600;
  letter-spacing:-.01em; }
.card .meta { font-family:"JetBrains Mono",monospace; font-size:11.5px;
  color:var(--faint); margin:0 0 12px; }
.card ul { margin:0; padding-left:17px; color:var(--muted); font-size:13.5px; }
.card li { margin:2px 0; }
.card .none { color:var(--faint); font-size:13.5px; margin:0; }
.tag { display:inline-block; font-family:"Archivo Narrow",Archivo,sans-serif;
  font-size:10.5px; font-weight:600; letter-spacing:.1em; text-transform:uppercase;
  padding:2.5px 8px; border-radius:4px; margin-bottom:9px; }
.tag.yes { background:var(--verified); color:var(--verified-ink); }
.tag.no { background:var(--sunk); color:var(--muted); }
.std { margin:9px 0 0; font-size:13.5px; color:var(--muted); }
.std b { color:var(--ink); font-family:"JetBrains Mono",monospace;
  font-weight:500; font-size:13px; }
footer { margin-top:34px; padding-top:18px; border-top:1px solid var(--line);
  color:var(--faint); font-size:13px; }
footer code { font-family:"JetBrains Mono",monospace; font-size:12px;
  background:var(--sunk); padding:1.5px 6px; border-radius:4px; color:var(--muted); }
@media (prefers-reduced-motion:no-preference) {
  .edge,.node { transition:opacity .18s ease; }
}
</style>

<div class="wrap">
  <header>
    <div>
      <p class="eyebrow">barra &middot; progression map</p>
      <h1>The calisthenics skill graph</h1>
      <p class="sub">Every skill in the sport, and every prerequisite between
      them. A graph rather than a tree, because a muscle-up is a pull-up and a
      dip joined by a transition &mdash; it has two parents, and forcing one
      would mean choosing which to pretend away.</p>
    </div>
    <div class="counts">
      <div class="count"><b id="c-total">0</b><span>skills</span></div>
      <div class="count hero"><b id="c-meas">0</b><span>barra can verify</span></div>
      <div class="count"><b id="c-edges">0</b><span>prerequisites</span></div>
      <div class="count"><b id="c-tiers">0</b><span>tiers deep</span></div>
    </div>
  </header>

  <p class="premise"><b>Six of these are measured. The rest are a map.</b>
  Barra verifies a skill by measuring reps from video against a published
  standard, and only six movements are in that vocabulary. Everything else is
  something you tell it, which unlocks what comes next and counts as
  <em>nothing</em> as evidence. The two are drawn differently on purpose.</p>

  <div class="bar">
    <div class="seg" role="group" aria-label="Whose progress to show">
      <button id="b-example" aria-pressed="true">Example athlete</button>
      <button id="b-real" aria-pressed="false">Your data</button>
    </div>
    <div class="legend">
      <span class="key"><i class="k-ver"></i>Verified &mdash; barra measured it</span>
      <span class="key"><i class="k-cla"></i>Claimed &mdash; you said so</span>
      <span class="key"><i class="k-ava"></i>Available</span>
      <span class="key"><i class="k-loc"></i>Locked</span>
    </div>
    <span class="hint">Click a skill to trace its route &middot; click again to claim it</span>
  </div>

  <div class="stage" id="stage"></div>

  <div class="panel">
    <div class="card" id="detail"></div>
    <div class="card" id="next"></div>
    <div class="card" id="status"></div>
  </div>

  <footer>Generated from <code>barra/skills.py</code> by
  <code>scripts/skill_tree.py</code> &mdash; the picture is drawn from the graph
  the app reasons over, so the two cannot drift apart.</footer>
</div>

<script>
const DATA = __DATA__;
const NODES = Object.fromEntries(DATA.nodes.map(n => [n.id, n]));
const SVG_NS = "http://www.w3.org/2000/svg";
const FAM = {push:"--f-push", pull:"--f-pull", bar:"--f-bar",
             core:"--f-core", balance:"--f-balance", legs:"--f-legs"};

let verified = new Set(DATA.example.verified);
let claimed  = new Set(DATA.example.claimed);
let selected = null;
let mode = "example";

const el = (t, a = {}) => {
  const n = document.createElementNS(SVG_NS, t);
  for (const k in a) n.setAttribute(k, a[k]);
  return n;
};
const famColor = f => `var(${FAM[f] || "--f-legs"})`;

function ancestors(id, out = new Set()) {
  for (const r of NODES[id].requires) if (!out.has(r)) { out.add(r); ancestors(r, out); }
  return out;
}
function descendants(id, out = new Set()) {
  for (const u of NODES[id].unlocks) if (!out.has(u)) { out.add(u); descendants(u, out); }
  return out;
}

/* Doing a skill implies its prerequisites - otherwise the map tells someone
   with a verified pull-up to go and work on a dead hang. Implied ones are
   claimed, never verified: they were inferred, not measured. */
function states() {
  const implied = new Set();
  for (const id of [...verified, ...claimed]) ancestors(id).forEach(a => implied.add(a));
  const isClaimed = new Set([...claimed, ...[...implied].filter(i => !verified.has(i))]);
  const done = new Set([...verified, ...isClaimed]);
  const out = {};
  for (const n of DATA.nodes) {
    out[n.id] = verified.has(n.id) ? "verified"
      : isClaimed.has(n.id) ? "claimed"
      : n.requires.every(r => done.has(r)) ? "available" : "locked";
  }
  return out;
}

function draw() {
  const st = states();
  const stage = document.getElementById("stage");
  stage.textContent = "";
  const svg = el("svg", {width: DATA.width, height: DATA.height,
                         viewBox: `0 0 ${DATA.width} ${DATA.height}`,
                         role: "img", "aria-label": "Calisthenics skill graph"});

  DATA.bands.forEach(b => {
    const g = el("g", {class: "band"});
    g.appendChild(el("rect", {x: 18, y: b.top, width: DATA.width - 36,
                              height: b.height, rx: 8}));
    const label = el("text", {x: 34, y: b.top + 17});
    label.textContent = b.name;
    g.appendChild(label);
    svg.appendChild(g);
  });

  const maxTier = Math.max(...DATA.nodes.map(n => n.tier));
  for (let t = 0; t <= maxTier; t++) {
    const x = 150 + t * 196;
    const tick = el("text", {x, y: 30, class: "tick", "text-anchor": "middle"});
    tick.textContent = "tier " + t;
    svg.appendChild(tick);
  }

  const lit = selected
    ? new Set([selected, ...ancestors(selected), ...descendants(selected)])
    : null;

  const edgeLayer = el("g");
  DATA.edges.forEach(e => {
    const a = NODES[e.from], b = NODES[e.to];
    const mx = (a.x + b.x) / 2;
    const p = el("path", {
      d: `M ${a.x + 7} ${a.y} C ${mx} ${a.y}, ${mx} ${b.y}, ${b.x - 7} ${b.y}`,
      stroke: famColor(e.family), class: "edge"});
    if (lit) p.classList.add(lit.has(e.from) && lit.has(e.to) ? "lit" : "dim");
    edgeLayer.appendChild(p);
  });
  svg.appendChild(edgeLayer);

  DATA.nodes.forEach(n => {
    const s = st[n.id];
    const g = el("g", {class: `node ${s}`, tabindex: "0", role: "button",
                       "aria-label": `${n.name}, ${s}`});
    if (lit && !lit.has(n.id)) g.classList.add("dim");
    if (selected === n.id) g.classList.add("sel");

    if (s === "verified") {
      g.appendChild(el("circle", {cx: n.x, cy: n.y, r: 9.5, class: "ring"}));
      g.appendChild(el("circle", {cx: n.x, cy: n.y, r: 6, class: "dot",
                                  fill: "var(--verified)", stroke: "var(--verified)"}));
    } else if (s === "claimed") {
      g.appendChild(el("circle", {cx: n.x, cy: n.y, r: 6, class: "dot",
                                  fill: "var(--surface)", stroke: famColor(n.family)}));
    } else if (s === "available") {
      g.appendChild(el("circle", {cx: n.x, cy: n.y, r: 6, class: "dot",
                                  fill: "var(--surface)", stroke: "var(--faint)",
                                  "stroke-dasharray": "2.5 2.5"}));
    } else {
      g.appendChild(el("circle", {cx: n.x, cy: n.y, r: 3.4, fill: "var(--line)"}));
    }
    /* A small square behind the marker means barra can verify this one - the
       distinction has to survive being printed in greyscale. */
    if (n.measurable) {
      g.appendChild(el("rect", {x: n.x - 12.5, y: n.y - 12.5, width: 25, height: 25,
                                rx: 3, fill: "none", stroke: "var(--verified)",
                                "stroke-width": 1, opacity: .55}));
    }
    const label = el("text", {x: n.x + (n.measurable ? 17 : 12), y: n.y + 4});
    label.textContent = n.name;
    g.appendChild(label);
    g.appendChild(el("rect", {x: n.x - 14, y: n.y - 14, width: 150, height: 28,
                              class: "hit"}));

    const activate = ev => {
      ev.preventDefault();
      if (selected === n.id) {
        if (verified.has(n.id)) { verified.delete(n.id); }
        else if (claimed.has(n.id)) { claimed.delete(n.id); }
        else { claimed.add(n.id); }
      } else { selected = n.id; }
      render();
    };
    g.addEventListener("click", activate);
    g.addEventListener("keydown", e => {
      if (e.key === "Enter" || e.key === " ") activate(e);
    });
    svg.appendChild(g);
  });

  stage.appendChild(svg);
}

function detailCard(st) {
  const d = document.getElementById("detail");
  if (!selected) {
    d.innerHTML = `<h3>Pick a skill</h3><p class="meta">nothing selected</p>
      <p class="none">Click any station to see what it needs, what it opens,
      and whether barra can verify it. Click it again to claim it and watch the
      graph unlock.</p>`;
    return;
  }
  const n = NODES[selected], s = st[selected];
  const names = ids => ids.map(i => NODES[i].name);
  const list = (title, ids) => ids.length
    ? `<p class="meta" style="margin:10px 0 4px">${title}</p><ul>` +
      names(ids).map(x => `<li>${x}</li>`).join("") + "</ul>"
    : `<p class="meta" style="margin:10px 0 4px">${title}</p>
       <p class="none">none &mdash; this is a starting point</p>`;
  d.innerHTML =
    `<span class="tag ${n.measurable ? "yes" : "no"}">${
      n.measurable ? "barra can verify this" : "you tell barra"}</span>
     <h3>${n.name}</h3>
     <p class="meta">${n.family} &middot; tier ${n.tier} &middot; ${s}</p>
     ${n.standard ? `<p class="std">Standard: <b>${n.standard}</b></p>` : ""}
     ${n.note ? `<p class="std">${n.note}</p>` : ""}
     ${list("Requires", n.requires)}
     ${list("Opens", n.unlocks)}`;
}

function nextCard(st) {
  const ready = DATA.nodes.filter(n => st[n.id] === "available")
    .sort((a, b) => (a.measurable === b.measurable)
      ? (a.tier - b.tier || a.name.localeCompare(b.name))
      : (a.measurable ? -1 : 1)).slice(0, 6);
  document.getElementById("next").innerHTML =
    `<h3>What to work on</h3>
     <p class="meta">${ready.length ? "measurable first" : "nothing available"}</p>
     <ul>${ready.map(n => `<li>${n.name}${
       n.measurable ? " &mdash; <b>verifiable</b>" : ""}</li>`).join("")}</ul>`;
}

function statusCard(st) {
  const c = {verified: 0, claimed: 0, available: 0, locked: 0};
  Object.values(st).forEach(v => c[v]++);
  const vm = DATA.measured.filter(m => st[m] === "verified").length;
  document.getElementById("status").innerHTML =
    `<h3>${mode === "real" ? "Your data" : "Example athlete"}</h3>
     <p class="meta">${mode === "real"
       ? "from the eight clips in the repository"
       : "illustrative &mdash; not your figures"}</p>
     <ul>
       <li><b>${c.verified}</b> verified${
         mode === "real" && !c.verified
           ? " &mdash; 3 scored reps so far, no standard met yet" : ""}</li>
       <li><b>${c.claimed}</b> claimed or implied</li>
       <li><b>${c.available}</b> available now</li>
       <li><b>${c.locked}</b> still locked</li>
     </ul>
     <p class="std">${vm} of ${DATA.measured.length} verifiable movements
     confirmed by measurement.</p>`;
}

function render() {
  const st = states();
  draw();
  detailCard(st);
  nextCard(st);
  statusCard(st);
}

function setMode(m) {
  mode = m;
  selected = null;
  if (m === "example") {
    verified = new Set(DATA.example.verified);
    claimed = new Set(DATA.example.claimed);
  } else {
    verified = new Set();   // nothing in the corpus meets a standard yet
    claimed = new Set();
  }
  document.getElementById("b-example").setAttribute("aria-pressed", m === "example");
  document.getElementById("b-real").setAttribute("aria-pressed", m === "real");
  render();
}

document.getElementById("c-total").textContent = DATA.nodes.length;
document.getElementById("c-meas").textContent = DATA.measured.length;
document.getElementById("c-edges").textContent = DATA.edges.length;
document.getElementById("c-tiers").textContent =
  Math.max(...DATA.nodes.map(n => n.tier)) + 1;
document.getElementById("b-example").addEventListener("click", () => setMode("example"));
document.getElementById("b-real").addEventListener("click", () => setMode("real"));
render();
</script>
"""


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "out" / "skill_tree.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    data = build()
    out.write_text(PAGE.replace("__DATA__", json.dumps(data, separators=(",", ":"))))
    print(f"{len(data['nodes'])} skills, {len(data['edges'])} prerequisites, "
          f"{len(data['measured'])} measurable -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
