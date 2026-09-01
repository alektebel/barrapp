# Where barra fits, and why it should stop calling itself a form checker

Research done September 2026. Sources at the bottom. Everything attributed to a
source is marked; everything else is reasoning from what this repository has
measured, which is stated as such.

---

## 1. The landscape splits into three, and none of them do the same job

### Progression libraries
Caliverse, Thenics, The Movement Athlete, Thenx, Fitloop, Ascend.

Video libraries plus a skill roadmap, £4–5/month or free with ads. The Movement
Athlete is the most interesting of them: it scores your current ability on each
skill before building a path, which makes it strong for people chasing a
specific move.

**The catch:** the assessment is self-reported. You tell it you did eight clean
reps and it believes you. Every roadmap in this category is gated on a number
the athlete supplies about themselves.

### AI form checkers
Gymscore (~98% claimed accuracy), AiKYNETIX (~95%, with validation work cited
at the University of Houston biomechanics lab and Rice athletics), SensAI,
Form Fix, Gym Assistant.

These analyse video, count reps and score movement. Two sub-shapes: live
skeleton overlay with mid-set cues, or send-a-clip-to-a-conversational-coach.

**The catch:** almost all are barbell-first — squat, deadlift, bench, Olympic
lifts. Calisthenics is not their market.

### Manual comparison tools
Onform, VueMotion, Comparison Aid, Duel, FormUp, WL Analysis.

Side-by-side or overlaid clips of your past self, frame-stepping, sync
playback. VueMotion explicitly markets loading two clips of the same athlete at
different points in time to compare longitudinal change.

**This category matters most for us, because it kills the naive
differentiator.** "Compare against your past self" is not novel. It exists. It
is manual and visual, and the interpretation is entirely yours — but it exists.

---

## 2. The gaps that are real

### 2.1 A change is never separated from noise
Every app with a score-over-time graph shows you 78 → 84 and lets you infer
improvement. **None of them tells you whether six points exceeds your own
rep-to-rep variation.**

This is the largest gap and it is the one thing this repository was built
around from the first commit: a deviation number without its null distribution
is not a measurement. Gymscore advertises graphs of scores improving over time;
that is precisely the claim that needs a null and does not have one.

### 2.2 Accuracy claims are unfalsifiable
95–98% accurate *at what*, against *whose* labels?

Rep counting is genuinely easy and probably is that accurate. **Technique
assessment has no ground truth to be accurate against** — there is no labelled
corpus of correct muscle-ups, and if there were, the labels would be one
coach's opinion.

Our own finding is the uncomfortable one here, and it is in
[`FINDINGS.md`](FINDINGS.md) with the numbers: **camera azimuth dominates the
deviation signal. A 10° camera move exceeded every technique error we induced.**
Any app scoring form from a handheld phone — ours included — is substantially
measuring where the phone was. Nobody in this market says so. One review
mentions in passing that with Gymscore "you need to position the camera
correctly to get an accurate score". That is the whole ballgame, filed as a
usage tip.

### 2.3 Calisthenics is skill-dominant and the trackers are load-dominant
Well documented outside the app market: progress is governed by motor control,
leverage mastery, connective tissue tolerance and efficiency — not by adding
weight each week. Athletes coming from barbell training report that reps, sets,
load and PRs "don't translate cleanly to skill-based training".

Every general tracker inherits the barbell metaphor: sets × reps × load. In
calisthenics the rep count stops moving long before progress does, and the
thing that *is* changing — control, range, leverage — is exactly what nobody
measures.

### 2.4 The progression gate is decided by vibes
The standard rule in the sport is roughly: *three sets of ten controlled reps,
with a pause at the peak, and you have earned the next progression.*

That is **the** decision in calisthenics. It is made constantly, it determines
whether you progress or injure yourself, and it is entirely self-assessed.
Nobody referees it. The Movement Athlete comes closest and still asks you.

### 2.5 Nothing refuses
No app in any of the three categories tells you it could not measure your clip.
They always return a number.

---

## 3. Does a self-referential trainer with memory break into this niche?

### The case against, taken seriously

**Peloton Guide.** Camera-based form feedback, automatic rep counting,
skeletal overlay, real hardware, enormous marketing budget, a captive
subscriber base — and it was [discontinued worldwide in July 2025][guide].
Form feedback by itself did not retain users. Peloton has since put AI cameras
back into its Cross Training hardware, so they have not abandoned the thesis,
but the standalone proposition failed at a company with every advantage.

**Assume "AI form check" as a category proposition is not enough.** That is the
single most important datum in this document.

**Our own build is the second argument against.** Being honest costs:

| | |
|---|---|
| Clips classified correctly | 7 of 8 |
| Clips producing **zero** reps | 3 of 8 |
| Real muscle-ups shown vs counted (clip 0010) | 3 shown, 2 counted |

A competitor willing to guess returns a satisfying number every time. We return
*"I could not measure that — tilt the camera up."* That is a harder sell and
pretending otherwise would be the same dishonesty the project exists to avoid.

**Filming friction is severe.** Calisthenics happens in parks, often alone,
frequently with nowhere to prop a phone. Every rep measured is a rep filmed.

