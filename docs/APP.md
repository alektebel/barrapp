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

## The coach

Answers are arithmetic over the sessions already on the phone, not a model call.
That is a deliberate constraint: it means the coach physically cannot invent a
PR, a trend, or a technique diagnosis. Questions outside what the data supports
get told so, along with the questions it can answer.

The server's prose model still writes the per-clip read-out, where the payload it
is handed bounds what it can say.

## Weekly review

WorkManager, Monday morning, weekly, and **only when there is something to
report** — a notification that arrives whether or not you trained is one people
turn off in a fortnight. Composed on the phone from local sessions, so it works
offline and can only state what was measured. The in-app card shows the same
text as the notification.

## Data on the phone

| Where | What |
|---|---|
| `ProfileStore` | Name, age, activity. Never leaves the device. |
| `SessionStore` | The calendar, per-rep metrics, chat history, last review time. |
| `DeviceId` | A random id. No account, no email, no Google sign-in. |

The server is the source of truth for measurements, but the calendar paints from
the local store so it works offline and instantly. Nothing is invented locally
that the server did not measure.

---

## Building, and what is verified

The Android SDK **cannot be downloaded in the Claude Code sandbox**
(`dl.google.com` is blocked by the network policy), so the Kotlin in this repo
was not compiled there. To build it properly:

```bash
source scripts/env.sh
./gradlew assembleDebug
```

Verification runs in three tiers, strongest first.

**Tier 1 — RUN.** `tools/run_logic_tests.sh` compiles the coach's answers and the
weekly review's arithmetic and **executes** them on a plain JVM. 40 checks. This
is why `Coach.answer` takes measurements rather than the UI state, why
`ReviewText` is split out of the Worker, and why `ProfileStore` is split out of
`Profile` — the logic was made Android-free so it could be run.

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

Three classes of defect these do not cover, and which a real build will surface
first: runtime layout constraints, Compose API signature changes across
versions, and resource references. Two of the three known layout traps were
found and fixed by reading (nested scrollables in one direction, a scroll index
one past the end); a third could remain.
