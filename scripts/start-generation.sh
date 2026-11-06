#!/usr/bin/env bash
# Start the generation stack for Nocturna: ACE-Step's API (port 8001) and the adapter (8002).
#
#   bash scripts/start-generation.sh          # real ACE-Step from $ACESTEP_DIR
#   bash scripts/start-generation.sh --fake   # synthetic drone stand-in, no model needed
#
# Then start Nocturna with ACE_STEP_ENABLED=true (see docs/generation.md). Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."

ACESTEP_DIR=${ACESTEP_DIR:-$HOME/ACE-Step-1.5}
MEDIA_DIR=${AUDIO_DIR:-./data/audio}
LOG_DIR=./data/logs
mkdir -p "$LOG_DIR" "$MEDIA_DIR"
source .venv/bin/activate

pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

if [ "${1:-}" = "--fake" ]; then
  echo "==> Starting FAKE ACE-Step on :8001 (synthetic drones, not a real model)"
  uvicorn nocturna.adapter.fake_acestep:app --host 127.0.0.1 --port 8001 > "$LOG_DIR/acestep.log" 2>&1 &
  pids+=($!)
  export ADAPTER_ACESTEP_REVISION=fake
else
  [ -d "$ACESTEP_DIR" ] || { echo "ACE-Step not found at $ACESTEP_DIR. Run scripts/setup-acestep.sh first."; exit 1; }
  if ! nvidia-smi >/dev/null 2>&1; then
    echo "==> No NVIDIA GPU visible: running ACE-Step on CPU without the language model."
    export ACESTEP_INIT_LLM=false
  fi
  echo "==> Starting ACE-Step API on :8001 (first start may download the model)"
  ( cd "$ACESTEP_DIR" && ACESTEP_API_HOST=127.0.0.1 ACESTEP_API_PORT=8001 uv run acestep-api ) \
    > "$LOG_DIR/acestep.log" 2>&1 &
  pids+=($!)
  export ADAPTER_ACESTEP_REPO_DIR="$ACESTEP_DIR"
fi

echo "==> Waiting for ACE-Step to answer (log: $LOG_DIR/acestep.log)"
for i in $(seq 1 600); do
  curl -sf http://127.0.0.1:8001/health >/dev/null && break
  sleep 2
done
curl -sf http://127.0.0.1:8001/health >/dev/null || { echo "ACE-Step did not start; see $LOG_DIR/acestep.log"; exit 1; }

echo "==> Starting Nocturna adapter on :8002"
ADAPTER_MEDIA_DIR="$MEDIA_DIR" uvicorn nocturna.adapter.app:app --host 127.0.0.1 --port 8002 \
  > "$LOG_DIR/adapter.log" 2>&1 &
pids+=($!)
sleep 3
curl -s http://127.0.0.1:8002/health && echo
echo
echo "Generation stack is up. In another terminal:"
echo "  ACE_STEP_ENABLED=true uvicorn nocturna.api:app --reload"
echo "Press Ctrl+C here to stop."
wait
