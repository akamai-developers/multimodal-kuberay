#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# Load Test for Ray Serve Autoscaling
#
# Sends concurrent requests to the LLM (and optionally TTS pipeline) to
# saturate replicas and trigger KubeRay's in-tree autoscaler.
#
# Usage:
#   ./scripts/load-test.sh                  # 10 workers, 60s, LLM only
#   ./scripts/load-test.sh -w 20 -d 120     # 20 workers, 120s
#   ./scripts/load-test.sh --pipeline       # Test VLM→TTS pipeline too
#   ./scripts/load-test.sh --monitor        # Show autoscaling metrics live
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────────────
WORKERS=10
DURATION=60
TEST_PIPELINE=false
MONITOR=false
GATEWAY_IP=""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ── Parse args ───────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    -w|--workers)   WORKERS="$2"; shift 2 ;;
    -d|--duration)  DURATION="$2"; shift 2 ;;
    --pipeline)     TEST_PIPELINE=true; shift ;;
    --monitor)      MONITOR=true; shift ;;
    --ip)           GATEWAY_IP="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: $0 [-w WORKERS] [-d DURATION] [--pipeline] [--monitor] [--ip GATEWAY_IP]"
      echo ""
      echo "  -w, --workers N     Number of concurrent request workers (default: 10)"
      echo "  -d, --duration S    Test duration in seconds (default: 60)"
      echo "  --pipeline          Also load-test the VLM→TTS pipeline (/v1/audio/describe)"
      echo "  --monitor           Print autoscaling metrics every 10s during the test"
      echo "  --ip IP             Gateway IP (default: auto-detect from kubectl)"
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# ── Resolve gateway ──────────────────────────────────────────────────────────
if [[ -z "$GATEWAY_IP" ]]; then
  GATEWAY_IP=$(kubectl get gateway llm-gateway -ojsonpath="{.status.addresses[0].value}" 2>/dev/null || true)
fi
if [[ -z "$GATEWAY_IP" ]]; then
  echo -e "${RED}ERROR: Could not detect gateway IP. Pass --ip or check 'kubectl get gateway llm-gateway'${NC}"
  exit 1
fi
if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo -e "${RED}ERROR: OPENAI_API_KEY not set${NC}"
  exit 1
fi

BASE_URL="http://${GATEWAY_IP}"
AUTH_HEADER="Authorization: Bearer ${OPENAI_API_KEY}"

# ── Counters (shared via temp files) ─────────────────────────────────────────
TMPDIR_LOAD=$(mktemp -d)
trap 'rm -rf "$TMPDIR_LOAD"' EXIT
echo 0 > "$TMPDIR_LOAD/llm_ok"
echo 0 > "$TMPDIR_LOAD/llm_err"
echo 0 > "$TMPDIR_LOAD/tts_ok"
echo 0 > "$TMPDIR_LOAD/tts_err"

# Prompts to cycle through (varied lengths to create realistic load)
PROMPTS=(
  "Explain the concept of tensor parallelism in 3 sentences."
  "Write a haiku about GPU computing."
  "What are the key differences between Ray Serve and TensorFlow Serving? Be concise."
  "Describe Kubernetes autoscaling in exactly 50 words."
  "List 5 benefits of using vision-language models for accessibility."
  "Explain how KV-cache works in transformer inference. Keep it short."
  "What is the role of an attention mechanism in a multimodal model?"
  "Compare gRPC and REST for ML model serving in 3 bullet points."
  "Write a one-paragraph explanation of quantization for LLM inference."
  "How does pipeline parallelism differ from data parallelism?"
)

# ── Worker function ──────────────────────────────────────────────────────────
llm_worker() {
  local id=$1
  local end_time=$2
  local count=0
  local errors=0

  while [[ $(date +%s) -lt $end_time ]]; do
    # Pick a random prompt
    local prompt="${PROMPTS[$((RANDOM % ${#PROMPTS[@]}))]}"

    local http_code
    http_code=$(curl --silent --max-time 120 \
      --output /dev/null \
      --write-out "%{http_code}" \
      "${BASE_URL}/v1/chat/completions" \
      -H "${AUTH_HEADER}" \
      -H "Content-Type: application/json" \
      -d "{
        \"model\": \"qwen3-vl-8b-instruct\",
        \"messages\": [{\"role\": \"user\", \"content\": \"${prompt}\"}],
        \"max_tokens\": 150
      }" 2>/dev/null) || http_code="000"

    if [[ "$http_code" == "200" ]]; then
      count=$((count + 1))
    else
      errors=$((errors + 1))
    fi
  done

  # Atomic-ish counter update
  local prev
  prev=$(cat "$TMPDIR_LOAD/llm_ok")
  echo $((prev + count)) > "$TMPDIR_LOAD/llm_ok"
  prev=$(cat "$TMPDIR_LOAD/llm_err")
  echo $((prev + errors)) > "$TMPDIR_LOAD/llm_err"
}

