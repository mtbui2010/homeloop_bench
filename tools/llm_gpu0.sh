#!/usr/bin/env bash
# Local LLM for HomeLoop-Bench on one GPU (DESIGN 10.5).   tools/llm_gpu0.sh start | stop | status | pull MODEL
#
# Starts an Ollama server in a container (default name homeloop_ollama_gpu0, http://127.0.0.1:11536). Optional
# lab helper: any Ollama-compatible server works with `--llm URL` (docs/live_smoke.md).
#
# Where the models come from (first match):
#   OLLAMA_MODELS_DIR=/path      a host directory holding an Ollama model store (mounted read-only)
#   OLLAMA_VOLUME=name           a docker volume holding one (mounted read-only)
#   the volume of an existing container named `ollama` (the authors' lab setup; read-only, never touched)
#   otherwise the helper's own named volume `homeloop_ollama_models` (read-write): fill it with
#   `tools/llm_gpu0.sh pull qwen3-vl:8b-instruct` (and the other models of docs/generation.md)
# GPU: HOMELOOP_GPU (default 0) -> --gpus device=$HOMELOOP_GPU. Port: HOMELOOP_LLM_PORT (default 11536).
# Image: pinned by digest (OLLAMA_IMAGE overrides). The helper never touches the shared `ollama` container itself,
# localhost:11535 / :8001 / :5577 / :8003, or any ROS domain. Stop it when you are done.
set -u
NAME=${HOMELOOP_LLM_NAME:-homeloop_ollama_gpu0}
PORT=${HOMELOOP_LLM_PORT:-11536}
GPU=${HOMELOOP_GPU:-0}
IMAGE=${OLLAMA_IMAGE:-ollama/ollama@sha256:2a6e883b917fc543389599dae79918f5cac9e1438890506982f44aa4f5625d01}
OWN_VOLUME=homeloop_ollama_models
PARALLEL=${OLLAMA_NUM_PARALLEL:-4}
cmd=${1:-status}

models_mount() {   # -> "-v SRC:/root/.ollama[:ro]"
  if [ -n "${OLLAMA_MODELS_DIR:-}" ]; then echo "-v ${OLLAMA_MODELS_DIR}:/root/.ollama:ro"; return; fi
  if [ -n "${OLLAMA_VOLUME:-}" ]; then echo "-v ${OLLAMA_VOLUME}:/root/.ollama:ro"; return; fi
  local vol
  vol=$(docker inspect ollama --format '{{range .Mounts}}{{if eq .Destination "/root/.ollama"}}{{.Name}}{{end}}{{end}}' 2>/dev/null)
  if [ -n "$vol" ]; then echo "-v $vol:/root/.ollama:ro"; return; fi
  echo "-v $OWN_VOLUME:/root/.ollama"
}

case "$cmd" in
  start)
    if curl -sf "http://127.0.0.1:$PORT/api/tags" >/dev/null 2>&1; then echo "already up on :$PORT"; exit 0; fi
    MOUNT=$(models_mount)
    docker rm -f "$NAME" >/dev/null 2>&1
    # shellcheck disable=SC2086
    docker run -d --name "$NAME" --gpus device="$GPU" -e OLLAMA_NUM_PARALLEL="$PARALLEL" -e OLLAMA_KEEP_ALIVE=30m \
      -e OLLAMA_CONTEXT_LENGTH=${OLLAMA_CONTEXT_LENGTH:-8192} -p 127.0.0.1:$PORT:11434 $MOUNT "$IMAGE" >/dev/null || exit 3
    for _ in $(seq 1 90); do
      curl -sf "http://127.0.0.1:$PORT/api/tags" >/dev/null 2>&1 && { echo "up on :$PORT ($MOUNT, GPU $GPU)"; exit 0; }
      sleep 1
    done
    echo "not up after 90 s"; exit 4 ;;
  pull)
    [ -n "${2:-}" ] || { echo "usage: $0 pull MODEL"; exit 64; }
    case "$(models_mount)" in *:ro) echo "the model store is mounted read-only; pull into it with its own server"; exit 2 ;; esac
    docker exec "$NAME" ollama pull "$2" ;;
  stop)
    docker stop "$NAME" >/dev/null 2>&1; docker rm "$NAME" >/dev/null 2>&1; echo "stopped $NAME" ;;
  status)
    curl -sf "http://127.0.0.1:$PORT/api/tags" | python3 -c 'import json,sys; print([m["name"] for m in json.load(sys.stdin)["models"]])' \
      || { echo "$NAME is not running"; exit 1; } ;;
  *) echo "usage: $0 start|stop|status|pull MODEL"; exit 64 ;;
esac
