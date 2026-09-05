# The app

## Screens

```
Privacy ─▶ Onboarding ─▶ Home ─┬─ Processing (during an upload)
          (name, age,          └─ Coach
           activity)
```

**Home** is an adaptive three-pane shell with one rule: below `840dp` of window
width the panes are shown one at a time with a bottom bar; at or above it they
sit side by side. They are the same composables either way, so a fix lands in
both. The breakpoint is measured from the window rather than the device, so a
split-screen phone gets the compact layout.

| Pane | What it holds |
|---|---|
| Calendar (left) | The training month. A filled dot is a measured day; an **outline** is a day you filmed where nothing came out. Below it, the month's sessions with reps and score. |
| Session (centre) | The empty state, an in-flight upload, or a measured session: header, every rep with its score broken into components, the read-out, and what is held back. |
| Progress (right) | Sessions with enough reps to compare, the score trend, the weekly review, and the way in to the coach. |

## The upload

One tap from picking a clip to a measured session. The exercise is **not** asked
for.

```
pick clip ─▶ upload ─▶ detect the movement ─▶ trim to the working set
          ─▶ count and measure reps ─▶ session appears on the calendar
```

The four stages are named on screen instead of a percentage. Upload progress to
an S3 pre-signed URL followed by server-side pose estimation has no honest
percentage, and a bar that sits at 90% is worse than a list you can read.

### The figure

Above the stage list a stick athlete does the movement the app is named after,
over a bar, with its own shoulder trace scrolling underneath - drawn on a
`Canvas` in `ui/parts/Figure.kt`, no image assets. It is the loading animation
and it is not decoration: each stage changes what the drawing does, in the
terms the pipeline works in.

| stage | what the figure does |
|---|---|
| Uploading | works the bar; nothing measured yet |
| Finding the exercise | the hands are bracketed - they are the reference everything else is measured against |
| Trimming | the trace appears, faint, with trim markers sliding in from either edge |
| Counting and measuring | the trace turns live and each lockout is marked and counted |

Under the active stage a line rotates every four seconds, and a seconds counter
sits in the corner, because "still working" at two minutes is a different fact
from "still working" at ten. The same figure, idle and slower, is the empty
state's illustration.

### The voice

Every line the app says on its own initiative lives in `Voice.kt`, which is
Android-free so the logic tests can execute it. One rule governs all of it: a
line must be true whatever the clip turns out to show. "Counting reps.
Counting them honestly, which sometimes means fewer" is safe; "looking good" is
not, because it may not be. The test enumerates every table and every
generated line and asserts none contains a claim word (`great`, `improving`,
`you're ready`, ...). Lines rotate by a seed - the job id, the day of the
year - so a screen does not change its mind while you look at it.

When a result lands the home screen gets one buzz and one line, then the line
leaves after six seconds. It only says what the payload proves: a count, and
whether anything scored.

## The score, and what it is not

Each rep gets a **baseline proxy** out of 100, from three components fixed in
`barra/quality.py` before any clip was scored:

| Component | Weight | Measures |
|---|---|---|
| Range | 40% | Hang depth and lockout height, against arm reach measured in the same clip |
| Control | 25% | Whether the descent was lowered or dropped |
| Smoothness | 35% | How much of the ascent made no progress |

Swing and left/right asymmetry are measured and shown **beside** the score,
never folded into it. They are horizontal quantities, so including them would
make the number depend on where the phone was standing — the failure documented
in [`FINDINGS.md`](FINDINGS.md). The three components that are included are
vertical or temporal, and rotating a camera about the vertical axis does not
foreshorten vertical distances.

A rep that could not be measured shows an **em dash and its reason**, never a
low score. A pose failure is not bad technique, and marking it as one would be
the most misleading thing the app could do.

The proxy has no null distribution behind it. It cannot say whether a change
exceeds your own rep-to-rep variation — that is `barra progress`, and the app
says so wherever it shows a difference.

## A hold is a result

