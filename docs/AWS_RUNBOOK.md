# AWS runbook: pick up here once `aws configure` is done

Context snapshot (2026-09-04): stack **`sam-app`** is live in **`eu-west-1`**
(account `257394490122`), `CREATE_COMPLETE`, with ApiUrl
`https://gogtzcttw6.execute-api.eu-west-1.amazonaws.com`. `aws` CLI is
authenticated. The HTTP contract works end-to-end and the worker now returns
**real analyses** — a verified muscle-up came back `sessionScore: 58, band:
solid`, `n_reps: 1`, per-rep `score`/`metrics`/`components` (`WA0012`); other
clips produced specific fixed-bar/pose blockers instead of blank output. Two
worker-image fixes were needed and are deployed (see §6.1): the missing
`libGL.so.1` (OpenCV/MediaPipe) and the missing `pandas` (barra's measurement
core). `gradle.properties` points the app at the ApiUrl. Toolchain is now
installed: `sam` in `~/.local/bin` (v1.166.0) and the `docker` group assigned —
but this shell predates the group, so run docker steps via `newgrp docker`.
`server/vendor/` is built.

## 0. Toolchain

```bash
# AWS CLI docs links in docs/AWS.md §1, then:
aws configure   # region eu-west-1, output json
# SAM CLI (user-local, no root): install the native zip, then
#   sh install -i ~/.local/aws-sam-cli -b ~/.local/bin ; sam --version
sudo usermod -aG docker $USER    # add self to the docker group (idempotent)
# The docker group only applies to NEW sessions. Until you re-login to Hyprland,
# run each docker-touching command under `newgrp docker`:
#   newgrp docker < script.sh      # script's docker/sam calls see the socket
newgrp docker
docker ps       # must show an empty table before any sam build
```

## 1. Who am I / what exists?

```bash
aws sts get-caller-identity
# expect Account "257394490122" (matches server/samconfig.toml ECR repo)

aws cloudformation describe-stacks --stack-name sam-app --region eu-west-1 \
  --query 'Stacks[0].{Status:StackStatus,Outputs:Outputs}'
# Look for OutputKey=ApiUrl -> https://<id>.execute-api.eu-west-1.amazonaws.com
```

- Stack exists + status `*_COMPLETE` + ApiUrl present → go to §2.
- Stack missing / `REVIEW_IN_PROGRESS` / failed → go to §3.

## 2. Backend is live — verify and connect the app

```bash
ApiUrl=$(aws cloudformation describe-stacks --stack-name sam-app --region eu-west-1 \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue' --output text)
curl "$ApiUrl/health"   # {"ok": true}
```

Then point the app at it in `gradle.properties` (both build types read it via
`project.findProperty`; **not** `local.properties`, which is the SDK/NDK file
and has no effect on `apiUrl`):

```properties
barrapp.apiUrlDebug=https://<id>.execute-api.eu-west-1.amazonaws.com
barrapp.apiUrlRelease=https://<id>.execute-api.eu-west-1.amazonaws.com
```

```bash
source scripts/env.sh
./gradlew assembleDebug
```

End-to-end: install the APK, add a clip, check Diagnostics screen trace id,
then replay the server's decision chain locally:

```bash
barra explain --replay <trace-id>
```

## 3. Backend is not live — deploy

```bash
cd server
bash vendor_barra.sh
mkdir -p vendor/barra/models
cp ../models/pose_landmarker_heavy.task vendor/barra/models/  # 30 MB, already in repo
sam build
sam deploy   # samconfig.toml already holds stack name/region/ECR; answer Y to IAM creation
```

Known gotchas (from docs/AWS.md): needs Python 3.11 on PATH or
`sam build --use-container`; first build uploads a large OpenCV+MediaPipe
image; never put pose/OpenCV in the API zip (250 MB Lambda limit — worker is
the container, API is `server/api/` only). On `CREATE_FAILED` with rollback
disabled: delete stack `sam-app` before retrying.

After deploy: copy the `ApiUrl` output into §2 steps. For Play release also set
`barrapp.apiUrlRelease` in `gradle.properties`, then `./gradlew bundleRelease`.

## 4. Architecture recap (what you are operating)

Phone `POST /v1/jobs` → `PUT` clip to S3 presigned URL → `POST submit` →
API Lambda invokes worker → worker downloads clip from S3, runs
`process_job()` (probe → MediaPipe pose → geometric classify → rep
segmentation → per-rep metrics → quality score → report), writes result JSON
to DynamoDB → phone polls `GET /v1/jobs/{id}`.

Per-clip pipeline detail: see `server/process.py:process_job()` and
`docs/CORE.md` ("How it decides"). Every run writes a trace id
(`out/traces/`, same id shown in app Diagnostics) for `barra explain --replay`.

## 5. Security caveat (decide before Play release)

There is **no real auth**: the only check is the self-asserted `X-Device-Id`
header (per-device isolation, anyone can set any value). No Cognito, API keys,
or IAM authorizer on the HTTP API. Fine for personal testing; needs a decision
before store release. Clips auto-expire from S3 after 30 days; idle cost is
near zero, each analysed clip costs a few cents of Lambda + S3.

