#!/usr/bin/env bash
set -euo pipefail

MODEL="${MODEL:-models/Qwen3-VL-32B-Instruct-AWQ}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-Qwen3-VL-32B-Instruct-AWQ}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-131072}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.90}"
LIMIT_MM_IMAGES="${LIMIT_MM_IMAGES:-80}"
QUANTIZATION="${QUANTIZATION:-}"

export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"

args=(
  serve "$MODEL"
  --host "$HOST"
  --port "$PORT"
  --served-model-name "$SERVED_MODEL_NAME"
  --tensor-parallel-size 1
  --max-model-len "$MAX_MODEL_LEN"
  --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION"
  --limit-mm-per-prompt "{\"image\": $LIMIT_MM_IMAGES}"
)

if [[ -n "$QUANTIZATION" ]]; then
  args+=(--quantization "$QUANTIZATION")
fi

if [[ -n "${MM_PROCESSOR_KWARGS:-}" ]]; then
  args+=(--mm-processor-kwargs "$MM_PROCESSOR_KWARGS")
fi

exec vllm "${args[@]}"
