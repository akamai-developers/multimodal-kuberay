#!/bin/bash
set -e

# Get Gateway service IP
export SERVICE_IP=$(kubectl get gateway llm-gateway -ojsonpath="{.status.addresses[0].value}")

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}===========================================================\n${NC}"
echo -e "${BLUE}  MiniMax M2.5 — Smoke Test${NC}"
echo -e "${BLUE}===========================================================\n${NC}"
echo -e "${GREEN}Gateway IP: ${SERVICE_IP}${NC}\n"

echo -e "${YELLOW}Test 1: Simple chat completion — tool-use capable model${NC}"
echo "-----------------------------------------------------------"
curl --location "http://${SERVICE_IP}/v1/chat/completions" \
  --header "Authorization: Bearer ${OPENAI_API_KEY}" \
  --header "Content-Type: application/json" \
  --data '{
    "model": "minimax-m2.5",
    "messages": [
      {"role": "system", "content": "You are a helpful research assistant."},
      {"role": "user", "content": "List 3 open problems in quantum computing in one sentence each."}
    ],
    "max_tokens": 400,
    "temperature": 1.0,
    "top_p": 0.95
  }'
echo -e "\n\n"

echo -e "${GREEN}===========================================================\n${NC}"
echo -e "${GREEN}  Smoke test complete${NC}"
echo -e "${GREEN}===========================================================\n${NC}"
