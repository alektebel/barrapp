# The Reel Room — Barrapp video debugger

Run from the repository root:

```bash
.venv/bin/python tools/debugweb/server.py
# Or select a free port:
.venv/bin/python tools/debugweb/server.py --port 8093
```

Open the printed localhost URL. There are three pages, all in the project's
Organic theme:

| Page | What it is for |
| --- | --- |
| `/` **Library** | Every video, one card each. Previews, the latest run, search, filters, import and per-video metadata. |
| `/guide` **How to debug** | The pipeline drawn end to end, a seven-step walkthrough, and a symptom → stage table. Start here. |
| `/models` **Model card** | Every constant, threshold, rule, metric and movement profile the prediction path reads, with the source comment that defines each one. |

Click a card to open the inspector. `/design-preview` preserves the older
reference mockup; it is not the debugging workspace and includes synthetic
presentation values.

## The video library

Videos are kept in a SQLite table at `out/library.db`, keyed on the **sha256 of
the file content** rather than on its name. That is what stops the same clip
appearing twice: this repository holds sixteen video files and twelve distinct
clips, because two were copied into `server/data/` under content-addressed
names. Keyed on the filename that is sixteen cards and six separate debug
histories for two videos; keyed on the content it is twelve cards, and the
extra paths show up as provenance on the card that owns them.

Three ways to put a video in, all of them deduplicating:

```bash
# 1. the Add video button on the library page (one file or several)
# 2. drop clips into data/videos/ (or ./, or server/data/) and press Rescan disk
# 3. the command line
python tools/debugweb/library.py scan               # index what is on disk
python tools/debugweb/library.py add clip.mp4       # copy a file in
python tools/debugweb/library.py list
python tools/debugweb/library.py show <id>
python tools/debugweb/library.py set <id> movement=pull_up title="Set 3"
python tools/debugweb/library.py rm <id> [--delete-file]
```

Importing content the library already holds returns the id that already holds
those frames and discards the upload. `rm` never touches `out/traces/`: traces
are evidence, and evidence outlives the file it was taken from.

`videos` is one row per distinct clip; `video_copies` records every path those
bytes were found at and doubles as the hash cache, so rescanning a settled
library is a directory walk rather than a re-hash.

## What the model actually is

The prediction path has two parts: geometric rules compared against live
constants, and a learned model vote that fusion accepts only when its
confidence and margin are strong enough. `/models` (and `/api/model`) reads the
constants, fusion thresholds, feature names, model path and provenance out of
the barra modules at request time, one row per value, carrying the source
comment from the line that defines it. Only constants a module actually
*defines* are attributed to it, so `from .config import THRESHOLDS` does not
make quality.py look like the owner of the fault thresholds.

The same slice appears inside the inspector: selecting a stage in the rail
shows what that stage decides, how it fails, what to look at first, and every
constant governing it — above that stage's evidence, so "why 0.15" is answered
where the question is asked.

## Debug a video

1. Start on the library. Click a card or use **Add video**. **All videos**
   in the inspector returns to the library. Imports are stored under
   `data/videos/`; content already in the library is reported as a duplicate
   and not copied again. Supported containers: MP4, MOV, M4V, AVI and MKV, up
   to 512 MiB. Browser playback still depends on the video's codec; unsupported
   media shows an explanation.
2. Leave movement on **auto**, or force a movement to test a classification
   hypothesis. **Run** calls the actual `server/process.py::process_job`
   production path in an isolated process: pose, geometric classify, learned
   model, fusion, segmentation, metrics, scoring, provenance, optional vision,
   and report assembly. Cached pose is reused by default. Enable **Fresh pose**
   to rerun the selected backend. Selecting a backend namespaces the pose cache,
   so A/B runs do not silently reuse another estimator's keypoints.
3. Watch stage progress and expand **Run log** for process output. **Stop run**
   terminates this analysis without deleting prior results. A Python failure
   preserves its partial trace; a native crash is reported through the worker
   process exit code.
4. Use the video controls, 0.25×/0.5× playback, **− frame / + frame**, or the
   left/right arrow keys outside form controls. Frame steps use the run's
   reported FPS. Click the signal chart to seek. The chart is a downsampled
   overview; use rep/phase bounds for precise evidence inspection.
5. Select a rep, then **setup**, **lifting**, **support**, **lowering** or another
   phase present in that result. **Loop selection** repeats the selected
   interval during playback. **Inspect evidence phase** seeks to the
   assessment's actual interval when provided.
6. Read the actual per-rep assessments: **observed**, **not observed**, or
   **unobservable**, with primitive, threshold, phase and availability reason.
   Expand **Raw assessment** for the full emitted object. Older payloads use
   the legacy evidence display and identify missing measurements.
7. Pick a baseline from **the same video**, then **Compare runs**. The view
   shows before/after result fields and a trace diff. Comparisons describe
   changes; they do not establish which run is correct.
8. Write your timestamped observations in **Your review**. Notes are stored
   per trace in this browser's local storage. **Export debug bundle** downloads
   the trace, payload, note and selected interval as JSON. It does not embed
   the video or pose arrays. Export notes before clearing browser storage.

The selected trace is encoded in the URL, so refresh and copied localhost
links reopen that run even if another analysis finishes meanwhile.

## Evidence provenance

New debugger runs save these files under `out/traces/`:

- `<traceId>.json`: pipeline decision trace, also readable with `barra explain --replay`.
- `<traceId>.payload.json`: analyzer result.
- `<traceId>.pose.parquet`: exact keypoints supplied to that run.

The skeleton overlay uses the run snapshot when available. Older traces fall
back to the current clip cache and display that limitation. The overlay does
not imply that the cached pose is ground truth. This debugger now executes
`process_job`, the same production analysis path used by the local server and
Lambda worker; it does not run the browser upload transport or Android
rendering.

## Verification

```bash
.venv/bin/python -m pytest tests/test_debugweb.py tests/test_library.py -q
.venv/bin/python tools/debugweb/browser_e2e.py
# Against an existing server:
.venv/bin/python tools/debugweb/browser_e2e.py --no-start --base http://127.0.0.1:8093
```

Browser verification needs Playwright/Chromium and the repository's sample
`VID-20260827-WA0010.mp4` with cached pose. It performs a real analyzer run,
checks the pinned overlay, phase seeking, frame stepping, note persistence,
JSON export, same-video comparison, request-error recovery and mobile layout.
It writes real traces and screenshots under `/tmp/barrapp-debugweb-qa`.

The stdlib HTTP server binds to localhost by default. No deployment is needed.
