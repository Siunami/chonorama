#!/usr/bin/env bash
# Build the published site in the directory linked to the Vercel project.
set -euo pipefail
cd "$(dirname "$0")"

STAGE=../.context/chronorama
node build.mjs --out "$STAGE" "$@"
cd "$STAGE" && exec vercel deploy --prod --yes
