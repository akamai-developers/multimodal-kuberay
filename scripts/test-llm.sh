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
echo -e "${BLUE}  Text-Only Quick Test - Both Models${NC}"
echo -e "${BLUE}===========================================================${NC}"
echo ""
echo -e "${GREEN}Service IP: ${SERVICE_IP}${NC}"
echo ""

# Test Qwen3-VL (text-only mode)
echo -e "${YELLOW}Testing Qwen3-VL-8B (text-only)${NC}"
echo "-----------------------------------------------------------"
curl --location "http://${SERVICE_IP}/v1/chat/completions" \
  --header "Authorization: Bearer ${OPENAI_API_KEY}" \
  --header "Content-Type: application/json" \
  --data '{
    "model": "qwen3-vl-8b-instruct",
    "messages": [
      {"role": "system", "content": "You are a helpful AI assistant."},
      {"role": "user", "content": "Provide 3 key benefits of using Ray for distributed computing."}
    ],
    "max_tokens": 300
  }'
echo -e "\n\n"

# Test Nemotron VL (text-only mode)
echo -e "${YELLOW}Testing Nemotron VL 12B (text-only)${NC}"
echo "-----------------------------------------------------------"
curl --location "http://${SERVICE_IP}/v1/chat/completions" \
  --header "Authorization: Bearer ${OPENAI_API_KEY}" \
  --header "Content-Type: application/json" \
  --data '{
    "model": "nemotron-vl-12b",
    "messages": [
      {"role": "system", "content": "/no_think"},
      {"role": "user", "content": "Provide 3 key benefits of using Kubernetes for container orchestration."}
    ],
    "max_tokens": 300
  }'
echo -e "\n\n"

echo -e "${GREEN}===========================================================${NC}"
echo -e "${GREEN}  Text-Only Tests Complete${NC}"
echo -e "${GREEN}===========================================================${NC}"
echo ""
echo "Note: Both models support vision capabilities. For image/video"
echo "      testing, use: ./scripts/test-vision-llm.sh"
echo ""
