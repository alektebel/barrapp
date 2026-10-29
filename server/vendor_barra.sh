#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
# This repo is the barra tree (barra/, models/, …). Older checkouts pointed at
# a sibling `barrapp/` clone; BARRA_ROOT still overrides when needed.
SRC="${BARRA_ROOT:-$ROOT/..}"
DEST="$ROOT/vendor/barra"
rm -rf "$DEST"
mkdir -p "$DEST"
rsync -a --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '.gradle' \
  --exclude '.kotlin' \
  --exclude '.idea' \
  --exclude 'build' \
  --exclude 'out' \
  --exclude 'dist' \
  --exclude 'server/vendor' \
  --exclude 'app/build' \
  --exclude '*.mp4' \
  --exclude '*.mov' \
  --exclude '*.pt' \
  --exclude '*.log' \
  --exclude 'hs_err_pid*' \
  --exclude 'replay_pid*' \
  "$SRC/" "$DEST/"
# Pose models live under models/ (gitignored except the tracked .task files).
# Ensure the production Full model is present for the worker image; Heavy is
# kept alongside for BARRA_POSE_MODEL rollback.
mkdir -p "$DEST/models"
for model in pose_landmarker_full.task pose_landmarker_heavy.task; do
  if [ -f "$SRC/models/$model" ] && [ ! -f "$DEST/models/$model" ]; then
    cp "$SRC/models/$model" "$DEST/models/$model"
  fi
done
if [ ! -f "$DEST/models/pose_landmarker_full.task" ]; then
  echo "missing models/pose_landmarker_full.task (needed by BARRA_POSE_MODEL)" >&2
  exit 1
fi
echo "vendored barra -> $DEST"
