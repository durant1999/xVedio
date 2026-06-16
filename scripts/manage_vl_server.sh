#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-start}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

CONDA_ENV="${CONDA_ENV:-}"
MODEL="${MODEL:-$ROOT_DIR/models/Qwen3-VL-32B-Instruct-AWQ}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-Qwen3-VL-32B-Instruct-AWQ}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
HEALTH_HOST="${HEALTH_HOST:-127.0.0.1}"
HEALTH_URL="${HEALTH_URL:-http://$HEALTH_HOST:$PORT/v1/models}"
CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-131072}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.90}"
LIMIT_MM_IMAGES="${LIMIT_MM_IMAGES:-80}"
QUANTIZATION="${QUANTIZATION:-}"
MM_PROCESSOR_KWARGS="${MM_PROCESSOR_KWARGS:-}"
START_TIMEOUT="${START_TIMEOUT:-1200}"
STOP_TIMEOUT="${STOP_TIMEOUT:-60}"
WAIT_HEALTH="${WAIT_HEALTH:-1}"
LOG_DIR="${LOG_DIR:-$ROOT_DIR/logs}"
RUN_DIR="${RUN_DIR:-$ROOT_DIR/.run}"
NAME="${NAME:-qwen3-vl-32b-awq-$PORT}"
PID_FILE="${PID_FILE:-$RUN_DIR/$NAME.pid}"
LOG_FILE="${LOG_FILE:-$LOG_DIR/$NAME.log}"

usage() {
  cat <<EOF
usage: scripts/manage_vl_server.sh {start|stop|restart|status|tail}

Environment overrides:
  CONDA_ENV=$CONDA_ENV
  CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES
  MODEL=$MODEL
  SERVED_MODEL_NAME=$SERVED_MODEL_NAME
  HOST=$HOST
  PORT=$PORT
  MAX_MODEL_LEN=$MAX_MODEL_LEN
  LIMIT_MM_IMAGES=$LIMIT_MM_IMAGES
  GPU_MEMORY_UTILIZATION=$GPU_MEMORY_UTILIZATION
  QUANTIZATION=$QUANTIZATION
  WAIT_HEALTH=$WAIT_HEALTH
  START_TIMEOUT=$START_TIMEOUT
  LOG_FILE=$LOG_FILE
EOF
}

pid_from_file() {
  if [[ -f "$PID_FILE" ]]; then
    tr -d '[:space:]' < "$PID_FILE"
  fi
}

is_running() {
  local pid
  pid="$(pid_from_file)"
  [[ -n "$pid" ]] && { kill -0 -- "-$pid" 2>/dev/null || kill -0 "$pid" 2>/dev/null; }
}

health_once() {
  python3 - "$HEALTH_URL" <<'PY'
import json
import sys
import urllib.request

url = sys.argv[1]
request = urllib.request.Request(url, headers={"User-Agent": "video-understanding-healthcheck"})
try:
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))
except Exception as exc:
    print(exc, file=sys.stderr)
    raise SystemExit(1)

models = payload.get("data", [])
if not isinstance(models, list):
    raise SystemExit(1)
print(",".join(str(item.get("id")) for item in models if isinstance(item, dict)))
PY
}

wait_for_health() {
  local deadline=$((SECONDS + START_TIMEOUT))
  while (( SECONDS < deadline )); do
    if ! is_running; then
      echo "server exited before becoming healthy; see $LOG_FILE" >&2
      return 1
    fi
    if health_once >/dev/null 2>&1; then
      echo "healthy: $HEALTH_URL"
      return 0
    fi
    sleep 5
  done
  echo "timed out waiting for $HEALTH_URL; see $LOG_FILE" >&2
  return 1
}

start_server() {
  if is_running; then
    echo "already running: pid $(pid_from_file)"
    echo "log: $LOG_FILE"
    return 0
  fi
  if [[ ! -d "$MODEL" && ! "$MODEL" =~ ^[A-Za-z0-9_.-]+/ ]]; then
    echo "model path not found: $MODEL" >&2
    return 2
  fi

  mkdir -p "$LOG_DIR" "$RUN_DIR"
  rm -f "$PID_FILE"

  local -a command=(
    env
    "CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"
    "MODEL=$MODEL"
    "SERVED_MODEL_NAME=$SERVED_MODEL_NAME"
    "HOST=$HOST"
    "PORT=$PORT"
    "MAX_MODEL_LEN=$MAX_MODEL_LEN"
    "GPU_MEMORY_UTILIZATION=$GPU_MEMORY_UTILIZATION"
    "LIMIT_MM_IMAGES=$LIMIT_MM_IMAGES"
    "QUANTIZATION=$QUANTIZATION"
    "MM_PROCESSOR_KWARGS=$MM_PROCESSOR_KWARGS"
    "$ROOT_DIR/scripts/launch_vllm_qwen3_vl_32b_awq.sh"
  )

  if [[ -n "$CONDA_ENV" ]]; then
    command=(conda run --no-capture-output -n "$CONDA_ENV" "${command[@]}")
  fi

  echo "starting $SERVED_MODEL_NAME on GPU $CUDA_VISIBLE_DEVICES port $PORT"
  echo "log: $LOG_FILE"
  nohup setsid "${command[@]}" >"$LOG_FILE" 2>&1 &
  echo "$!" > "$PID_FILE"
  sleep 2

  if ! is_running; then
    echo "failed to start; see $LOG_FILE" >&2
    return 1
  fi
  echo "pid: $(pid_from_file)"

  if [[ "$WAIT_HEALTH" == "1" ]]; then
    wait_for_health
  fi
}

stop_server() {
  if ! is_running; then
    echo "not running"
    rm -f "$PID_FILE"
    return 0
  fi

  local pid
  pid="$(pid_from_file)"
  echo "stopping pid $pid"
  kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true

  local deadline=$((SECONDS + STOP_TIMEOUT))
  while (( SECONDS < deadline )); do
    if ! is_running; then
      rm -f "$PID_FILE"
      echo "stopped"
      return 0
    fi
    sleep 1
  done

  echo "pid $pid did not stop within ${STOP_TIMEOUT}s; sending SIGKILL" >&2
  kill -9 -- "-$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
  rm -f "$PID_FILE"
}

status_server() {
  if is_running; then
    echo "running: pid $(pid_from_file)"
    echo "health: $HEALTH_URL"
    echo "log: $LOG_FILE"
    if health_once >/dev/null 2>&1; then
      echo "ready: yes"
    else
      echo "ready: no"
    fi
  else
    echo "not running"
    echo "pid file: $PID_FILE"
    echo "log: $LOG_FILE"
  fi
}

case "$ACTION" in
  start)
    start_server
    ;;
  stop)
    stop_server
    ;;
  restart)
    stop_server
    start_server
    ;;
  status)
    status_server
    ;;
  tail)
    mkdir -p "$LOG_DIR"
    touch "$LOG_FILE"
    tail -f "$LOG_FILE"
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 64
    ;;
esac
