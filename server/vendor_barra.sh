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
  --exclude 'out' \
  --exclude 'data/videos/*.mp4' \
  --exclude 'data/videos/*.mov' \
  "$SRC/" "$DEST/"
echo "vendored barra -> $DEST"
