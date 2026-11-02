#!/usr/bin/env bash
# Local LLM for HomeLoop-Bench on GPU 0 only (DESIGN 10.5).
#   tools/llm_gpu0.sh start | stop | status
# Container homeloop_ollama_gpu0, http://127.0.0.1:11536, the model volume of the shared `ollama` container mounted
# READ-ONLY (the same docker run as scenarios/run_all.sh). It never touches the shared `ollama` container,
# localhost:11535 / :8001 / :5577 / :8003, or any ROS domain. Stop it when you are done.
set -u
NAME=homeloop_ollama_gpu0
PORT=11536
PARALLEL=${OLLAMA_NUM_PARALLEL:-4}
cmd=${1:-status}
case "$cmd" in
  start)
    if curl -sf "http://127.0.0.1:$PORT/api/tags" >/dev/null 2>&1; then echo "already up on :$PORT"; exit 0; fi
    VOL=$(docker inspect ollama --format '{{range .Mounts}}{{if eq .Destination "/root/.ollama"}}{{.Name}}{{end}}{{end}}')
    [ -n "$VOL" ] || { echo "cannot find the model volume of the 'ollama' container"; exit 2; }
    docker rm -f "$NAME" >/dev/null 2>&1
    docker run -d --name "$NAME" --gpus device=0 -e OLLAMA_NUM_PARALLEL="$PARALLEL" -e OLLAMA_KEEP_ALIVE=30m -e OLLAMA_CONTEXT_LENGTH=${OLLAMA_CONTEXT_LENGTH:-4096} \
      -p 127.0.0.1:$PORT:11434 -v "$VOL":/root/.ollama:ro ollama/ollama >/dev/null || exit 3
    for _ in $(seq 1 90); do
      curl -sf "http://127.0.0.1:$PORT/api/tags" >/dev/null 2>&1 && { echo "up on :$PORT (volume $VOL read-only, GPU 0)"; exit 0; }
      sleep 1
    done
    echo "not up after 90 s"; exit 4 ;;
  stop)
    docker stop "$NAME" >/dev/null 2>&1; docker rm "$NAME" >/dev/null 2>&1; echo "stopped $NAME" ;;
  status)
    curl -sf "http://127.0.0.1:$PORT/api/tags" | python3 -c 'import json,sys; print([m["name"] for m in json.load(sys.stdin)["models"]])' \
      || { echo "$NAME is not running"; exit 1; } ;;
  *) echo "usage: $0 start|stop|status"; exit 64 ;;
esac
