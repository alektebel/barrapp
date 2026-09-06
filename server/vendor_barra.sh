#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
SRC="${BARRA_ROOT:-$ROOT/../../barrapp}"
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
echo "vendored barra -> $DEST"
