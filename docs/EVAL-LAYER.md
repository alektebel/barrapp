# Eval Layer

How barrapp's outputs are tested, graded, and gated. Everything here is
runnable; the entry point is `scripts/eval_runner.py`.

## The four layers

| Layer | What it checks | Cost | File |
|---|---|---|---|
| Golden dataset | measurement core vs reviewed labels | free | `barra/eval/golden.py` |
| Reference check | prose quotes only measured numbers | free | `barra/eval/judge.py` |
| LLM-as-a-judge | prose against a rubric, graded by a model | ~1 call/clip | `barra/eval/judge.py` |
| Regression gate | this run vs committed baseline | free | `barra/eval/gate.py` |

Plus `barra/eval/fetch.py`: pulls YouTube clips into the corpus with
attribution, so the golden set can grow from named public sources instead
of accumulating by hand.

## Golden dataset

`data/evaluation/sample_manifest.json` is the reviewed truth: 8 root clips
with movement, rep count, and three "must not" registries (forbidden
faults, phase-scoped checks, notReps intervals). `grade_run` turns one run's
payloads into per-clip verdicts; every rollup carries its denominator, so
"100%" over two clips reads as inconclusive, not as a pass.

The runner grades in cached mode by default (keypoints from the pose cache,
so two runs differ only in code), and every clip runs in the same trace
discipline as the technique pipeline (`barra/trace.py` records what fired
and against which threshold).

```bash
. .venv/bin/activate
python scripts/eval_runner.py --mode cached            # grade + judge + gate
python scripts/eval_runner.py --mode fresh             # isolated subprocess per clip
python scripts/eval_runner.py --save-baseline          # first run: write the baseline
python scripts/eval_runner.py --gate                   # exit 1 blocks CI
```

Outputs land in `out/eval/<timestamp>-<mode>/`: `payloads/`, `grade.json`
(per clip + rollup), `judge.json`, `gate.json`, `perf.json`, `summary.txt`.

## The judge

Two layers, deliberately cheap first:

1. **Reference check** (deterministic, always runs). Every number in the
   prose must exist in the payload's measured facts. "You did 11 reps" for
   a 2-rep payload fails here, without spending a cent - this is the
   hallucination gate, and it does not need a model.
2. **Rubric judge** (one nan call when `NAN_BASE_URL` + `NAN_API_KEY` are
   set). Five criteria - faithful numbers, no unsupported claim, honest
   abstention, actionable next session, plain language - each scored 0-2
   with the exact quoted fragment that earned it. Verdict: pass /
   borderline / fail. The judge is told to abstain (into `unverifiable`)
   on anything a grader without the video cannot check.

Without an endpoint, layer 2 degrades to layer 1 and says so in
`judge.json` (`"judged": false`).

## The gate

`barra/eval/gate.py` compares `grade.json` against
`out/eval/baseline/grade.json` (committed to the repo; `.gitignore`
unignores exactly that file). Rules:

* `movement`/`repCount` gate on a rate drop > 0.05 (one clip of eight
  flipping is 0.125; noise below).
* The must-not registries (`forbidden`, `notReps`, `phaseScoped`,
  `unobservable`) gate at 0.0: any firing is a regression.
* Improvements never block. Denominator drift (graded-clip count changed)
  is reported as informational, never gating.
* `allPassed` going true -> false blocks even when rollup rates held,
  because a check that stopped grading is a regression the rollup cannot
  see.
* No baseline on disk: advisory only, first run saves one.

## CI

`.github/workflows/eval-gate.yml` runs the eval-layer unit tests plus the
golden set against the committed baseline on every push touching `barra/`
or the manifest. The LLM judge does not run in CI (needs a key); the
reference check does.

## CI/CD

`.github/workflows/cicd.yml` runs the whole pipeline, with eval at every
stage:

```
test-python ─┐
             ├─► package (ECR image, media-type assert) ─► deploy ─► smoke
test-android ┘                                              │
                                              deploy_smoke_eval.py:
                                              one golden clip through the
                                              REAL deployed API, graded by
                                              barra.eval.golden
```

* **test-python**: eval-layer unit tests, the full suite, then the golden
  set against the committed baseline (`--gate`). A metric drop blocks
  before anything is packaged.
* **test-android**: pure-logic Kotlin tests, import discipline, Android
  unit tests, debug APK.
* **package**: builds the worker image with deploy.sh's exact flags
  (the OCI-index/media-type trap is documented in that script) and pushes
  it only after asserting the manifest media type Lambda accepts.
* **deploy**: protected GitHub environment (`aws-production`; configure it
  with required reviewers). After `sam deploy`: `/health`, then
  `scripts/deploy_smoke_eval.py` uploads one reviewed clip through the
  deployed API's own contract (POST /v1/jobs -> presigned PUT -> submit ->
  poll -> payload) and grades it with the same `barra.eval.golden` layer.
  The eval tests the deployment, not just the code.
* **release** (`v*` tags): signed AAB, only after the deploy job's smoke
  eval passed on the same commit.

Secrets required: `AWS_DEPLOY_ROLE_ARN` (OIDC role, no long-lived AWS
keys), `WORKER_ECR_REPO`, `NAN_API_KEY`, `NAN_BASE_URL`,
`DEEPSEEK_API_KEY`, `RELEASE_KEYSTORE_B64` (+ password/alias/key).
`android-build.yml` stays as the PR-fast path; `eval-gate.yml` as the
eval-only path.

## Speed

`barra/eval/perf.py` reports per-clip wall time, analyze time
(`_runtimeS.analyze`, what the measurement itself took), the pose source
that produced the keypoints, and `poseS` - the wall-minus-analyze gap,
which is dominated by pose extraction. One report-only block in
`perf.json` and three lines on the summary screen:
  speed: wall mean 4.1s median 3.9s p95 7.2s max 7.2s
    pose cache: 8 clips, mean wall 4.1s
    slow: VID-20260827-WA0017.mp4 7.2s (cache)
```

Report-only on purpose: CI runners share hardware, so a seconds-level
timing gate would block on load spikes, not on regressions. Read it as a
distribution (p95 and the slowest clips), not as a threshold. Errored
clips are listed, never averaged in - a clip that always crashes also
always takes zero seconds, and averaging that in would flatter the
pipeline.

## Growing the corpus

```bash
python -m barra.eval.fetch --url "https://youtube.com/watch?v=..." \
    --exercise pull_up --set 3
```

Downloads at the same 720p format spec `scripts/scrape_calisthenics.py`
proven (YouTube serves av01/webm at 720p, so `ext=mp4` filters match
nothing), names the file the convention `barra/ingest.py` parses
(`YYYY-MM-DD__<exercise>__setNN.mp4`; underscores become hyphens to fit
the regex), and appends an attribution row to `<out>/metadata.csv` with
source URL, license, and uploader.

## What this layer does not do

* It does not score technique against an ideal, ever. The manifest's
  labels are "what a reviewer saw", not "what correct form is".
* The judge grades prose against the payload, not against reality - a
  faithful report of a bad measurement passes. The golden set is what
  catches bad measurements.
* Nothing here calls a model unless `NAN_API_KEY` is configured; the
  whole pipeline runs offline at its default settings.