### The case for

**The refusals become the product, if the positioning is right.**

Nobody needs a fifteenth app saying their squat depth is 87%. But *"am I
actually ready for the next progression, or do I just feel ready?"* is a real,
recurring, high-stakes question that athletes currently answer by guessing.

A **verified rep** — one that was actually measured, against a stated
threshold, whose reasoning can be replayed — is worth *more* than an
unverified one precisely because it is harder to get. Refusal stops being
failure and becomes the thing that makes the certificate mean something.

And every competitor claiming 98% accuracy has structurally disqualified
themselves from making that claim. **A system that never refuses cannot certify
anything.** If it always returns a number, the number carries no information
about whether the rep was real.

**This also fixes the retention problem Peloton hit.** Form feedback is advice,
and advice is ignorable. A progression gate is a *decision you need made*, it
requires your history, and so the value compounds and the switching cost grows
with every session logged. That is what "memory of the past" actually buys —
not nostalgia, but a personal null distribution a competitor starting from zero
cannot reproduce for you.

### Where this lands

The niche is real and under-served. The technical asset — self-referential
measurement with an explicit null, plus honest refusal — is genuinely
differentiated, and the differentiation survives contact with the manual
comparison tools because theirs is visual and unquantified.

**But the wedge is not form-checking.** That is crowded, barbell-first, and its
accuracy claims are unfalsifiable in a way that will eventually be noticed.

**The wedge is objectively refereeing the progression decision**, for the two
or three movements we can measure well, with filming discipline made an
explicit part of the deal rather than a hidden failure mode.

> Not a coach. A referee.

---

## 4. What that means for the product

Concretely, the repositioning implies these changes, in priority order.

### 4.1 Make "verified rep" a first-class concept — DONE
A rep counts only if it was segmented, passed the plausibility checks, and
received a score. Everything else is a candidate. The distinction already
exists inside the measurement core; it was not surfaced. It now is, and the
language throughout is *verified*, not *detected*.

### 4.2 Answer the progression question — DONE
`barra/progression.py` is the referee. It holds a ladder of movements, a
published standard per step, and it reports readiness with the evidence and
what is still missing. It never says "ready" from a single session.

### 4.3 Frame refusal as integrity, not error — DONE
A clip that could not be measured says so, says why, and says what to change.
It is not an apology and not an error state. The Diagnostics screen already
made the reasoning replayable; the athlete-facing copy now matches.

### 4.4 Still open
- **Filming protocol as onboarding.** The azimuth finding means camera
  placement is not a tip, it is a precondition. It should be taught once,
  explicitly, with a check that it worked.
- **Validate that "verified" reads as trustworthy rather than broken.** This is
  a ten-person test, not a research question, and it is the highest-value thing
  left. If users read a refusal as the app being broken, the whole positioning
  fails and we should know that before building further on it.
- **Narrow the movement set deliberately.** Better to referee three movements
  credibly than eight badly.

---

## 5. Market context

The fitness app market is projected at roughly **$13.5–13.8bn in 2026**, rising
to $38–45bn by 2034/35 at ~13–14% CAGR. Mobile exercise apps ranked second in
the ACSM Worldwide Survey of Fitness Trends for 2025, and bodyweight training
has been a recurring global trend for a decade.

No source isolates calisthenics-specific revenue, so treat the segment size as
unknown rather than inferring it. The relevant signal is not the total —
it is that the segment is large enough to support niche products and that the
incumbents in it are content libraries, not measurement tools.

---

## Sources

- [OriGym — 11 Best Calisthenics Apps of 2026](https://www.origym.co.uk/blog/calisthenics-apps/)
- [Calisthenics Worldwide — The 18 Best Calisthenics Apps in 2026](https://calisthenicsworldwide.com/apps/best-calisthenics-apps/)
- [SensAI — Best AI Workout Form Check Apps (2026)](https://www.sensai.fit/blog/best-ai-workout-form-check-apps-2026)
- [Gymscore](https://www.gymscore.ai/)
- [AiKYNETIX](https://aikynetix.com/)
- [The Clip Out — Peloton Guide Discontinued][guide]
- [Gavin.fit — How to Track Calisthenics Progress Without Traditional Weightlifting Metrics](https://www.gavin.fit/blog/how-to-track-calisthenics-progress-without-traditional-weightlifting-metrics)
- [Gravgear — How to Progress Your Bodyweight Training](https://thegravgear.com/blogs/calisthenics/bodyweight-fitness-progression)
- [VueMotion — Video Compare](https://www.vuemotion.com/blog/introducing-video-compare-a-smarter-way-to-analyze-movement-side-by-side)
- [Onform](https://onform.com/sports/track-and-field/)
- [Towards Healthcare — Fitness App Market Sizing](https://www.towardshealthcare.com/insights/fitness-app-market-sizing)
- [Grand View Research — Fitness Apps Market Report 2026–2033](https://www.grandviewresearch.com/industry-analysis/fitness-app-market)

[guide]: https://theclipout.com/peloton-guide-discontinued/