A clip that sits still used to reach the athlete as "not a set", which is true
and useless. The server now names the position and times it - dead hang,
flexed hang, inverted hang, front or back lever, handstand, plank, L-sit,
support hold - and the session shows the seconds where the score ring would
be. Time held is the measurement; how straight the line was is an angle in the
image, and `FINDINGS.md` shows a few degrees of camera position move that more
than technique does, so there is no score. The calendar paints a held day as a
filled dot in the unscored colour: something came out of it, and it was not a
score. How the geometry decides, and what has and has not been checked on
real footage, is in `CORE.md`.

## Techniques, quoted

Below the Improve panel, and on the Plan page under the next step, a card
says what the movement is *for*: cues, common faults, the muscles it works.
None of it is the app's opinion. `scripts/scrape_techniques.py` collects it
from openly licensed sources (free-exercise-db, wger, Wikipedia, CC-licensed
YouTube captions), keeps the licence and the record on every line, and mines
cues from the text by sentence shape. The card says "quoted, not measured" and
names the source, because the measured faults - the ones in the Improve panel
- are a different kind of fact and the two must never blur.

The app reads `assets/techniques.json`, a compact copy of
`data/techniques/techniques.json` (name, up to four cues, three faults,
muscles, sources). It is bundled so the card works offline and cannot be
changed by the server.

## The coach

Answers are arithmetic over the sessions already on the phone, not a model call.
That is a deliberate constraint: it means the coach physically cannot invent a
PR, a trend, or a technique diagnosis. Questions outside what the data supports
get told so, along with the questions it can answer.

The server's prose model still writes the per-clip read-out, where the payload it
is handed bounds what it can say.

## Data on the phone

| Where | What |
|---|---|
| `ProfileStore` | Name, age, activity. Never leaves the device. |
| `SessionStore` | The calendar, per-movement verified reps, chat history, last review time. |
| `DeviceId` | A random id. No account, no email, no Google sign-in. |

The server is the source of truth for measurements, but the calendar paints from
the local store so it works offline and instantly. Nothing is invented locally
that the server did not measure.

---

## The progression verdict

The first thing on the progress pane, because it is the decision the athlete
came for: *am I ready for the next progression, or do I just feel ready?* The
reasoning for putting this at the centre of the product is in
[`MARKET.md`](MARKET.md) — briefly, it is the decision calisthenics turns on,
it is currently made by feel, and no app in the market referees it.

> **Working towards** — **Muscle-up** · from pull-up
> **5** of 8 verified reps
> *Verified means barra measured the rep — not that you performed it. A rep it
> could not measure is not counted either way.*
>
> **The standard** — 8 verified reps in one session at 60 or better, on 2
> separate days. *A convention, not a measurement. It is written down so you
> can disagree with it.*
>
> **Your evidence** — Best session: 5 verified reps at 78 (solid) on 14 Aug.
> 0 of 2 days clear the standard.
>
> Still needed: 3 more verified reps in one session, and 2 more qualifying days.

The card is laid out so the two halves cannot be confused, because that
distinction *is* the product:

- **Whether a rep counts is measured.** Segmented, survived the plausibility
  checks, scored. Every one carries a trace id you can replay.
- **How many reps earn the step is a convention.** The ladder in
  `Progression.kt` is a published standard sitting close to the rule the sport
  already uses. It is stated on the card so it can be argued with.

The app never says "you are ready" on its own authority. It says what the
standard is, what you have, and what is missing.

Two consequences worth stating:

- **The ladder says where it stops.** Barra cannot verify added load or tell a
  pistol squat from a two-legged one, so those steps are marked unmeasurable
  and the card says the refereeing ends there rather than implying it continues.
- **Unverified reps never count.** A rep the segmenter proposed and the anchor
  test rejected is not a rep you did badly — it is a rep barra did not measure,
  and adding the two together would punish you for the camera.

## What the session write-up says

