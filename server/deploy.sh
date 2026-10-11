#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# The worker image is built here rather than by `sam build`, and that is not a
# preference. Docker 29 with the containerd snapshotter pushes an OCI image
# INDEX with attestations attached; Lambda only accepts a single Docker v2
# schema 2 manifest, and rejects the index with
#
#   The image manifest, config or layer media type for the source image ...
#   is not supported
#
# which fails the stack update and rolls it back - and because the rollback
# restores a working image, the pipeline keeps running and the breakage only
# shows up the next time someone tries to deploy. --provenance/--sbom drop the
# attestations (no index), oci-mediatypes=false picks the Docker media types.
REPO="${WORKER_REPO:-257394490122.dkr.ecr.eu-west-1.amazonaws.com/samapp7427b055/workerfunction5fd3ab0brepo}"
REGION="${AWS_REGION:-eu-west-1}"
TAG="worker-$(date +%Y%m%d-%H%M%S)"

bash vendor_barra.sh

aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "${REPO%%/*}"

docker buildx build \
  --provenance=false --sbom=false \
  --output type=docker,oci-mediatypes=false \
  -t "$REPO:$TAG" .
docker push "$REPO:$TAG"

# Fail here rather than halfway through a stack update: if the media type is
# wrong, Lambda will reject it and the deploy will roll back.
MEDIA=$(aws ecr describe-images --repository-name "${REPO#*/}" --region "$REGION" \
  --image-ids "imageTag=$TAG" \
  --query 'imageDetails[0].imageManifestMediaType' --output text)
if [ "$MEDIA" != "application/vnd.docker.distribution.manifest.v2+json" ]; then
  echo "worker image has media type $MEDIA; Lambda needs a v2 schema 2 manifest" >&2
  exit 1
fi
echo "worker image $TAG pushed ($MEDIA)"

# --use-container so the zip does not depend on a python3.11 being installed
# here; the API has no third-party deps, but the runtime version still has to
# match what Lambda runs.
sam build --use-container ApiFunction

# SAM rejects empty NoEcho parameter overrides. Omitting a parameter lets
# CloudFormation reuse the stack's current value instead of clearing the key.
overrides=(
  "WorkerImageUri=$REPO:$TAG"
)
if [ -n "${DEEPSEEK_API_KEY:-}" ]; then
  overrides+=("DeepSeekApiKey=$DEEPSEEK_API_KEY")
fi
if [ -n "${NAN_BASE_URL:-}" ]; then
  overrides+=("NanBaseUrl=$NAN_BASE_URL")
fi

sam deploy \
  --no-confirm-changeset \
  --no-fail-on-empty-changeset \
  --parameter-overrides "${overrides[@]}"

# The smoke that would have caught the deploy of 2026-09-12. That image was
# missing api/auth.py, so every invoke died at import with
#
#   Unable to import module 'handler': No module named 'auth'
#
# before a single line of the handler ran. The stack updated cleanly, the
# deploy reported success, and every clip after it went to the dead-letter
# queue - unread, because nothing was watching the queue either.
#
# One synchronous invoke settles it. The job id is nonsense on purpose: a
# worker that imports gets as far as looking for the clip and fails on the
# missing object, which is a PASS here. A worker that cannot import fails
# before that, with Runtime.ImportModuleError, and this exits non-zero.
WORKER_FN=$(aws cloudformation describe-stack-resource \
  --stack-name "${STACK:-sam-app}" --region "$REGION" \
  --logical-resource-id WorkerFunction \
  --query 'StackResourceDetail.PhysicalResourceId' --output text)

echo "smoke-testing $WORKER_FN"
OUT=$(mktemp)
PAYLOAD=$(mktemp)
printf '%s' '{"job_id":"deploy-smoke","owner":"deploy-smoke"}' > "$PAYLOAD"

# fileb:// rather than a raw --payload string, and no --cli-binary-format:
# that flag exists only in AWS CLI v2, and this machine runs v1, where it is
# an "Unknown options" usage error. fileb:// is read as bytes by both.
if ! aws lambda invoke --function-name "$WORKER_FN" --region "$REGION" \
      --payload "fileb://$PAYLOAD" "$OUT" >/dev/null; then
  echo "could not invoke $WORKER_FN - the smoke test did not run" >&2
  rm -f "$OUT" "$PAYLOAD"
  exit 1
fi
rm -f "$PAYLOAD"

if grep -q "ImportModuleError\|No module named\|Unable to import" "$OUT"; then
  echo "the worker image cannot import its own handler:" >&2
  cat "$OUT" >&2
  echo >&2
  echo "the stack is updated but every clip will dead-letter - fix and redeploy" >&2
  rm -f "$OUT"
  exit 1
fi
echo "worker imports cleanly: $(head -c 200 "$OUT")"
rm -f "$OUT"

# The same question, asked of the API: a zip missing a module answers 502 to
# every request, and /health is the one route that touches no AWS service, so
# a 200 here means the package imported.
API=$(aws cloudformation describe-stacks --stack-name "${STACK:-sam-app}" \
  --region "$REGION" --query \
  'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue' --output text)
CODE=$(curl -s -o /dev/null -w '%{http_code}' "$API/health")
if [ "$CODE" != "200" ]; then
  echo "the API answered $CODE on /health - the zip is broken" >&2
  exit 1
fi
echo "api healthy at $API"
