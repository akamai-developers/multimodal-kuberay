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
echo -e "${BLUE}  VLM → TTS Pipeline Test (Describe and Speak)${NC}"
echo -e "${BLUE}===========================================================${NC}"
echo ""
echo -e "${GREEN}Service IP: ${SERVICE_IP}${NC}"
echo ""

# Test 1: Text-only prompt → Speech
echo -e "${YELLOW}Test 1: Text prompt → Speech${NC}"
echo "-----------------------------------------------------------"
HTTP_CODE=$(curl --silent --location --max-time 180 \
  --output /tmp/pipeline_text.wav \
  --write-out "%{http_code}" \
  "http://${SERVICE_IP}/v1/audio/describe" \
  --header "Authorization: Bearer ${OPENAI_API_KEY}" \
  --header "Content-Type: application/json" \
  --data '{
    "model": "qwen3-vl-8b-instruct",
    "messages": [
      {"role": "user", "content": "In one sentence, what is Kubernetes?"}
    ],
    "voice": "alloy",
    "max_tokens": 100
  }')
echo "HTTP Status: ${HTTP_CODE}"
if [ -f /tmp/pipeline_text.wav ] && [ -s /tmp/pipeline_text.wav ]; then
  echo -e "${GREEN}Audio saved to /tmp/pipeline_text.wav ($(wc -c < /tmp/pipeline_text.wav) bytes)${NC}"
else
  echo -e "${YELLOW}Warning: No audio output received${NC}"
  cat /tmp/pipeline_text.wav 2>/dev/null
fi
echo ""

# Test 2: Image description → Speech
echo -e "${YELLOW}Test 2: Image (Kubernetes logo) → Speech${NC}"
echo "-----------------------------------------------------------"
HTTP_CODE=$(curl --silent --location --max-time 180 \
  --output /tmp/pipeline_image.wav \
  --write-out "%{http_code}" \
  "http://${SERVICE_IP}/v1/audio/describe" \
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
            "text": "Describe this logo in one sentence."
          }
        ]
      }
    ],
    "voice": "echo",
    "max_tokens": 150
  }')
echo "HTTP Status: ${HTTP_CODE}"
if [ -f /tmp/pipeline_image.wav ] && [ -s /tmp/pipeline_image.wav ]; then
  echo -e "${GREEN}Audio saved to /tmp/pipeline_image.wav ($(wc -c < /tmp/pipeline_image.wav) bytes)${NC}"
else
  echo -e "${YELLOW}Warning: No audio output received${NC}"
  cat /tmp/pipeline_image.wav 2>/dev/null
fi
echo ""

# Test 3: Spanish voice output
echo -e "${YELLOW}Test 3: Spanish prompt → Spanish Speech${NC}"
echo "-----------------------------------------------------------"
HTTP_CODE=$(curl --silent --location --max-time 180 \
  --output /tmp/pipeline_spanish.wav \
  --write-out "%{http_code}" \
  "http://${SERVICE_IP}/v1/audio/describe" \
  --header "Authorization: Bearer ${OPENAI_API_KEY}" \
  --header "Content-Type: application/json" \
  --data '{
    "model": "qwen3-vl-8b-instruct",
    "messages": [
      {"role": "user", "content": "Responde en español: ¿Qué es la inteligencia artificial en una oración?"}
    ],
    "voice": "onyx",
    "language": "es",
    "max_tokens": 100
  }')
echo "HTTP Status: ${HTTP_CODE}"
if [ -f /tmp/pipeline_spanish.wav ] && [ -s /tmp/pipeline_spanish.wav ]; then
  echo -e "${GREEN}Audio saved to /tmp/pipeline_spanish.wav ($(wc -c < /tmp/pipeline_spanish.wav) bytes)${NC}"
else
  echo -e "${YELLOW}Warning: No audio output received${NC}"
  cat /tmp/pipeline_spanish.wav 2>/dev/null
fi
echo ""

echo -e "${GREEN}===========================================================${NC}"
echo -e "${GREEN}  Pipeline Tests Complete${NC}"
echo -e "${GREEN}===========================================================${NC}"
echo ""
echo "Play audio:  afplay /tmp/pipeline_text.wav   (macOS)"
echo "             afplay /tmp/pipeline_image.wav   (macOS)"
echo "             afplay /tmp/pipeline_spanish.wav  (macOS)"
