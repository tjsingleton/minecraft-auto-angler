#!/usr/bin/env bash
set -euo pipefail

out_path="${1:-$HOME/.autoangler/flamegraph.svg}"
mkdir -p "$(dirname "$out_path")"

exec uvx py-spy record \
  --output "$out_path" \
  --format flamegraph \
  -- python -m autoangler