The numbers live on the rep cards. The write-up above them says what they
amount to, because "how did that go?" is the question someone opens the app to
ask and a list of timings in capital letters does not answer it.

> **2 muscle-up reps, solid**
> 2 muscle-up reps across a 13-second working set. Scored 78 out of 100 —
> solid. Three reps is the floor before a session median means anything, so
> treat this as a single observation rather than a session. The weakest part
> was smoothness through the rep at 67% (31% of the ascent made no progress);
> control of the descent was the strongest at 87%.

Four rules it works under:

- **Name the weakest part, with the measurement behind it.** That is the one
  sentence of any report that gets acted on.
- **Never compare against another session.** One clip cannot support a
  comparison; that is the weekly review's job, and only when the evidence
  clears the noise.
- **Count what could not be scored.** A set of six must never quietly present
  a number built from two.
- **A clip that measured nothing is still a result** — the reason, then what to
  change, never an apology:

> **No movement barra can measure**
> Barra could not tell what this clip shows. The hands were only tracked in
> 31% of the clip — they are out of frame for most of it. Tilt the camera up or
> step back so your hands stay in shot for the whole set — they are the
> reference everything else is measured against.

The advice comes from the *first* blocker the pipeline hit, not from whichever
blocker happens to match a keyword first. A clip whose real problem was the
athlete walking around the rig used to be told to keep the turnaround in frame.

## The weekly review

WorkManager, Monday morning, and **only when there is something to report** — a
notification that arrives whether or not you trained is one people turn off in
a fortnight. Composed on the phone from local sessions, so it works offline and
can only state what was measured. The in-app card shows the same text as the
notification.

> **Diego — 3 sessions this week**
> 28 reps measured across 3 days. Push-up (19 reps over 1 day) and muscle-up
> (9 reps over 2 days). 3 sessions cleared the 3-rep floor. Scores held level
> within their own spread. Best day was 26 Aug at 94 (strong). Volume is up
> from 6 reps the week before. 1 session produced no measurable reps — worth
> checking the framing on those clips.

The volume comparison is a **count**, so it is sound in a way the score
comparison is not — but it still stays silent when the previous week has
nothing in it, because "up 100%" from a week you did not train is not
information. The score line keeps its guard: under 8 points it reports level,
and over it says plainly that the change has not been tested against your own
rep-to-rep variation.

## When something goes wrong on a phone

There is a **Diagnostics** screen two taps from anywhere: the ⓘ in the app
header opens the privacy screen, which has a **Diagnostics** button at the
bottom. It is behind privacy rather than in the main navigation because it is
not a feature — it is what you reach for when something looks wrong. It exists
because the alternative — a user saying "it didn't work" and a developer with
no way to find out which run they mean — is not debuggable.

It shows:

- **the last trace id**, and the literal command to run against it:
  `barra explain --replay 260828-221455-4f8a59`
- **the provenance stamp** — which build and which pose model produced that
  answer
- **device, server and event count**
- **the event log**: the last 120 uploads, failures, lost connections,
  timeouts, completions and deletes, newest first, with INFO/WARN/ERROR levels
- **Copy report**, which renders all of the above as a paste-able block

The report deliberately carries no personal data: device model, API base,
Android build, and the events. Not the name, age, or any clip.

The id is the whole trick. The server writes a trace under an id, returns that
id in the payload, the app stores it with the session and shows it here, and
the CLI replays it. One id, four places, so a complaint about a specific number
leads to the exact run that produced it rather than to a re-run that may not
reproduce it. The full chain: [`docs/DEBUGGING.md`](DEBUGGING.md).

## Building, and what is verified

The Android SDK **cannot be downloaded in the Claude Code sandbox**
(`dl.google.com` is blocked by the network policy), so the Kotlin in this repo
was not compiled there. To build it properly:

```bash
source scripts/env.sh
./gradlew assembleDebug
```

Verification runs in three tiers, strongest first.

