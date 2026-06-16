#!/usr/bin/env bash
set -euo pipefail

MODEL_PATH="${MODEL_PATH:-Qwen/Qwen3-VL-32B-Instruct}"
OUTPUT_PATH="${OUTPUT_PATH:-models/Qwen3-VL-32B-Instruct-AWQ}"
W_BIT="${W_BIT:-4}"
Q_GROUP_SIZE="${Q_GROUP_SIZE:-128}"
ZERO_POINT="${ZERO_POINT:-true}"
VERSION="${VERSION:-GEMM}"

python -m video_understanding.quantize_awq \
  --model-path "$MODEL_PATH" \
  --output-path "$OUTPUT_PATH" \
  --w-bit "$W_BIT" \
  --q-group-size "$Q_GROUP_SIZE" \
  --zero-point "$ZERO_POINT" \
  --version "$VERSION"

