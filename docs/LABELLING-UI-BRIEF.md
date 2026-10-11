# Rep review — a design brief

For redesigning the labelling UI served by `scripts/label_reps.py --serve`.
Written to be worked from directly in Figma: every string, count and state
below is real, taken from the running tool on 2026-09-13.

---

## 1. What this screen is for

It produces the **golden dataset**. Every accuracy figure this repo reports is
measured against labels a person entered here. Nothing else in the project has
that property — the vision passes and the pose model are the things being
scored, so they cannot be the reference.

Two labels come out of it:

| Label | Grain | Goes to | Used by |
|---|---|---|---|
| **Movement** — which of 88 skills this is | per clip | `data/calisthenics/labels-adjudicated.csv` | `classify_eval.py`, `label_source_eval.py` |
| **Faults** — what went wrong | per rep | `out/fault-labels-human/<clip>.json` | `fault_eval.py` |

Today that CSV holds **92 rows and 0 verdicts**, and `out/fault-labels-human/`
is empty. The tool works; nobody has been able to face using it. That is the
design problem.

### The stake, stated plainly

**A label nobody looked at is worse than no label.** It is indistinguishable
from a real one downstream, and it silently corrupts every number measured
against it. The current UI makes producing those the path of least resistance
(see 4.1). The redesign's first job is to make attention visible and
inattention hard — not to make labelling faster.

---

## 2. Who uses it, and how the session actually goes

One person, the developer, on a laptop, alone, for 20–60 minutes at a stretch.
Not a crowd-work tool. No accounts, no permissions, no collaboration. It runs
on `127.0.0.1` from a local script and is never deployed.

The session is **repetitive and visually fatiguing**: the same five questions
against six near-identical stills, over and over. One clip in the current set
(`VID-20260827-WA0020`, a dip) has **19 reps × 5 faults = 95 tri-state
decisions on a single screen**.

Throughput matters, but only in second place. A design that doubles speed and
halves care makes the dataset worse.

---

## 3. The data the UI has to work with

Read from `out/rep-review/index.json`. Everything here is available to the
design; nothing else is.

### Per clip

```
clip          "VID-20260827-WA0020.mp4"
movement      "dip"                  ← editable, this is a label
declared      "dip"                  ← what it came in with, for comparison
kind          "reps" | "clip"
measurable    true                   ← barra can segment it into reps
hasRules      true                   ← fault rules exist for it
intendedFault ""                     ← if filmed deliberately, e.g. "shallow_depth"
subject       "diego"
angle         "frontal-anterior"
note          "declared in sessions.csv (2026-08-14, set 1)"
durationS     19.94                  ← clip-kind only
```

### Per rep (`kind: "reps"` only)

```
index    0
startS   2.13
endS     3.41
frames   6 JPEGs, 360px wide, sampled evenly across the rep
```

Whole-clip review gets **8 frames** across the clip instead, and no reps.

### The fault vocabulary — real content for your frames

Each fault has a short name and an `observable`: the exact phrasing the
geometric rule is written against. The wording is deliberate and should not be
paraphrased in the design — the point is that the human and the rule are
answering the *same* question.

**muscle_up — 7 faults**

| name | label | observable |
|---|---|---|
| `body_swing` | momentum | the hips travel more than the threshold, in torso-lengths, relative to the hands across the rep |
| `incomplete_lockout` | lockout | the shoulders' height above the hands at the top, as a share of the athlete's own arm reach |
| `incomplete_hang` | dead hang | the shoulders' depth below the hands at the start, as a share of the athlete's own arm reach |
| `dropped_descent` | control | the lowering phase lasts less than the threshold share of the lift |
| `lift_stall` | stall | the share of the lift, outside its first and last 10% of travel, spent making no progress |
| `slow_transition` | poor transition | seconds the shoulders spend within the bar plane during the lift |
| `incomplete_support_extension` | bent arms | the median elbow angle in the support window at the top of the rep |

**dip — 5 faults**

| name | label | observable |
|---|---|---|
| `incomplete_lockout` | lockout | the median elbow angle in the support window before lowering |
| `excessive_depth` | too deep | the median elbow angle in the turnaround window at the bottom |
| `bounce` | bounce at bottom | the slowest speed of the tracked point through the turnaround, in torso-lengths per second |
| `dropped_descent` | control | the lowering phase lasts less than the threshold share of the lift |
| `lift_stall` | stall | the share of the lift, outside its first and last 10% of travel, spent making no progress |

