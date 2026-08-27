#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
bash vendor_barra.sh
sam build
sam deploy --parameter-overrides "DeepSeekApiKey=${DEEPSEEK_API_KEY:-}"
