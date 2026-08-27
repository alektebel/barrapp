# Set up AWS for barrapp

You need an AWS account, a credit card on file, and Docker. eu-west-1 (Ireland) is a reasonable region from Spain.

## 1. Install tools

```bash
# AWS CLI: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
# SAM CLI: https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html
# Docker Engine, running (`docker ps` should work)
```

Create an IAM user (or use the root account only for first login) with permission to create Lambda, API Gateway, S3, DynamoDB, ECR, IAM roles, and CloudFormation.

```bash
aws configure
```

Set region `eu-west-1`, output `json`. The access key lives only on your machine.

## 2. Optional DeepSeek

In `server/.env`:

```
DEEPSEEK_API_KEY=
```

Leave blank: the app still returns metrics. Fill it if you want the LLM write-up.

## 3. Vendor barra and bake the pose model

```bash
cd server
bash vendor_barra.sh
# optional, skips a 30 MB download on first user:
mkdir -p vendor/barra/models
cp ../../barrapp/models/pose_landmarker_heavy.task vendor/barra/models/ 2>/dev/null || true
```

If the `.task` file is not there yet, run one local analysis first (`python3 server/local_server.py` and upload a clip) — MediaPipe downloads it to `../barrapp/models/`.

## 4. Deploy

```bash
cd server
sam build
sam deploy --guided --parameter-overrides DeepSeekApiKey="${DEEPSEEK_API_KEY:-}"
```

This machine has Python 3.11, so the API Lambda runtime is `python3.11`. If SAM still cannot find it, either put `/usr/bin` on your PATH or build inside Docker: `sam build --use-container`.

Answer the prompts:

| Prompt | What to type |
|---|---|
| Stack name | `barrapp` |
| Region | `eu-west-1` |
| Confirm changes | `Y` |
| Allow SAM CLI IAM role creation | `Y` |
| Disable rollback | `N` |
| Create ECR repo for worker image | `Y` |
| Save arguments to samconfig.toml | `Y` |

The first build uploads a large Docker image (OpenCV + MediaPipe). Worker pins NumPy 1.26 because MediaPipe still requires `numpy<2`. Later deploys are `sam build && sam deploy`.

The **API** Lambda is a small zip (`server/api/` only). Pose, OpenCV, `vendor/`, and the SAM installer must not go in that zip — Lambda rejects packages over 250 MB unzipped.

If a deploy fails with `CREATE_FAILED` and rollback was disabled, delete the broken stack before retrying:

```bash
aws cloudformation delete-stack --stack-name sam-app
aws cloudformation wait stack-delete-complete --stack-name sam-app
sam build
sam deploy
```

This repo already has `server/samconfig.toml`, so you can skip `--guided` after the first successful save. If you already created stack `sam-app`, keep that name (do not start a second stack).

## 5. Point the app at the API

Copy **ApiUrl** from the deploy output (it looks like `https://abc123.execute-api.eu-west-1.amazonaws.com`).

Put it in `gradle.properties`:

```
barrapp.apiUrlRelease=https://abc123.execute-api.eu-west-1.amazonaws.com
```

For a phone talking to AWS even in debug, also set `barrapp.apiUrlDebug` to that same URL (HTTPS, no laptop IP).

```bash
source scripts/env.sh
./gradlew assembleDebug          # phone testing
./gradlew bundleRelease          # Play Store upload (.aab)
```

Check:

```bash
curl "$ApiUrl/health"
# {"ok": true}
```

## 6. What this creates (and cost)

- HTTP API (TLS included)
- S3 bucket, private, clips expire after 30 days
- DynamoDB table, jobs keyed per device
- Small API Lambda
- Container worker Lambda (3 GB, 10 min) that runs MediaPipe

Idle cost is near zero. Each analysed clip is a few cents of Lambda + S3. Watch the first month in Billing.

## 7. Restart the local server after pulls

The API now requires header `X-Device-Id`. Stop the old `local_server.py` (Ctrl+C) and start it again if you still test on LAN.

```bash
python3 server/local_server.py
```
