# KubeRay Multi-modal LLM Inference on Linode Kubernetes Engine

Deploy a GPU-accelerated deep research agent on Linode Kubernetes Engine with MCP tool-use, real-time streaming, and an OpenAI-compatible API.

## Overview

This repository demonstrates how to deploy a production-ready deep research agent using KubeRay on Linode Kubernetes Engine (LKE). A user asks a research question and the system autonomously searches arXiv, reads full papers via OCR, and synthesizes a comprehensive research report — all streamed in real time through OpenWebUI or a standard API endpoint.

**Learning Objectives**: Orchestrate GPU workloads on Kubernetes, serve LLMs with Ray Serve, wire up MCP tool servers, and configure secure API gateways.

**Current Stack**:
- **MiniMax M2.5** — Frontier MoE reasoning model (4× Blackwell GPUs, tool-use, 65K context)
- **NVIDIA Nemotron Parse v1.2** — High-throughput OCR model (auto-scales 1–4 replicas across 2× Blackwell nodes)
- **MCP Servers** — ArXiv search + Paper-to-Text OCR, exposed as Streamable HTTP tool servers
- **OpenWebUI** — Chat UI with the deep research pipeline available as a selectable model

## Features

- 🔬 **Deep research pipeline** — Two-phase agent: search & select papers → OCR & synthesize report
- 🛠️ **MCP tool servers** — ArXiv search and PDF-to-text OCR via FastMCP (Streamable HTTP transport)
- 🚀 **OpenAI-compatible API** — Standard `/v1/chat/completions` endpoint via Envoy Gateway
- 🎮 **GPU-accelerated inference** — NVIDIA Blackwell GPU support (8× RTX PRO 6000)
- 🔧 **Infrastructure-as-Code** — Terraform for cluster provisioning, Tilt for deployment orchestration
- 🔐 **Secure by default** — Bearer token authentication, deny-by-default security policies
- 📊 **Full observability** — Grafana dashboards, Prometheus metrics, Ray Dashboard
- ⚡ **Real-time streaming** — Research progress streamed token-by-token to the UI
- 📦 **Model weight caching** — Akamai Object Storage accelerates cold starts via s5cmd

## Architecture

**Components**:
- **Linode LKE** — Managed Kubernetes cluster with GPU node pools (1× 4-GPU + 2× 2-GPU Blackwell nodes)
- **NVIDIA GPU Operator** — Automated GPU driver and runtime management
- **KubeRay Operator** — Ray cluster lifecycle management on Kubernetes
- **Ray Serve** — Scalable LLM serving framework:
  - **MiniMax M2.5** — Frontier MoE model for reasoning and tool-use (4 GPUs, tensor parallelism)
  - **Nemotron Parse v1.2** — Fast OCR model (1 GPU/replica, auto-scales 1–4 replicas)
- **OpenWebUI** — Chat interface with persistent storage and custom branding
- **Pipelines Server** — Hosts the MCP research pipeline, exposes it as a selectable model in OpenWebUI
- **MCP Servers** — FastMCP-based tool servers (ArXiv search, Paper-to-Text OCR)
- **Envoy Gateway** — API gateway with Bearer token authentication and routing
- **Kueue** — Workload queue management for GPU resources
- **kube-prometheus-stack** — Prometheus + Grafana with Ray-specific dashboards
- **Tilt** — Live development environment with automatic reloading

**Request Flow** (Deep Research Pipeline):
1. User submits a research question via OpenWebUI or the Gateway API
2. OpenWebUI routes to the Pipelines server, which runs the MCP research pipeline
3. **Phase 1 — Search & Select**: MiniMax M2.5 calls the ArXiv MCP server to search for and select relevant papers
4. **Phase 2 — Read & Synthesize**: MiniMax M2.5 calls the Paper-to-Text MCP server, which OCRs papers through Nemotron Parse, then writes a comprehensive report
5. The report streams back token-by-token to the user

## Prerequisites

**Required Tools** (with installation links):

