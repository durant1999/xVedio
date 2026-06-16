#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: scripts/run_single_video.sh <video-path-or-url> [workdir]" >&2
  exit 64
fi

VIDEO="$1"
WORKDIR="${2:-}"

args=(run "$VIDEO" --config configs/pipeline.yaml)
if [[ -n "$WORKDIR" ]]; then
  args+=(--workdir "$WORKDIR")
fi

exec python -m video_understanding "${args[@]}"

