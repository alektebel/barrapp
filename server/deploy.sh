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

sam deploy \
  --image-repository "$REPO" \
  --parameter-overrides \
    "DeepSeekApiKey=${DEEPSEEK_API_KEY:-}" \
    "NanApiKey=${NAN_API_KEY:-}" \
    "NanBaseUrl=${NAN_BASE_URL:-}" \
    "WorkerImageUri=$REPO:$TAG"