Each fault takes one of **three** values — `present` / `absent` / `unclear`.
Never two. "The camera angle hides the ankle" is a real answer, and collapsing
it into `absent` is how a harness manufactures agreement it has not got.

### The movement vocabulary

88 skills across 6 families (`push` 15, `pull` 13, `core` 22, `legs` 8,
`balance` 21, `bar` 9), plus *"— cannot tell from this clip —"*. Six of the 88
are measurable into reps; ten have fault rules. The picker must make a
90-option choice feel small.

---

## 4. The current screen, and what is wrong with it

One page, one clip at a time. Sticky header with a `<select>` of clips, a
status line and a **Save clip** button. Below it: a metadata line, the
movement bar, then a stack of rep cards — each with a title row, a horizontal
strip of 6 frames at 150px tall, and a grid of fault rows. A free-text
textarea at the bottom.

### 4.1 The defaults are the answer — the critical flaw

Every fault is pre-set before the reviewer looks at anything: the intended
fault to `present`, **everything else to `absent`**. That state is submitted
verbatim on Save.

So the fastest way to label 95 decisions is to click Save. The output is
indistinguishable from 95 considered judgements. Nothing in the UI, the file,
or any downstream consumer can tell them apart.

**This is the thing to fix.** Some directions, none of them settled:

- Start every fault *unanswered* and make unanswered visibly incomplete.
- Show progress as "37 of 95 answered", not as a clip count.
- Let a deliberate "all clean" be one explicit action, so it is a *choice*
  rather than an absence of one.
- Record per-rep whether the reviewer actually opened/viewed that rep.

The tension to design against: an honest tool is slower, and a tool too slow
to use produces no labels at all. 92 rows and 0 verdicts is what that failure
looks like.

### 4.2 Six stills is often not enough to judge

The questions are about *motion* — "the lowering phase lasts less than the
threshold share of the lift", "bounce at the bottom", "the hips travel
relative to the hands". Six 360px stills in a scrolling strip frequently
cannot answer them, and there is no video playback at all.

A reviewer who cannot tell should answer `unclear` — but `unclear` is
currently the least reachable of the three buttons, and `absent` is
pre-selected. The design should make the honest answer the easy one.

### 4.3 No keyboard path

Every one of those 95 decisions is a mouse click on a ~24px target. There are
no shortcuts, no focus model, no way to move between reps or faults from the
keyboard. This is the single biggest throughput win available and it is
entirely absent.

### 4.4 No sense of progress or position

The clip `<select>` reads `VID-20260827-WA0020.mp4 (dip, 19 reps)`. It does
not say which clips are done, which were skipped, or how much is left.
Finished clips look exactly like untouched ones.

### 4.5 Save auto-advances

On success the view jumps to the next clip. There is no undo, no confirmation,
and no way back to what you just submitted other than finding it in the
dropdown again.

### 4.6 A rep the segmenter invented cannot be rejected

If the segmenter produces a rep that is not one — or misses reps that are —
there is no way to say so. The reviewer can only answer fault questions about
a rep whose existence they may disagree with. This is a real case: one clip in
the set (`VID-20260827-WA0018`, a muscle-up) yields **zero** reps and now
falls back to whole-clip review, which records the movement but not the fact
that the segmentation failed.

### 4.7 The 88-item movement picker is a flat `<select>`

Grouped by family with `<optgroup>`, but still a 90-row dropdown. It is the
control most likely to be used *rarely and importantly* — most clips are
confirmed, a few are corrected, and the corrections are the valuable rows.

---

## 5. States to design

Please cover all of these. Several exist today with no design at all.

**Clip kinds**
1. **Rep clip** — movement bar + N rep cards with fault grids. Design for
   N = 1, and for N = 19.
2. **Whole-clip review** — movement bar + 8 frames + an explanation of why
   there are no fault questions. Three different reasons, each with its own
   copy:
   - *no reps were found* (measurable, segmenter returned nothing)
   - *barra cannot segment this movement* (has rules, not measurable)
   - *no fault rules exist for this movement yet* (neither)

**Movement labelling**
3. Movement **confirmed** (matches `declared`) — the quiet default.
4. Movement **changed** — a required "why" field appears. Currently an amber
   left border and a revealed input; Save is refused while it is empty, with
   the message *"say why the movement is different before saving"*.
