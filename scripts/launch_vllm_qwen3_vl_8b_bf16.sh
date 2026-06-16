#!/usr/bin/env bash
set -euo pipefail

MODEL="${MODEL:-Qwen/Qwen3-VL-8B-Instruct}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-$MODEL}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8002}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-131072}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.90}"
LIMIT_MM_IMAGES="${LIMIT_MM_IMAGES:-80}"

export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-2}"

args=(
  serve "$MODEL"
  --host "$HOST"
  --port "$PORT"
  --served-model-name "$SERVED_MODEL_NAME"
  --tensor-parallel-size 1
  --max-model-len "$MAX_MODEL_LEN"
  --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION"
  --dtype bfloat16
  --limit-mm-per-prompt "image=$LIMIT_MM_IMAGES"
)

if [[ -n "${MM_PROCESSOR_KWARGS:-}" ]]; then
  args+=(--mm-processor-kwargs "$MM_PROCESSOR_KWARGS")
fi

exec vllm "${args[@]}"