**Tier 1 — RUN.** `tools/run_logic_tests.sh` compiles the coach's answers, the
weekly review's arithmetic, the progression referee and the app's voice and
**executes** them on a plain JVM. 875 checks. This is why `Coach.answer` takes
measurements rather than the UI state, why `ReviewText` is split out of the
Worker, why `ProfileStore` is split out of `Profile`, and why `Voice` is a
plain object — the logic was made Android-free so it could be run.

**Tier 2 — TYPE-CHECK.** The data layer against a real `android.jar` (API 35,
from a GitHub mirror): `SharedPreferences`, `JSONObject`, `Uri`, okhttp. This
resolves real signatures, so a wrong method or a null-safety mistake is caught.

**Tier 3 — PARSE.** The Compose UI. androidx genuinely cannot be fetched —
`maven.google.com` 301s to `dl.google.com`, which the network policy blocks, and
every Google-repo mirror is blocked too. So the UI is checked for syntax and
structure only, plus the import linter.

What each tier does and does not cover:

**Kotlin parser** — the real `kotlin-compiler-embeddable`, run without the
Android classpath.

- catches: syntax errors, unbalanced braces, malformed declarations, conflicting
  overloads, bad modifiers, duplicate definitions.
- cannot catch: anything needing androidx types. Every `androidx` symbol is
  unresolved, so type mismatches and inference failures are filtered as noise.
- verified against a deliberately broken file before being trusted.

**Import linter** — [`tools/check_imports.py`](../tools/check_imports.py).

```bash
python tools/check_imports.py $(find app/src/main/java -name '*.kt')
```

- catches: a Compose or Android symbol used without its import — which the
  parser *cannot* see, because without the classpath a missing import looks
  identical to a present one.
- covers a curated list of ~90 common symbols, not everything.
- verified by deleting a real import and confirming it was reported.

**Python side** — fully run and tested: 57 tests, and the whole server pipeline
executed on the four real muscle-up clips plus a missing-file case, checking that
every key the Kotlin client reads is present on every path.

```bash
python -m unittest discover -s tests
```

## How close is the web replica to the real thing?

The replica shares the colour tokens (copied hex for hex from `Color.kt`), the
type scale, the layout structure, the 840dp breakpoint, the copy, the arithmetic
and the coach's answers. So the *composition* is what you will get.

What will differ on a device, and none of it is a bug:

- **Material 3 chrome.** The replica hand-draws approximations of the real
  components. The genuine `NavigationBar` puts a filled pill behind the active
  icon; `OutlinedTextField` floats its label into a notch in the border and is
  56dp tall; buttons have state layers and ripples. Expect those to look more
  finished than the replica, not less.
- **The system font.** The replica pulls Roboto from Google Fonts. A device uses
  its own system face, which on Samsung and some others is not Roboto.
- **Window insets.** The real app is edge-to-edge and pads for the status bar
  and gesture bar. The replica has no system bars to pad for.
- **Motion.** Onboarding slides horizontally between steps and the score ring
  counts up over 700ms; the replica renders both statically.

### The one real difference that WAS a bug

Everything inside a Compose `Canvas` is measured in **pixels, not dp**. Every
line this app draws - the rep trace, the chart axes, the floor line, the score
trend, the minimum bar height, the processing pulse - was written with bare
float literals, so on a 3x-density phone each would have rendered at a third of
its intended weight. Hairlines where there should be strokes, and a 1dp minimum
bar instead of 3dp, which quietly undid the fix that made one-rep sessions
visible in the first place.

The replica could never have caught this: a browser at 1x renders CSS pixels,
so it drew exactly what was intended. It was caught by asking whether the app
would really look like the replica, and checking rather than assuming. All of it
now converts through `DrawScope.toPx()`.

Three classes of defect these checks still do not cover, and which a real build
will surface first: runtime layout constraints, Compose API signature changes
across versions, and resource references. Two known layout traps were found and
fixed by reading (nested scrollables in one direction, a scroll index one past
the end); a third could remain.
