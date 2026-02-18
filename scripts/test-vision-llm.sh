#!/bin/bash
set -e

# Get Gateway service IP
export SERVICE_IP=$(kubectl get gateway llm-gateway -ojsonpath="{.status.addresses[0].value}")

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}===========================================================${NC}"
echo -e "${BLUE}  Testing Dual Vision-Language Model Deployment${NC}"
echo -e "${BLUE}  - Qwen3-VL-8B-Instruct (visual coding, UI agents)${NC}"
echo -e "${BLUE}  - NVIDIA Nemotron VL 12B (document intelligence)${NC}"
echo -e "${BLUE}===========================================================${NC}"
echo ""
echo -e "${GREEN}Service IP: ${SERVICE_IP}${NC}"
echo ""

# Test 1: Text-only prompt (baseline) - Qwen3-VL
echo -e "${YELLOW}Test 1a: Text-only prompt - Qwen3-VL${NC}"
echo "-----------------------------------------------------------"
curl --location "http://${SERVICE_IP}/v1/chat/completions" \
  --header "Authorization: Bearer ${OPENAI_API_KEY}" \
  --header "Content-Type: application/json" \
  --data '{
    "model": "qwen3-vl-8b-instruct",
    "messages": [
      {"role": "user", "content": "Say hello and describe your capabilities in one sentence."}
    ],
    "max_tokens": 100
  }'
echo -e "\n"

# Test 1b: Text-only prompt (baseline) - Nemotron VL
echo -e "${YELLOW}Test 1b: Text-only prompt - Nemotron VL${NC}"
echo "-----------------------------------------------------------"
curl --location "http://${SERVICE_IP}/v1/chat/completions" \
  --header "Authorization: Bearer ${OPENAI_API_KEY}" \
  --header "Content-Type: application/json" \
  --data '{
    "model": "nemotron-vl-12b",
    "messages": [
      {"role": "system", "content": "/no_think"},
      {"role": "user", "content": "Say hello and describe your capabilities in one sentence."}
    ],
    "max_tokens": 100
  }'
echo -e "\n"

# Test 2: Vision test with sample image - Both models
echo -e "${YELLOW}Test 2a: Image analysis (Kubernetes logo) - Qwen3-VL${NC}"
echo "-----------------------------------------------------------"
curl --location "http://${SERVICE_IP}/v1/chat/completions" \
  --header "Authorization: Bearer ${OPENAI_API_KEY}" \
  --header "Content-Type: application/json" \
  --data '{
    "model": "qwen3-vl-8b-instruct",
    "messages": [
      {
        "role": "user",
        "content": [
          {
            "type": "image_url",
            "image_url": {
              "url": "https://raw.githubusercontent.com/kubernetes/kubernetes/master/logo/logo.png"
            }
          },
          {
            "type": "text",
            "text": "Describe this image in detail. What logo or symbol is shown?"
          }
        ]
      }
    ],
    "max_tokens": 200
  }'
echo -e "\n"

echo -e "${YELLOW}Test 2b: Image analysis (Kubernetes logo) - Nemotron VL${NC}"
echo "-----------------------------------------------------------"
curl --location "http://${SERVICE_IP}/v1/chat/completions" \
  --header "Authorization: Bearer ${OPENAI_API_KEY}" \
  --header "Content-Type: application/json" \
  --data '{
    "model": "nemotron-vl-12b",
    "messages": [
      {
        "role": "system",
        "content": "/no_think"
      },
      {
        "role": "user",
        "content": [
          {
            "type": "image_url",
            "image_url": {
              "url": "https://raw.githubusercontent.com/kubernetes/kubernetes/master/logo/logo.png"
            }
          },
          {
            "type": "text",
            "text": "Describe this image in detail. What logo or symbol is shown?"
          }
        ]
      }
    ],
    "max_tokens": 200
  }'
echo -e "\n"

echo -e "${GREEN}===========================================================${NC}"
echo -e "${GREEN}  Dual Vision-Language Model Tests Complete${NC}"
echo -e "${GREEN}===========================================================${NC}"
echo ""
echo "Models tested:"
echo "  ✓ Qwen3-VL-8B-Instruct (visual coding, UI agents, video)"
echo "  ✓ NVIDIA Nemotron VL 12B (document intelligence, OCR)"
echo ""
echo "Next steps:"
echo "  1. Test Qwen3-VL with UI screenshots (visual coding)"
echo "  2. Test Nemotron VL with invoices/documents (OCR, extraction)"
echo "  3. Try multi-image comparison (up to 4 images per request)"
echo "  4. Test video frame analysis (extract frames with FFmpeg)"
echo ""
echo "For detailed usage examples, see VISION_MODEL_USAGE.md"
echo ""