pipeline_worker() {
  local id=$1
  local end_time=$2
  local count=0
  local errors=0

  while [[ $(date +%s) -lt $end_time ]]; do
    local http_code
    http_code=$(curl --silent --max-time 180 \
      --output /dev/null \
      --write-out "%{http_code}" \
      "${BASE_URL}/v1/audio/describe" \
      -H "${AUTH_HEADER}" \
      -H "Content-Type: application/json" \
      -d '{
        "model": "qwen3-vl-8b-instruct",
        "messages": [{"role": "user", "content": "Describe what a GPU cluster looks like in one energetic sentence."}],
        "voice": "alloy",
        "max_tokens": 60
      }' 2>/dev/null) || http_code="000"

    if [[ "$http_code" == "200" ]]; then
      count=$((count + 1))
    else
      errors=$((errors + 1))
    fi
  done

  local prev
  prev=$(cat "$TMPDIR_LOAD/tts_ok")
  echo $((prev + count)) > "$TMPDIR_LOAD/tts_ok"
  prev=$(cat "$TMPDIR_LOAD/tts_err")
  echo $((prev + errors)) > "$TMPDIR_LOAD/tts_err"
}

# ── Monitor function ─────────────────────────────────────────────────────────
monitor_autoscaler() {
  local end_time=$1
  local llm_head
  llm_head=$(kubectl get pods --no-headers 2>/dev/null | grep 'ray-serve-llm.*head' | awk '{print $1}')

  while [[ $(date +%s) -lt $end_time ]]; do
    sleep 10
    echo -e "\n${CYAN}── Autoscaling Metrics ($(date +%H:%M:%S)) ──${NC}"

    # LLM metrics
    local metrics
    metrics=$(kubectl exec "$llm_head" -c ray-head -- \
      curl -s localhost:8080/metrics 2>/dev/null | \
      grep -E 'ray_serve_autoscaling_(total_requests|desired_replicas|target_replicas)' | \
      grep -v '^#' | grep 'LLMServer' || true)

    local total desired target
    total=$(echo "$metrics" | grep total_requests | sed 's/.*} //')
    desired=$(echo "$metrics" | grep desired_replicas | sed 's/.*} //')
    target=$(echo "$metrics" | grep target_replicas | sed 's/.*} //')

    echo -e "  LLM ongoing_requests: ${BOLD}${total:-?}${NC}  desired_replicas: ${BOLD}${desired:-?}${NC}  target_replicas: ${BOLD}${target:-?}${NC}"

    # Worker pod count
    local workers
    workers=$(kubectl get pods --no-headers 2>/dev/null | grep 'ray-serve-llm.*worker' | grep -c Running || echo 0)
    echo -e "  LLM worker pods: ${BOLD}${workers}${NC}"

    if $TEST_PIPELINE; then
      local tts_workers
      tts_workers=$(kubectl get pods --no-headers 2>/dev/null | grep 'ray-serve-tts.*worker' | grep -c Running || echo 0)
      echo -e "  TTS worker pods: ${BOLD}${tts_workers}${NC}"
    fi
  done
}

# ── Print config ─────────────────────────────────────────────────────────────
echo -e "${BLUE}══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Ray Serve Autoscaling Load Test${NC}"
echo -e "${BLUE}══════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${GREEN}Gateway:${NC}     ${BASE_URL}"
echo -e "  ${GREEN}Workers:${NC}     ${WORKERS} concurrent LLM request loops"
if $TEST_PIPELINE; then
  echo -e "  ${GREEN}Pipeline:${NC}    + $((WORKERS / 3 > 0 ? WORKERS / 3 : 1)) concurrent VLM→TTS workers"
fi
echo -e "  ${GREEN}Duration:${NC}    ${DURATION}s"
echo -e "  ${GREEN}Monitor:${NC}     ${MONITOR}"
echo -e "  ${GREEN}Scaling at:${NC}  target_ongoing_requests = 4 (LLM), 2 (TTS)"
echo ""

