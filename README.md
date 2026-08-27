# Barra

Decides whether one repetition deviates from **the same subject's own**
reference repetitions by more than that subject's own natural rep-to-rep
variation.

It is not a coaching product, not an app, and not a technique score. It is a
measurement core, built standalone so it can be falsified cheaply. It makes no
cross-subject comparison and no claim about *why* a rep deviated.

**No deviation number is ever reported without the null distribution it is
measured against.**

---

## Status

| | |
|---|---|
| Pipeline | complete, 13 commands run end to end |
| Movements | squat, muscle-up, pull-up, dip |
| Verified on synthetic data | yes — `barra selftest`, 36 invariant tests |
| Run on real footage | yes — 4 muscle-up clips, 3 sessions, Aug 2026 |
| Deviation verdict (section 8) | **not obtainable on that footage**: 3 usable reps, and a template needs 8 in one bin |
| Progress verdict | **not yet trackable**: 1 and 2 usable reps per session, 3 is the minimum |

The `Part A` pipeline the original spec assumed (pose extraction + rep
segmentation) did not exist in this repository. Rather than stop, this repo
implements that stage thinly and swappably: pose estimation is delegated to a
pluggable backend, and rep segmentation is a documented heuristic writing a
plain CSV you are expected to correct by hand. If a real Part A appears later,
`barra ingest --from-part-a <dir>` turns this stage into a loader.

### Preliminary verdict, on synthetic data only

On the simulated subject the tool **does not clear its own verdict bar**, and
the cause is identified: uncontrolled camera azimuth. A 10° camera move —
comfortably inside the spec's 20°-wide `SAGITTAL` bin — produces a larger
deviation than any of the five deliberately induced technique errors.

Full numbers and what follows from them: [`docs/FINDINGS.md`](docs/FINDINGS.md).

### What the real footage added

Four muscle-up clips across three sessions produced **three** measurable reps.
Two clips produced none, and the tool records why rather than staying quiet:
one lost tracking as the athlete left frame at the top, the other contained
no reps at all — its candidates were the athlete *walking around the rig*, at
0.9 keypoint confidence. Confidence is not accuracy; the checks that catch this
are geometric, and they are described in
[`docs/PROGRESS.md`](docs/PROGRESS.md).

This is a falsification of the recording protocol, not of the idea. The
prediction it makes — lock the camera to a marked floor position and the null
tightens to the rep-to-rep noise floor — is untested. Testing it needs your
footage.

---

## Quick start

```bash
uv venv --python 3.11 .venv && . .venv/bin/activate
uv pip install -e .

# see the whole thing work on simulated data, with no camera required
barra selftest
barra normalise
barra viewpoints
barra mark-reference 2026-08-01__squat__set01 0-2
barra mark-reference 2026-08-08__squat__set01 0-2
barra mark-reference 2026-08-15__squat__set01 0-2
barra mark-reference 2026-08-01__squat__set02 0-2
barra mark-reference 2026-08-08__squat__set02 0-2
barra mark-reference 2026-08-15__squat__set02 0 1
barra all
open out/report.html
```

`barra selftest` writes a `SYNTHETIC` marker into `out/`. Delete the whole
directory before ingesting real footage.

## Running it on your own videos

**1. Install a pose backend.** None ships by default: the spec pins the
dependency list, so a pose estimator is an explicit opt-in.

```bash
uv pip install -e ".[mediapipe]"      # CPU, fast, recommended to start
# or
uv pip install -e ".[ultralytics]"    # YOLO-pose, COCO-17 native
```

**2. Add videos** to `data/videos/`. Read
[`data/videos/README.md`](data/videos/README.md) first — it covers naming, how
many reps you need, and the recording requirements. The tripod one is not
optional; it is the finding above.

**3. Run the pipeline.**

```bash
rm -rf out                      # clear the synthetic run
barra status                    # what exists, what is missing
barra ingest                    # pose + rep segmentation
                                # -> inspect out/reps.csv and fix it by hand if wrong
barra normalise                 # stage 1
barra viewpoints                # stage 2 - read the bin summary before continuing
barra mark-reference 2026-08-27__squat__set01 0-5
barra template                  # stage 3 + the leave-one-out null (stage 5)
barra score                     # stage 4
barra validate                  # stage 6 - needs out/labels.csv
barra report                    # out/report.html
```

`barra all` runs everything after `ingest`. Every command is idempotent, reads
from `out/` and writes to `out/`. There is no hidden state.

**4. Write `out/labels.csv`** before validating. Template:
[`docs/labels.example.csv`](docs/labels.example.csv).

```csv
rep_id,label,edge_of_bin,note
2026-08-27__squat__set01#r00,clean,false,
2026-09-03__squat__err01#r00,excess_forward_lean,false,deliberate
```