5. Movement set to **"cannot tell from this clip"** — no reason required, and
   deliberately **not** written as a verdict.

**Feedback**
6. Saved — currently a text fragment: `saved · dip · bounce, lift_stall`.
7. Save refused for a missing reason.
8. Save failed (server down / write error).
9. Nothing extracted yet — the tool says *"nothing extracted yet - run
   --extract first"* on the console and the page never loads. Undesigned.

**Empty / edge**
10. A rep whose frames failed to extract (possible: frame extraction is
    best-effort and silently yields fewer than 6).
11. A clip already labelled, reopened.

---

## 6. Design system — please match, don't invent

This tool is developer-facing and currently has its own ad-hoc palette. The
**app** has a real design system, and matching it is preferred so the two read
as one product. Tokens are in `app/src/main/java/com/barrapp/ui/theme/Tracker.kt`.

```
bg       #0B0B12      ink     #F0EEFF
surface  #161626      muted   #7070A0
card     #1E1E32      border  #2A2A44
primary  #7C5DFA      teal    #22D3A5   ← good / absent
amber    #F59E0B      rose    #F43F5E   ← critical / present
```

Semantic mapping already in use, worth keeping: **rose = present** (a fault
was seen), **teal = absent**, **amber = unclear**.

Typefaces, all bundled in the app and on Google Fonts:

- **Barlow Condensed** (600/700/900) — display, headings, labels
- **Inter** (400/500/600) — body and UI
- **JetBrains Mono** (400/500/600) — timestamps, ids, counts, anything tabular

The current page is light-first with a dark media query. The app is dark-only.
Picking one is a decision for the designer; committing to dark would match the
app and suits long sessions looking at video stills.

---

## 7. Constraints that are not negotiable

- **Single static HTML file**, served from a Python `http.server` with one
  `POST /save` endpoint. It is a string constant (`PAGE`) inside
  `scripts/label_reps.py`. No build step, no npm, no framework.
- **No external network.** No CDN fonts, no CDN CSS. Anything needed must be
  inlined or already on the machine. (The app's font files are in the repo at
  `app/src/main/res/font/`.)
- Frames are served as plain `<img>` from the review directory. Video playback
  would need the source clip served too — possible, currently not done.
- One reviewer at a time. No realtime, no conflict resolution.

---

## 8. What "better" would mean

In rough priority:

1. A reviewer cannot submit a judgement they did not make.
2. `unclear` is as easy to reach as the other two answers.
3. A 19-rep clip is completable from the keyboard without the mouse.
4. It is obvious at all times how much is done and how much is left.
5. A movement correction, and its reason, feels worth the thirty seconds it
   takes — these are the highest-value rows in the dataset.
6. Judging motion from stills is as easy as it can be made — scrubbing,
   larger frames, before/after pairing, playback.

---

## 9. Open questions for the designer

- **How to show 19 reps.** One long scroll, a paged one-rep-at-a-time view, or
  a grid overview that expands? A paged view enforces attention but hides
  progress; a long scroll shows progress but invites a blind Save.
- **Should faults be per-rep or per-clip-with-exceptions?** Most sets are
  uniform — the same fault on most reps or none. Marking 19 reps individually
  may be the wrong interaction for the common case, while still being the
  right *grain* for the data.
- **Is the reason free text?** It is today. A structured cause — a dropdown of
  common confusions, or the decision-tree node where the classifier went wrong
  — would be far more analysable, at the cost of expressiveness.
- **Does `intendedFault` pre-marking stay?** It encodes a real prior (the set
  was filmed on purpose to show that fault) but it is still a default that
  becomes an answer. See 4.1.

---

## 10. Where to look

| | |
|---|---|
| The tool | `scripts/label_reps.py` (`PAGE` is the HTML) |
| Run it | `python scripts/label_reps.py --extract` then `--serve --port 8760` |
| Sample data | `out/rep-review/index.json` — 8 clips, 4 rep-kind, 4 whole-clip |
| Movement vocabulary | `barra/skills.py` — 88 skills |
| Decision tree | `barra/movement_tree.py` — 23 questions, the same vocabulary |
| Fault vocabulary | `barra/rules.py` — 10 movements |
| App design system | `app/src/main/java/com/barrapp/ui/theme/Tracker.kt` |
| Why holds differ | `barra/holds.py` |