# ── Pre-flight: show current state ──────────────────────────────────────────
echo -e "${YELLOW}Current cluster state:${NC}"
kubectl get pods --no-headers 2>/dev/null | grep ray-serve | \
  awk '{printf "  %-55s %s\n", $1, $3}'
echo ""

# ── Launch workers ───────────────────────────────────────────────────────────
END_TIME=$(( $(date +%s) + DURATION ))
PIDS=()

echo -e "${GREEN}Launching ${WORKERS} LLM workers...${NC}"
for i in $(seq 1 "$WORKERS"); do
  llm_worker "$i" "$END_TIME" &
  PIDS+=($!)
done

if $TEST_PIPELINE; then
  PIPELINE_WORKERS=$((WORKERS / 3 > 0 ? WORKERS / 3 : 1))
  echo -e "${GREEN}Launching ${PIPELINE_WORKERS} pipeline (VLM→TTS) workers...${NC}"
  for i in $(seq 1 "$PIPELINE_WORKERS"); do
    pipeline_worker "$i" "$END_TIME" &
    PIDS+=($!)
  done
fi

if $MONITOR; then
  monitor_autoscaler "$END_TIME" &
  PIDS+=($!)
fi

echo -e "${YELLOW}Load test running for ${DURATION}s... (Ctrl+C to stop early)${NC}"
echo ""

# ── Wait for completion ──────────────────────────────────────────────────────
trap 'echo -e "\n${RED}Interrupted — killing workers...${NC}"; kill "${PIDS[@]}" 2>/dev/null; wait 2>/dev/null' INT

for pid in "${PIDS[@]}"; do
  wait "$pid" 2>/dev/null || true
done

# ── Report ───────────────────────────────────────────────────────────────────
LLM_OK=$(cat "$TMPDIR_LOAD/llm_ok")
LLM_ERR=$(cat "$TMPDIR_LOAD/llm_err")
TTS_OK=$(cat "$TMPDIR_LOAD/tts_ok")
TTS_ERR=$(cat "$TMPDIR_LOAD/tts_err")

echo ""
echo -e "${BLUE}══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Results${NC}"
echo -e "${BLUE}══════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${GREEN}LLM requests:${NC}      ${LLM_OK} ok / ${LLM_ERR} errors"
if $TEST_PIPELINE; then
  echo -e "  ${GREEN}Pipeline requests:${NC} ${TTS_OK} ok / ${TTS_ERR} errors"
fi
TOTAL=$((LLM_OK + TTS_OK))
echo -e "  ${GREEN}Throughput:${NC}        ~$(( TOTAL / DURATION )) req/s"
echo ""

# ── Final cluster state ─────────────────────────────────────────────────────
echo -e "${YELLOW}Final cluster state:${NC}"
kubectl get pods --no-headers 2>/dev/null | grep ray-serve | \
  awk '{printf "  %-55s %s\n", $1, $3}'
echo ""

# ── Check if scaling happened ────────────────────────────────────────────────
LLM_WORKERS=$(kubectl get pods --no-headers 2>/dev/null | grep 'ray-serve-llm.*worker' | grep -c Running || echo 0)
if [[ "$LLM_WORKERS" -gt 1 ]]; then
  echo -e "${GREEN}✓ Autoscaling triggered! LLM scaled to ${LLM_WORKERS} workers.${NC}"
else
  echo -e "${YELLOW}⚠ LLM still at 1 worker. Try more workers (-w 20) or longer duration (-d 180).${NC}"
fi

if $TEST_PIPELINE; then
  TTS_WORKERS=$(kubectl get pods --no-headers 2>/dev/null | grep 'ray-serve-tts.*worker' | grep -c Running || echo 0)
  if [[ "$TTS_WORKERS" -gt 1 ]]; then
    echo -e "${GREEN}✓ TTS autoscaling triggered! Scaled to ${TTS_WORKERS} workers.${NC}"
  else
    echo -e "${YELLOW}⚠ TTS still at 1 worker.${NC}"
  fi
fi

echo ""
echo -e "${BLUE}Tip: Run with --monitor to see autoscaling metrics in real-time.${NC}"
echo -e "${BLUE}     Watch the Ray Dashboard at http://localhost:8265 for live scaling.${NC}"