## 6. Redeploy after a code change

Nothing in `server/` reaches AWS until you re-build. Two deployables:

- **API** — a zip of `server/api/` (`handler.py`).
- **Worker** — a Docker image built from `server/Dockerfile`, which copies
  `api/handler.py process.py deepseek.py` plus `vendor/barra` (barra source).

```bash
cd server
bash vendor_barra.sh   # only if barra/ source changed; re-vendors into vendor/barra
sam build
sam deploy            # samconfig.toml already holds stack/region/ECR
```

- `process.py` / `deepseek.py` / barra changed → the worker image re-builds and
  re-uploads (the big, slow one).
- `api/handler.py` changed → that alone is in the API zip, but `sam build`
  rebuilds both; `sam deploy` uploads whatever changed.
- DeepSeek key changed → pass it as a parameter. `server/deploy.sh` already does
  this: `sam deploy --parameter-overrides "DeepSeekApiKey=${DEEPSEEK_API_KEY:-}"`.
  Or edit it in the Lambda console (Environment variables) and redeploy.

## 6.1 Two worker-image blockers (fixed and deployed)

End-to-end testing (2026-09-04) showed every clip analysing to zero reps. Two
separate `import` failures blocked the worker; both are fixed, rebuilt and
redeployed. Verified: `WA0012` returned `sessionScore: 58 / band: solid`,
`n_reps: 1`; `WA0020` auto-detected 19 push-up reps; others returned specific
fixed-bar/pose blockers instead of blank output.

**1. `libGL.so.1: cannot open shared object file`** — `mediapipe` pulls
non-headless `opencv-contrib-python`, and its `cv2` dlopen()s `libGL.so.1` at
import. The minimal AL2023 base image has none of the OpenCV/MediaPipe runtime
libs.

- `server/Dockerfile` now installs `mesa-libGL mesa-libEGL glib2 libXext
  libXrender libX11 libSM libICE fontconfig libgomp libpng` (gcc too) as a
  **loud** step — it no longer swallows errors with `|| true`, so a bad package
  name aborts the build instead of shipping a container that measures nothing.
- `server/requirements-worker.txt` pins `opencv-contrib-python==4.10.0.84` in
  place of `opencv-python-headless`, so the two builds stop competing for the
  `cv2` module (mediapipe needs the non-headless one anyway).

**2. `No module named 'pandas'`** — barra's measurement core (`ingest.py`,
`metrics.py`, `movements.py`) runs on DataFrames. Added
`pandas==2.2.3` (compatible with the pinned `numpy<2`). `dtaidistance`,
`jinja2` and `pyarrow` are in `pyproject.toml` but are CLI-only — `process_job`
does not import them, so they are deliberately left out of the worker image.

Rebuild + redeploy (see §6; on this machine there is no `python3.11`, so use
`--use-container`):

```bash
cd server && bash vendor_barra.sh
sam build --use-container
sam deploy --no-confirm-changeset --no-fail-on-empty-changeset
```

Then re-run an end-to-end job (§7) and confirm `status=done` with `n_reps > 0`.

## 7. Watch it run (logs + job records)

Lambda logs live under the `/aws/lambda/sam-app` prefix:

```bash
aws logs describe-log-groups --log-group-name-prefix /aws/lambda/sam-app --region eu-west-1
aws logs tail /aws/lambda/sam-app-ApiFunction-<hash>   --region eu-west-1 --follow
aws logs tail /aws/lambda/sam-app-WorkerFunction-<hash> --region eu-west-1 --follow
```

The job record lives in DynamoDB (table `sam-app-JobsTable-<hash>`, list it with
`aws dynamodb list-tables --region eu-west-1`). Statuses go
`created` → `queued` → `processing` → `done` / `failed`:

```bash
aws dynamodb scan --table-name sam-app-JobsTable-<hash> --region eu-west-1
```

Common failures:

- Stuck at `queued` → the worker never ran. Check its log for an import/cold-start
  error; usually missing `vendor/barra` or no pose model — re-run
  `vendor_barra.sh` and copy `models/pose_landmarker_heavy.task` into
  `vendor/barra/models/`.
- `failed` → the error string is in the record's `error` field, and
  `barra explain --replay <trace-id>` replays that job's decision chain locally.
- Worker times out (>10 min) → clip too long or MediaPipe hung; the job is
  capped at 600 s (`WorkerFunction.Timeout`).

## 8. Stop it / tear down (stop the meter)

Idle cost is near zero, but to fully shut the stack down:

```bash
aws cloudformation delete-stack --stack-name sam-app --region eu-west-1
aws cloudformation wait stack-delete-complete --stack-name sam-app --region eu-west-1
```

This removes the API, both Lambda functions, the S3 bucket (and its clips), and
the DynamoDB table. The ECR image may survive the stack (billed a few cents a
month) — delete the repo in the ECR console if you want the meter fully off.
Re-deploying later is just §3 again.
