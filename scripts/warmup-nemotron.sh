#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Nemotron Parse Warmup — sends concurrent dummy requests to all 16 replicas
#
# Warmup triggers:
#   - PyTorch lazy CUDA kernel compilation
#   - Flash-attention kernel JIT
#   - Trust-remote-code image processor first-run init
#   - KV cache memory allocation patterns
#
# Runs during MiniMax M2.5 weight loading (~8 min) so Nemotron replicas are
# fully hot by the time the research pipeline is ready.
#
# Usage:  warmup-nemotron.sh [NEMOTRON_URL] [NUM_REQUESTS]
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

URL="${1:-http://nemotron-parse-svc.default.svc.cluster.local:8000/v1/chat/completions}"
# 6× replica count (96) gives ~97% probability that every replica is hit.
# Ray Serve uses power-of-2-choices (P2C) routing; when all 16 replicas are
# equally idle at t=0 it degenerates to uniform random, so coverage follows
# the coupon-collector bound: P(miss ≥1) ≤ 16*(15/16)^k → ~3% at k=96.
NUM_REPLICAS=16
NUM_REQUESTS="${2:-$((NUM_REPLICAS * 8))}"

# 1×1 white PNG — valid image that exercises the full vision pipeline
TINY_PNG="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="

BODY=$(cat <<EOF
{
    "model": "nvidia/NVIDIA-Nemotron-Parse-v1.2",
    "messages": [{
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": "</s><s><predict_bbox><predict_classes><output_markdown><predict_no_text_in_pic>"
            },
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,${TINY_PNG}"}
            }
        ]
    }],
    "max_tokens": 1,
    "temperature": 0,
    "extra_body": {
        "repetition_penalty": 1.1,
        "top_k": 1,
        "skip_special_tokens": false
    }
}
EOF
)

echo "╔══════════════════════════════════════════╗"
echo "║  Nemotron Parse Warmup — ${NUM_REQUESTS} concurrent requests  ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "Target: ${URL}"
echo ""

# Phase 1: Wait for the HTTP server to respond on /v1/models
# (proves the Ray Serve proxy is up; does NOT prove vLLM is ready to infer)
MODELS_URL="$(echo "$URL" | sed 's|/v1/chat/completions|/v1/models|')"
echo "Waiting for Nemotron Parse HTTP server..."
ATTEMPT=0
MAX_WAIT=600  # 10 min
while true; do
    if wget -q -O /dev/null --timeout=5 "$MODELS_URL" 2>/dev/null; then
        echo "HTTP server is up."
        break
    fi
    ATTEMPT=$((ATTEMPT + 5))
    if [ "$ATTEMPT" -ge "$MAX_WAIT" ]; then
        echo "ERROR: Timed out waiting for HTTP server after ${MAX_WAIT}s"
        exit 1
    fi
    sleep 5
done

# Phase 2: Block until the inference engine actually accepts a request.
# /v1/models returns OK before vLLM finishes KV-cache allocation, CUDA
# kernel compilation, and trust_remote_code image-processor init.  Without
# this gate the bulk warmup requests queue inside vLLM and hit the 120s
# timeout before a single forward pass completes.
echo ""
echo "Waiting for first successful inference (vLLM engine ready)..."
ATTEMPT=0
MAX_WAIT=600
while true; do
    if wget -q -O /dev/null --timeout=60 \
        --header="Content-Type: application/json" \
        --post-data="$BODY" \
        "$URL" 2>/dev/null; then
        echo "Inference engine ready."
        break
    fi
    ATTEMPT=$((ATTEMPT + 10))
    if [ "$ATTEMPT" -ge "$MAX_WAIT" ]; then
        echo "ERROR: Inference engine did not become ready after ${MAX_WAIT}s"
        exit 1
    fi
    echo "  Not ready yet, retrying in 10s... (${ATTEMPT}/${MAX_WAIT}s)"
    sleep 10
done

echo ""
echo "Sending ${NUM_REQUESTS} warmup requests simultaneously..."
START=$(date +%s)

# Fire all requests at once — the phase-2 readiness gate above already
# confirmed vLLM is accepting inference, so no request will queue-starve.
# Simultaneous dispatch hits all 16 replicas in a single wave so warmup
# completes in one forward-pass cycle rather than multiple consecutive spikes.
for i in $(seq 1 "$NUM_REQUESTS"); do
    (
        if wget -q -O /dev/null --timeout=300 \
            --header="Content-Type: application/json" \
            --post-data="$BODY" \
            "$URL" 2>/dev/null; then
            echo "  ✓ req ${i}"
        else
            echo "  ✗ req ${i}"
        fi
    ) &
done
wait

END=$(date +%s)
ELAPSED=$((END - START))

echo ""
echo "════════════════════════════════════════════"
echo "  Warmup complete in ${ELAPSED}s"
echo "════════════════════════════════════════════"