`label` is `clean` or an error name **you** choose. Nothing in this codebase
interprets the names.

---

## How it decides

```
video ──ingest──> keypoints + rep boundaries
      ──normalise──> hip at origin, torso = 1, rotation KEPT
      ──viewpoints──> azimuth ± interval -> SAGITTAL / OBLIQUE / FRONTAL / UNKNOWN
      ──mark-reference──> you name the reference reps, by hand
      ──template──> DBA barycentre + leave-one-out NULL DISTRIBUTION
      ──score──> DTW residual (joint × phase) -> total, per-joint, per-phase
      ──validate──> detection rate AND false positive rate, together
      ──report──> out/report.html
```

The decisions worth arguing about, and why they went the way they did:

- **Rotation is not removed.** Torso lean in the image plane is signal. A full
  Procrustes alignment would rotate it away and erase one of the few things
  worth measuring. Scale and translation only. There is a test for this
  (`test_rotation_is_not_removed`) so it cannot regress silently.
- **Scale is per-set, not per-frame.** Camera distance is fixed within a set,
  so a per-set scale removes distance while preserving torso foreshortening —
  which changes as the lifter pitches toward or away from the camera, and is
  the same class of signal as lean. `--scale per_frame` gives the literal
  reading of the spec if you want to test the choice rather than argue it.
- **Reference reps are marked by hand, never selected automatically.** With no
  labels, any automatic choice of "good" reps would be a function of the
  deviation score itself, and the template would become "the reps that score
  well against the template". That is circular and it manufactures a tight
  null out of nothing.
- **The null is leave-one-out.** Each held-out reference rep is scored against
  a template rebuilt without it. A rep that helped build its own template
  would score too well and the null would come out fraudulently tight.
- **Movements are declared, never guessed.** A squat is measured about the hips;
  a muscle-up is measured about the bar, because the hands are what stays still
  and a hip-centred frame would cancel the very motion being measured. An
  unknown exercise name is an error rather than a silent fallback to squat
  geometry, which would produce numbers that look fine and mean nothing.
- **Never compare across viewpoint bins**, and a bin with fewer than 6 reps is
  reported underpowered and excluded. A set whose azimuth interval straddles a
  boundary is binned `UNKNOWN` and dropped — an unknown viewpoint is cheap, a
  wrong one silently poisons a template.
- **Joints are weighted by keypoint confidence** (test rep × template, floored,
  normalised to sum to 1), so an occluded joint cannot dominate. The weights
  used are printed in the report for every rep.
- **Thresholds are fixed in `config.py` before labels are seen.** `validate`
  fingerprints that file on its first run and the report says loudly if it
  changed afterwards. Post-hoc tuning is not preventable, but it is visible.

## Verdict rule (spec section 8)

The tool does not work if, at the 95th-percentile threshold:

- false positive rate on **held-out** clean reps exceeds **20%**, or
- detection rate on induced errors is below **60%**.

At least 30% of clean reps must be held out of the reference set. `validate`
refuses to report an FPR estimated on reps that built the template, and refuses
to report a detection rate without an FPR beside it.

## Commands

| | |
|---|---|
| `barra status` | what exists on disk, what is missing |
| `barra ingest [--backend B] [--from-part-a DIR]` | pose extraction + rep segmentation |
| `barra normalise [--scale per_set\|per_frame]` | stage 1 |
| `barra viewpoints [--true-shoulder-ratio R]` | stage 2 |
| `barra mark-reference VIDEO REPS...` | stage 3 — `0-5`, `0 2 5`, rep ids, or `all` |
| `barra template` | stage 3 template + stage 5 null |
| `barra score [VIDEO] [--no-qc]` | stage 4 + percentile |
| `barra validate` | stage 6 |
| `barra report` | `out/report.html` |
| `barra remember [DIR] [--note ...]` | fold this run into the persistent `profile/` |
| `barra progress` | compare sessions against within-session variation |
| `barra selftest [--seed N]` | synthetic data; validates nothing |
| `barra all` | everything after `ingest` |

## Tests

```bash
python -m unittest discover -s tests -v      # 36 invariant tests
python scripts/viewpoint_sensitivity.py      # the finding in docs/FINDINGS.md
```

## Not built, deliberately

3D lifting, physics simulation, SMPL fitting, Gaussian splatting, mobile UI,
LLM-generated feedback, expert-labelled scoring, cross-subject comparison, and
any claim about why a deviation occurred.

## Fill in after your first real validation run

- Viewpoint bins used: _______
- Reference reps, and from how many sessions: _______
- FPR on held-out clean reps: _______
- Detection rate per induced error: _______
- Cross-session inflation ratio: _______
- **Verdict:** _______
