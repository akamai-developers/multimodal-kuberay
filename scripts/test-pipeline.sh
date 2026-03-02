#!/bin/bash
# Test the Deep Research Agent pipeline via the OpenWebUI Pipelines API.
# The pipelines server exposes an OpenAI-compatible /v1/chat/completions endpoint;
# the pipeline is selected by setting model=<pipeline-id>.
set -e

# Resolve the pipelines server URL (internal port-forward or external LB)
PIPELINES_URL="${PIPELINES_URL:-http://localhost:9099}"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}===========================================================\n${NC}"
echo -e "${BLUE}  Deep Research Agent \u2014 Pipeline Smoke Test${NC}"
echo -e "${BLUE}===========================================================\n${NC}"
echo -e "${GREEN}Pipelines URL: ${PIPELINES_URL}${NC}\n"

# \u2500\u2500 1. List available pipelines \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
echo -e "${YELLOW}Step 1: Listing available pipelines${NC}"
echo "-----------------------------------------------------------"
curl --silent \
  --header "Authorization: Bearer ${OPENAI_API_KEY}" \
  "${PIPELINES_URL}/v1/models" | python3 -m json.tool 2>/dev/null || echo "(JSON parse failed)"
echo ""

# \u2500\u2500 2. Submit a research query \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
RESEARCH_TOPIC="${1:-diffusion models for protein structure prediction}"
echo -e "${YELLOW}Step 2: Research query${NC}"
echo "Topic: ${RESEARCH_TOPIC}"
echo "-----------------------------------------------------------"

curl --location --no-buffer \
  --max-time 600 \
  --header "Authorization: Bearer ${OPENAI_API_KEY}" \
  --header "Content-Type: application/json" \
  "${PIPELINES_URL}/v1/chat/completions" \
  --data "{
    \"model\": \"deep-research-agent\",
    \"messages\": [
      {\"role\": \"user\", \"content\": \"${RESEARCH_TOPIC}\"}
    ],
    \"stream\": true
  }"

echo -e "\n\n${GREEN}Pipeline test complete.${NC}"
echo ""
echo "Notes:"
echo "  \u2022 Pass a custom topic: ./scripts/test-pipeline.sh 'attention mechanisms in transformers'"
echo "  \u2022 The pipeline takes 2\u20135 min for a full research query."
echo "  \u2022 OpenWebUI external IP: kubectl get svc openwebui-svc"

