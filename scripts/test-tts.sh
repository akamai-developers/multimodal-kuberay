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
echo -e "${BLUE}  MagpieTTS Text-to-Speech Test${NC}"
echo -e "${BLUE}===========================================================${NC}"
echo ""
echo -e "${GREEN}Service IP: ${SERVICE_IP}${NC}"
echo ""

OUTPUT_FILE="/tmp/tts_output.wav"

# Test 1: Basic English TTS
echo -e "${YELLOW}Test 1: English TTS (Sofia / alloy)${NC}"
echo "-----------------------------------------------------------"
curl --silent --location "http://${SERVICE_IP}/v1/audio/speech" \
  --header "Authorization: Bearer ${OPENAI_API_KEY}" \
  --header "Content-Type: application/json" \
  --output "${OUTPUT_FILE}" \
  --data '{
    "model": "magpie-tts",
    "input": "Hello! Welcome to the NVIDIA MagpieTTS multilingual text to speech system running on KubeRay.",
    "voice": "alloy",
    "language": "en"
  }'
if [ -f "${OUTPUT_FILE}" ] && [ -s "${OUTPUT_FILE}" ]; then
  echo -e "${GREEN}Audio saved to ${OUTPUT_FILE} ($(wc -c < "${OUTPUT_FILE}") bytes)${NC}"
else
  echo -e "${YELLOW}Warning: No audio output received${NC}"
fi
echo ""

# Test 2: Spanish TTS
echo -e "${YELLOW}Test 2: Spanish TTS (Jason / onyx)${NC}"
echo "-----------------------------------------------------------"
curl --silent --location "http://${SERVICE_IP}/v1/audio/speech" \
  --header "Authorization: Bearer ${OPENAI_API_KEY}" \
  --header "Content-Type: application/json" \
  --output "/tmp/tts_spanish.wav" \
  --data '{
    "model": "magpie-tts",
    "input": "Hola, bienvenido al sistema de texto a voz MagpieTTS de NVIDIA.",
    "voice": "onyx",
    "language": "es"
  }'
if [ -f "/tmp/tts_spanish.wav" ] && [ -s "/tmp/tts_spanish.wav" ]; then
  echo -e "${GREEN}Audio saved to /tmp/tts_spanish.wav ($(wc -c < "/tmp/tts_spanish.wav") bytes)${NC}"
else
  echo -e "${YELLOW}Warning: No audio output received${NC}"
fi
echo ""

# Test 3: List models
echo -e "${YELLOW}Test 3: List TTS models${NC}"
echo "-----------------------------------------------------------"
curl --silent --location "http://${SERVICE_IP}/v1/audio/models" \
  --header "Authorization: Bearer ${OPENAI_API_KEY}" | python3 -m json.tool
echo ""

echo -e "${GREEN}===========================================================${NC}"
echo -e "${GREEN}  TTS Tests Complete${NC}"
echo -e "${GREEN}===========================================================${NC}"
echo ""
echo "Speakers: alloy (Sofia), echo (John), fable (Aria), onyx (Jason), nova (Leo)"
echo "Languages: en, es, de, fr, vi, it, zh"
echo ""
echo "Play audio: afplay ${OUTPUT_FILE}  (macOS)"
echo "            aplay ${OUTPUT_FILE}   (Linux)"
