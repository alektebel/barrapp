# barrapp — Simpler feedback and the skill path

> 2026-10-11. Two changes to what the athlete sees: (A) instead of a wall of
> per-rep detail, **the 3 things to improve, in priority order**; (B) **the
> graph of skills on the way to the one they want**. Tests first, in steps.

## A. Top 3 things to improve

**Today:** the results screen lists every detected fault with rep counts, then a
card per rep with its checks; the session sheet adds per-check tables. The
server already picks ONE primary fault (`fault_select.primary_from_assessments`:
consensus gate + normalised exceedance).

**Ranking — explainable, three keys in order:**
1. **Importance** — the coaching order per movement (`recommend.PRIORITY`):
   what to fix first because the rest depends on it (momentum before lockout,
   range before tempo). Today it covers 4 movements; extended to all 10 with
   the same convention, written in the open so it can be argued with.
2. **Prevalence** — share of judged reps that showed it (a fault on 9 of 10 reps
   outranks one on 3 of 10).
3. **Exceedance** — how far past the threshold the worst rep went.

Only faults that pass the existing consensus gate are candidates, so the list
never repeats one-rep pose jitter. Fewer than 3 is a valid answer; none is
"nada que corregir" — never padded.

### Steps
- **A1 (server):** `fault_select.top_fixes(per_rep_assessments, movement, n=3)` →
  `topFixes: [{rank, errorId, name, observedReps, judgedReps, exceedance}]` in
  the payload; `PRIORITY` extended to every movement with rules.
  *Tests:* ordering by each key; consensus gate; ties; ≤ 3; empty; payload
  contract key; `primaryFault` == `topFixes[0]` when both exist (one story).
- **A2 (app):** parse `topFixes`; results screen and session sheet lead with
  **"Lo que mejorar"** — 1, 2, 3, each with the Spanish name and cue the app
  already has (`faultEs`, `cueEs`) and "en N de M repeticiones". Per-rep cards
  and check tables move behind **"Ver detalle"** (collapsed by default).
  *Tests:* parsing; the card shows ≤ 3 in order; screenshot of both states.

## B. The skill path

**Today:** `barra/skills.py` holds the full skill DAG (~60 skills, prerequisites,
computed tiers, states VERIFIED / CLAIMED / AVAILABLE / LOCKED, 6 measurable).
The app only knows a 6-step ladder (`Progression.LADDER`).

### Steps
- **B1 (data):** `scripts/export_skills.py` writes the graph to
  `app/src/main/assets/skills.json` (id, Spanish name, family, requires, tier,
  measurable, standard). Spanish names live next to the graph
  (`barra/skills_es.py`). *Tests:* every skill has a Spanish name; the committed
  JSON equals a fresh export (so the app and the graph cannot drift); the DAG
  validates.
- **B2 (app logic):** `SkillGraph` loads the JSON; `pathTo(target)` = the target
  and all its prerequisites, by tier; states mirror `skills.state()`: VERIFIED
  only from barra's own measurements (a measured skill whose standard a session
  met), AVAILABLE when every prerequisite is done, else LOCKED. Self-report is
  never shown as verified. *Tests:* path of muscle-up includes pull-up and dip;
  states; unknown target.
- **B3 (app UI):** "Camino a {skill}" from the Progress tab: rows by tier,
  nodes coloured by state, edges between them, the next skill to work on
  highlighted; target = the goal from onboarding, changeable on the screen.
  *Tests:* screenshot; the next skill is an AVAILABLE ancestor.

## Delivery
A1 → deploy; A2 + B1–B3 → one APK, installed over wifi, checked on the phone.