- **Linode Account** — [Sign up](https://login.linode.com/signup) | Generate API token from [Cloud Manager](https://cloud.linode.com/profile/tokens)
- **Terraform** (>= 1.0) — [Install Guide](https://developer.hashicorp.com/terraform/install)  
  Quick: `brew install terraform` (macOS) or `choco install terraform` (Windows)
- **Tilt** (>= 0.30) — [Install Guide](https://docs.tilt.dev/install.html)  
  Quick: `curl -fsSL https://raw.githubusercontent.com/tilt-dev/tilt/master/scripts/install.sh | bash`
- **kubectl** — [Install Guide](https://kubernetes.io/docs/tasks/tools/)  
  Quick: `brew install kubectl` (macOS) or `choco install kubernetes-cli` (Windows)
- **HuggingFace Account** — [Sign up](https://huggingface.co/join) | Create [access token](https://huggingface.co/settings/tokens) for model downloads
- **Akamai Object Storage** — For model weight caching (create a bucket and generate access keys from [Cloud Manager](https://cloud.linode.com/object-storage))

## Quick Start

```bash
# 1. Clone this repository
git clone <your-repo-url>
cd multimodal-kuberay

# 2. Configure Terraform variables
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your Linode API token and cluster preferences

# 3. Configure environment variables
cp .env.example .env
# Edit .env with:
#   HUGGINGFACE_TOKEN  — Your HuggingFace access token
#   OPENAI_API_KEY     — Any arbitrary secret for API authentication
#   OBJ_ACCESS_KEY     — Akamai Object Storage access key
#   OBJ_SECRET_KEY     — Akamai Object Storage secret key
#   OBJ_ENDPOINT_HOSTNAME — e.g. us-ord-1.linodeobjects.com
#   OBJ_REGION         — e.g. us-ord-1

# 4. Deploy everything (one command!)
make all

# Expected timeline:
# - Provision LKE cluster with GPU nodes: ~5-10 minutes
# - Install operators (GPU, KubeRay, Envoy, Kueue): ~5 minutes
# - Upload models to Object Storage: ~10-15 minutes
# - Deploy MiniMax M2.5 + Nemotron Parse + MCP servers: ~10-15 minutes
```

Once complete, access the Tilt UI at http://localhost:10350 to monitor deployment status.

## Configuration

### Terraform Variables (`terraform.tfvars`)

| Variable             | Description                  | Default                              | Options/Notes                                                                                               |
|----------------------|------------------------------|--------------------------------------|-------------------------------------------------------------------------------------------------------------|
| `linode_token`       | Linode API token             | (required)                           | Generate from Cloud Manager                                                                                 |
| `cluster_label`      | Cluster name                 | `"myllm"`                            | Any descriptive string                                                                                      |
| `region`             | Linode region                | `"us-lax"`                           | [Available regions](https://www.linode.com/docs/products/platform/get-started/guides/choose-a-data-center/) |
| `kubernetes_version` | Kubernetes version           | `"1.34"`                             | Check LKE supported versions                                                                                |
| `gpu_big_node_type`  | Large GPU node type (MiniMax)| `"g3-gpu-rtxpro6000-blackwell-4"`    | 4× Blackwell GPUs — hosts MiniMax M2.5                                                                     |
| `gpu_big_node_count` | Number of large GPU nodes    | `1`                                  | 1 node for the MoE model                                                                                   |
| `gpu_node_type`      | Small GPU node type (OCR)    | `"g3-gpu-rtxpro6000-blackwell-2"`    | 2× Blackwell GPUs — hosts Nemotron Parse replicas                                                           |
| `gpu_node_count`     | Number of small GPU nodes    | `2`                                  | 2 nodes → up to 4 OCR replicas                                                                              |
| `tags`               | Resource tags                | `["kuberay", "llm", "gpu"]`          | For organization and tracking                                                                               |

### Environment Variables (`.env`)

| Variable               | Required | Description                                              |
|------------------------|----------|----------------------------------------------------------|
| `HUGGINGFACE_TOKEN`    | Yes      | HuggingFace access token for model downloads             |
| `OPENAI_API_KEY`       | Yes      | Arbitrary secret for API authentication (Bearer token)   |
| `OBJ_ACCESS_KEY`       | Yes      | Akamai Object Storage access key                         |
| `OBJ_SECRET_KEY`       | Yes      | Akamai Object Storage secret key                         |
| `OBJ_ENDPOINT_HOSTNAME`| Yes     | Object Storage endpoint (e.g. `us-ord-1.linodeobjects.com`) |
| `OBJ_REGION`           | Yes      | Object Storage region (e.g. `us-ord-1`)                  |
| `MODEL_BUCKET`         | No       | Bucket name for cached model weights (default: `model-cache`) |

### Model Configuration

**Deployed Models**:

1. **MiniMax M2.5** (`minimax-m2.5`)
   - **Role**: Primary reasoning model — orchestrates the research pipeline via tool-use
   - **Developer**: MiniMax
   - **Architecture**: Mixture of Experts (MoE)
   - **GPU Allocation**: 4 GPUs (tensor parallelism on a single 4-GPU Blackwell node)
   - **Context Window**: 65,536 tokens
   - **Capabilities**: Tool calling, chain-of-thought reasoning, structured output
   - **Model Source**: Cached in Akamai Object Storage, synced to local volume at boot

2. **NVIDIA Nemotron Parse v1.2** (`nvidia/NVIDIA-Nemotron-Parse-v1.2`)
   - **Role**: OCR engine — converts PDF pages to structured text for the research pipeline
   - **Developer**: NVIDIA
   - **GPU Allocation**: 1 GPU per replica (auto-scales 1–4 replicas across 2× 2-GPU nodes)
   - **Context Window**: 8,192 tokens
   - **Capabilities**: Page-level OCR with layout preservation, 30+ language support
   - **Scaling**: Aggressive autoscaling (3s upscale delay, 2s metrics interval) for burst OCR workloads
   - **Model Source**: Cached in Akamai Object Storage, synced to local volume at boot

### MCP Tool Servers

| Server | Endpoint | Tools | Description |
|--------|----------|-------|-------------|
| ArXiv Search | `http://mcp-arxiv-search-svc:8000/mcp` | `search_arxiv`, `get_paper_info` | Search arXiv by query, retrieve paper metadata |
| Paper-to-Text | `http://mcp-paper-to-text-svc:8000/mcp` | `read_papers`, `read_single_paper` | Download PDFs, render pages, OCR via Nemotron Parse |

Both servers use FastMCP with Streamable HTTP transport and Bearer token authentication.

## Usage

### Accessing Services

Once deployed, the following services are available:

- **Tilt Dashboard**: http://localhost:10350  
  Monitor deployment status, view logs, and manage resources

- **OpenWebUI**: `kubectl get svc openwebui-svc` for the external LoadBalancer IP  
  Chat interface — select "MiniMax M2.5" for direct chat or "Deep Research Agent" for the research pipeline

- **MiniMax Ray Dashboard**: http://localhost:8265 (via Tilt port-forward)  
  View cluster metrics, task execution, and resource utilization

- **MiniMax API**: http://localhost:8000 (via Tilt port-forward)  
  Direct access to MiniMax M2.5 serving endpoint (bypasses Gateway)

- **Nemotron Parse Ray Dashboard**: http://localhost:18265 (via Tilt port-forward)  
  Monitor OCR model replicas and autoscaling

- **Grafana**: http://localhost:3000 (via Tilt port-forward)  
  Pre-configured Ray dashboards for model cache, serve deployments, and LLM metrics

- **Gateway API**: `kubectl get gateway llm-gateway` for the external LoadBalancer IP  
  OpenAI-compatible API with Bearer token authentication

### Making API Requests

#### Using Test Scripts

```bash
# Smoke test — simple chat completion via the Gateway
make test

# Full research pipeline test — streams a deep research query
make test-research

# Custom research topic
./scripts/test-pipeline.sh "attention mechanisms in transformers"
```

#### Manual API Requests

**Chat completion (via Gateway)**:
```bash
# 1. Get the Gateway service IP
export SERVICE_IP=$(kubectl get gateway llm-gateway -o jsonpath='{.status.addresses[0].value}')

# 2. Send a request to MiniMax M2.5
curl -X POST "http://${SERVICE_IP}/v1/chat/completions" \
  -H "Authorization: Bearer ${OPENAI_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "minimax-m2.5",
    "messages": [
      {"role": "system", "content": "You are a helpful research assistant."},
      {"role": "user", "content": "List 3 open problems in quantum computing."}
    ],
    "max_tokens": 400,
    "temperature": 1.0
  }'
```

**Deep research query (via Pipelines)**:
```bash
# The Pipelines server runs on port 9099 (port-forwarded by Tilt for openwebui-pipelines)
curl --no-buffer \
  -H "Authorization: Bearer ${OPENAI_API_KEY}" \
  -H "Content-Type: application/json" \
  "http://localhost:9099/v1/chat/completions" \
  -d '{
    "model": "deep-research-agent",
    "messages": [
      {"role": "user", "content": "diffusion models for protein structure prediction"}
    ],
    "stream": true
  }'
```

**Authentication**: Replace `${OPENAI_API_KEY}` with the value you set in your `.env` file.

### Monitoring Deployment Status

```bash
# Check overall status
make status

# View Tilt UI for detailed resource status
# Open http://localhost:10350 in your browser

# Check specific Kubernetes resources
kubectl get gateway llm-gateway
kubectl get rayservice ray-serve-minimax
kubectl get rayservice ray-serve-nemotron-parse
kubectl get pods -l app.kubernetes.io/name=kuberay-operator
```

## Development Workflow

For detailed development workflows, code style guidelines, and agentic coding instructions, see [AGENTS.md](./AGENTS.md).

### Common Commands

```bash
make help           # Show all available commands
make status         # Check deployment status
make up             # Start Tilt in interactive mode
make ci             # Run Tilt in CI mode (non-interactive)
make down           # Tear down Tilt resources (keeps cluster running)
make test           # Smoke test the MiniMax M2.5 API
make test-research  # Run a full research pipeline test
make destroy        # Destroy the entire LKE cluster
make clean          # Clean up local files
```

### Making Changes

- **Kubernetes Manifests** (`manifests/*.yaml`) — Tilt auto-reloads on save
- **Pipeline Code** (`serve/*.py`) — Tilt auto-reloads the ConfigMap and restarts the Pipelines pod
- **MCP Servers** (`mcp/*.py`) — Tilt auto-reloads the ConfigMap and restarts the MCP pods
- **Tiltfile** — Tilt auto-reloads on save
- **Terraform** (`*.tf`) — Run `make plan` then `make apply`

## Cleanup

### Stop Kubernetes Resources (Keep Cluster)

```bash
make down
```

This tears down all Kubernetes resources (Ray Serve, Gateway, MCP servers, OpenWebUI, operators) while keeping your LKE cluster running. It also cleans up CRDs, NVIDIA node labels, stale webhooks, and Tilt-created namespaces to restore a vanilla LKE cluster.

### Destroy Everything

```bash
# Destroy the entire LKE cluster and all infrastructure
make destroy

# Clean up local files (kubeconfig, Terraform state)
make clean
```

**Warning**: `make destroy` permanently deletes your LKE cluster and all associated resources.

## Project Structure

```
multimodal-kuberay/
├── Makefile                        # Build/deploy/test commands
├── Tiltfile                        # Kubernetes deployment orchestration (~570 lines)
├── main.tf                         # Terraform: LKE cluster with GPU node pools
├── variables.tf                    # Terraform: Input variables
├── outputs.tf                      # Terraform: Outputs (kubeconfig, cluster ID)
├── terraform.tfvars.example        # Example Terraform configuration
├── .env.example                    # Example environment variables
├── assets/
│   └── custom.css                  # OpenWebUI custom branding CSS
├── hack/
│   ├── monitoring-values.yaml      # kube-prometheus-stack Helm values
│   └── grafana-dashboards/         # 7 Ray-specific Grafana dashboards
│       ├── data_grafana_dashboard.json
│       ├── default_grafana_dashboard.json
│       ├── model_cache_grafana_dashboard.json
│       ├── serve_deployment_grafana_dashboard.json
│       ├── serve_grafana_dashboard.json
│       ├── serve_llm_grafana_dashboard.json
│       └── train_grafana_dashboard.json
├── manifests/
│   ├── gateway.yaml                # Envoy Gateway + SecurityPolicy + ClientTrafficPolicy
│   ├── rayservice-minimax.yaml     # MiniMax M2.5 RayService (4 GPUs)
│   ├── rayservice-nemotron-parse.yaml  # Nemotron Parse v1.2 RayService (auto-scaling)
│   ├── openwebui.yaml              # OpenWebUI + Pipelines server deployments
│   ├── mcp-arxiv-search.yaml       # ArXiv Search MCP server
│   ├── mcp-paper-to-text.yaml      # Paper-to-Text OCR MCP server
│   ├── model-upload-job.yaml       # Job: caches models to Object Storage
│   ├── ray-podmonitor.yaml         # Prometheus PodMonitor for Ray metrics
│   └── kustomization.yaml          # Kustomize configuration
├── mcp/
│   ├── common.py                   # Shared BearerAuthMiddleware for MCP servers
│   ├── arxiv_search_server.py      # FastMCP server: search_arxiv, get_paper_info
│   └── paper_to_text_server.py     # FastMCP server: read_papers, read_single_paper
├── serve/
│   └── mcp_research_pipeline.py    # Deep research pipeline (OpenWebUI Pipelines)
├── scripts/
│   ├── model-sync.sh               # s5cmd-based Object Storage model downloader
│   ├── test-llm.sh                 # MiniMax M2.5 API smoke test
│   └── test-pipeline.sh            # Deep research pipeline test
├── AGENTS.md                       # Guide for AI coding agents
└── README.md                       # This file
```

## Troubleshooting

### Common Issues

**Tilt fails to connect to cluster**
```bash
# Ensure KUBECONFIG is set correctly
export KUBECONFIG=$(pwd)/kubeconfig
make up
```

**Pods stuck in Pending on GPU nodes**
```bash
# Check GPU operator installation status
kubectl get pods -n gpu-operator

# View GPU operator logs
kubectl logs -n gpu-operator -l app=nvidia-gpu-operator
```

**Model download is slow or stuck**
```bash
# First run uploads models to Object Storage (~10-15 min for MiniMax M2.5)
# Subsequent runs sync from Object Storage (much faster)
# Check the model-upload job and worker init container logs:
kubectl logs job/model-upload -f
kubectl logs -l ray.io/node-type=worker -c model-download --tail=100 -f
```

**Kueue webhook errors on resource creation**
```bash
# If resources fail with "failed calling webhook", clean up stale webhooks:
kubectl delete mutatingwebhookconfigurations -l app.kubernetes.io/name=kueue
kubectl delete validatingwebhookconfigurations -l app.kubernetes.io/name=kueue
# Then re-deploy:
make up
```

**Gateway not accessible**
```bash
# Check Gateway status and IP allocation
kubectl get gateway llm-gateway
kubectl describe gateway llm-gateway

# Verify HTTPRoute is configured
kubectl get httproute llm-route
```

**Authentication failures (401 Unauthorized)**
```bash
# Verify your OPENAI_API_KEY matches between .env and your API request
# The Bearer token in the Authorization header must match exactly
```

**Research pipeline times out or produces no output**
```bash
# Check that both MCP servers are healthy
kubectl get pods -l app=mcp-arxiv-search
kubectl get pods -l app=mcp-paper-to-text

# Verify Nemotron Parse is serving (needed for OCR)
kubectl get rayservice ray-serve-nemotron-parse

# Check the Pipelines server logs for errors
kubectl logs -l app=openwebui-pipelines --tail=100 -f
```

### Getting More Help

- **Tilt UI**: http://localhost:10350 — Shows detailed resource status and logs
- **MiniMax Ray Dashboard**: http://localhost:8265 — View cluster and serving metrics
- **Nemotron Parse Ray Dashboard**: http://localhost:18265 — Monitor OCR autoscaling
- **Grafana**: http://localhost:3000 — Ray-specific dashboards (default login: admin/prom-operator)
- **Kubernetes Logs**: `kubectl logs <pod-name>` — View detailed pod logs
- **AGENTS.md**: Detailed development workflows and troubleshooting

---

**Questions or Issues?** This is a learning/demo project. Feel free to experiment, break things, and rebuild! The entire environment can be recreated with `make all`.
