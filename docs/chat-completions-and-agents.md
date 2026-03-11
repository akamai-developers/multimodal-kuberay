# Chat Completions API and Agent Setup

This repo exposes one public OpenAI-compatible endpoint through the Gateway:

- `http://<GATEWAY_IP>/v1/chat/completions`

That endpoint routes to MiniMax M2.5. If you are integrating a client, benchmark, or agent harness, this is the API surface to target.

## What You Need

You need two things before making requests:

- the Gateway base URL
- the bearer token used by the Gateway

In this repo, the bearer token is the value of `OPENAI_API_KEY` in `.env`. There is no separate token creation flow. You choose the value, deploy the stack, and then use that same value in your clients.

If you need to rotate it:

1. change `OPENAI_API_KEY` in `.env`
2. re-deploy so the Gateway picks up the new value
3. update clients, benchmarks, and agent harnesses to send the new token

## Get the Gateway URL and Token

```bash
# 1. Load local environment values
set -a
source .env
set +a

# 2. Resolve the current Gateway IP
export GATEWAY_IP=$(kubectl get gateway llm-gateway -o jsonpath='{.status.addresses[0].value}')

# 3. Build the API base URL
export GATEWAY_BASE_URL="http://${GATEWAY_IP}/v1"

# 4. Optional sanity check
echo "${GATEWAY_BASE_URL}"
echo "${OPENAI_API_KEY}"
```

`GATEWAY_BASE_URL` should include `/v1`. Do not append `/chat/completions` when configuring SDKs or agent providers that expect a base URL.

## Call the API

```bash
curl -X POST "${GATEWAY_BASE_URL}/chat/completions" \
  -H "Authorization: Bearer ${OPENAI_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "minimax-m2.5",
    "messages": [
      {"role": "user", "content": "Summarize recent work on multimodal reasoning."}
    ],
    "stream": true
  }'
```

The important pieces are:

- base URL: `http://${GATEWAY_IP}/v1`
- auth header: `Authorization: Bearer ${OPENAI_API_KEY}`
- model: `minimax-m2.5`

## OpenAI SDK Example

Most OpenAI-compatible clients follow the same pattern: set a base URL, pass the bearer token as the API key, and use the served model name.

```python
from openai import OpenAI

client = OpenAI(
    base_url=gateway_base_url,
    api_key=openai_api_key,
)

response = client.chat.completions.create(
    model="minimax-m2.5",
    messages=[
        {"role": "user", "content": "List three open problems in OCR for scientific PDFs."}
    ],
)

print(response.choices[0].message.content)
```

## OpenCode Setup

OpenCode can use a project-level `opencode.json`. It does not have to be configured globally in `~/.config/opencode`.

This repo includes [opencode.json](../opencode.json), which defines a project-local provider named `multimodal-kuberay` and defaults the model to `multimodal-kuberay/minimax-m2.5`.

That config reads:

- `OPENCODE_BASE_URL` from the environment
- `OPENAI_API_KEY` from the environment

Set them like this:

```bash
set -a
source .env
set +a

export GATEWAY_IP=$(kubectl get gateway llm-gateway -o jsonpath='{.status.addresses[0].value}')
export OPENCODE_BASE_URL="http://${GATEWAY_IP}/v1"
```

Then run OpenCode from the repo:

```bash
opencode run . -m multimodal-kuberay/minimax-m2.5 "Say hello in one sentence."
```

If that works, you have confirmed that the repo-local `opencode.json` is being used and that OpenCode can reach the Gateway with the same bearer token your other clients use.

If you want the provider available across multiple repos, you can copy the same provider block into your global OpenCode config later. For this repo, the local file is enough.

## Related Docs

- [benchmark.md](./benchmark.md) for load and latency testing
- [README.md](../README.md) for deploy and usage overview
