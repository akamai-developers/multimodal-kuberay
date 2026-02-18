# KubeRay Multi-modal LLM Inference on Linode Kubernetes Engine

Deploy GPU-accelerated LLM inference on Linode Kubernetes Engine with OpenAI-compatible API endpoints.

## Overview

This repository demonstrates how to deploy production-ready, GPU-accelerated Large Language Model (LLM) inference using KubeRay on Linode Kubernetes Engine (LKE). It provides a foundation for building multi-modal AI deployments with configurable models, secure API access, and Infrastructure-as-Code best practices.

**Learning Objectives**: Understand how to orchestrate GPU workloads on Kubernetes, manage LLM serving with Ray Serve, and configure secure API gateways.

**Current State**: Dual vision-language model deployment for comparison and benchmarking:
- **Qwen3-VL-8B-Instruct** - Alibaba's vision-language model (general vision, visual coding, UI agents)
- **NVIDIA Nemotron Nano 12B v2 VL** - NVIDIA's vision-language model (document intelligence, OCR)

## Features

- 🚀 **OpenAI-compatible API** - Standard `/v1/chat/completions` endpoint via Envoy Gateway
- 🎮 **GPU-accelerated inference** - NVIDIA Blackwell/Ada GPU support
- 🔧 **Infrastructure-as-Code** - Terraform for cluster provisioning, Tilt for deployment orchestration
- 🔐 **Secure by default** - API key authentication, deny-by-default security policies
- 📊 **Observable** - Ray Dashboard for cluster metrics and monitoring
- 🎯 **Dual vision-language models** - Compare Qwen3-VL vs Nemotron VL performance
- 🖼️ **Advanced vision capabilities** - Multi-image reasoning, OCR, document intelligence, visual coding
- 📹 **Video understanding** - Process video frames for temporal analysis

## Architecture

**Components**:
- **Linode LKE** - Managed Kubernetes cluster with GPU node pools
- **NVIDIA GPU Operator** - Automated GPU driver and runtime management
- **KubeRay Operator** - Ray cluster lifecycle management on Kubernetes
- **Ray Serve** - Scalable LLM serving framework with dual vision-language models:
  - **Qwen3-VL-8B** - General vision + visual coding (8.29B params, 2 GPUs)
  - **Nemotron VL 12B** - Document intelligence + OCR (12.6B params, 2 GPUs)
- **Envoy Gateway** - API gateway with authentication and routing
- **Kueue** - Workload queue management for GPU resources
- **Tilt** - Live development environment with automatic reloading

## Prerequisites

**Required Tools** (with installation links):

- **Linode Account** - [Sign up](https://login.linode.com/signup) | Generate API token from [Cloud Manager](https://cloud.linode.com/profile/tokens)
- **Terraform** (>= 1.0) - [Install Guide](https://developer.hashicorp.com/terraform/install)  
  Quick: `brew install terraform` (macOS) or `choco install terraform` (Windows)
- **Tilt** (>= 0.30) - [Install Guide](https://docs.tilt.dev/install.html)  
  Quick: `curl -fsSL https://raw.githubusercontent.com/tilt-dev/tilt/master/scripts/install.sh | bash`
- **kubectl** - [Install Guide](https://kubernetes.io/docs/tasks/tools/)  
  Quick: `brew install kubectl` (macOS) or `choco install kubernetes-cli` (Windows)
- **HuggingFace Account** - [Sign up](https://huggingface.co/join) | Create [access token](https://huggingface.co/settings/tokens) for model downloads

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
#   HUGGINGFACE_TOKEN - Your HuggingFace access token
#   OPENAI_API_KEY - Any arbitrary secret for API authentication

# 4. Deploy everything (one command!)
make all

# Expected timeline:
# - Provision LKE cluster with GPU nodes: ~5-10 minutes
# - Install GPU operators and KubeRay: ~5 minutes
# - Deploy LLM service and download model: ~10-15 minutes
```

Once complete, access the Tilt UI at http://localhost:10350 to monitor deployment status.

## Configuration

### Terraform Variables (`terraform.tfvars`)

| Variable             | Description            | Default                           | Options/Notes                                                                                               |
|----------------------|------------------------|-----------------------------------|-------------------------------------------------------------------------------------------------------------|
| `linode_token`       | Linode API token       | (required)                        | Generate from Cloud Manager                                                                                 |
| `cluster_label`      | Cluster name           | `"myllm"`                         | Any descriptive string                                                                                      |
| `region`             | Linode region          | `"ca-central"`                    | [Available regions](https://www.linode.com/docs/products/platform/get-started/guides/choose-a-data-center/) |
| `kubernetes_version` | Kubernetes version     | `"1.34"`                          | Check LKE supported versions                                                                                |
| `gpu_node_type`      | GPU node instance type | `"g3-gpu-rtxpro6000-blackwell-2"` | `g3-gpu-rtxpro6000-blackwell-2` (Blackwell), `g2-gpu-rtx4000a4-m` (Ada)                                     |
| `gpu_node_count`     | Number of GPU nodes    | `3`                               | 1-10+ depending on workload                                                                                 |
| `tags`               | Resource tags          | `["kuberay", "llm", "gpu"]`       | For organization and tracking                                                                               |

### Environment Variables (`.env`)

- **`HUGGINGFACE_TOKEN`** - Required for downloading models from HuggingFace Hub  
  Generate at: https://huggingface.co/settings/tokens

- **`OPENAI_API_KEY`** - Arbitrary secret string for API authentication  
  Example: `my-secret-api-key-12345`  
  **Note**: For demonstration purposes only. In production, use proper secret management (HashiCorp Vault, AWS Secrets Manager, etc.)

### LLM Model Configuration

**Deployed Models**:

1. **Qwen3-VL-8B-Instruct** (`qwen3-vl-8b-instruct`)
   - **Type**: Vision-language model
   - **Developer**: Alibaba (Qwen Team)
   - **Parameters**: 8.29 billion
   - **GPU Allocation**: 2 GPUs (tensor parallelism)
   - **Context Window**: 256K native (expandable to 1M)
   - **Max Images**: 4 images + 1 video per request
   - **Best For**: General vision understanding, visual coding (HTML/CSS from screenshots), UI agents, spatial reasoning
   - **License**: Apache 2.0

2. **NVIDIA Nemotron Nano 12B v2 VL** (`nemotron-vl-12b`)
   - **Type**: Vision-language model
   - **Developer**: NVIDIA
   - **Parameters**: 12.6 billion
   - **GPU Allocation**: 2 GPUs (tensor parallelism)
   - **Context Window**: 128K
   - **Max Images**: 4 images per request
   - **Max Resolution**: 3072×1024 pixels (12 tiles @ 512×512)
   - **Best For**: Document intelligence, invoice/receipt processing, OCR (32 languages), technical diagrams
   - **License**: NVIDIA Open Model License

**Model Comparison**:
- **Qwen3-VL**: Better for general vision tasks, visual coding, UI understanding, video analysis
- **Nemotron VL**: Better for structured documents, invoices, OCR, technical diagram analysis

**Customizing Models**:
1. Edit `manifests/rayservice.yaml`
2. Modify the `llm_configs` array to add/remove/change models
3. Adjust `tensor_parallel_size` and `gpu_memory_utilization` based on model size
4. Redeploy with `make up` (Tilt auto-reloads)

**See Also**: [VISION_MODEL_USAGE.md](VISION_MODEL_USAGE.md) for detailed vision model documentation and examples.

## Usage

### Accessing Services

Once deployed, the following services are available:

- **Tilt Dashboard**: http://localhost:10350  
  Monitor deployment status, view logs, and manage resources

- **Ray Dashboard**: http://localhost:8265 (via Tilt port-forward)  
  View cluster metrics, task execution, and resource utilization

- **Ray Serve**: http://localhost:8000 (via Tilt port-forward)  
  Direct access to LLM serving endpoint (bypasses Gateway)

### Making API Requests

#### Using Test Scripts

```bash
# Test vision-language models (both Qwen3-VL and Nemotron VL)
./scripts/test-vision-llm.sh
```

#### Manual API Requests

**Vision request (Qwen3-VL - General Vision)**:
```bash
# 1. Get the Gateway service IP
export SERVICE_IP=$(kubectl get gateway llm-gateway -o jsonpath='{.status.addresses[0].value}')

# 2. Test Qwen3-VL with image
curl -X POST "http://${SERVICE_IP}/v1/chat/completions" \
  -H "Authorization: Bearer ${OPENAI_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-vl-8b-instruct",
    "messages": [
      {
        "role": "user",
        "content": [
          {
            "type": "image_url",
            "image_url": {
              "url": "https://example.com/screenshot.png"
            }
          },
          {
            "type": "text",
            "text": "Generate HTML/CSS code to recreate this UI design."
          }
        ]
      }
    ],
    "max_tokens": 2048
  }'
```

**Vision request (Nemotron VL - Document Intelligence)**:
```bash
curl -X POST "http://${SERVICE_IP}/v1/chat/completions" \
  -H "Authorization: Bearer ${OPENAI_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nemotron-vl-12b",
    "messages": [
      {
        "role": "user",
        "content": [
          {
            "type": "image_url",
            "image_url": {
              "url": "https://example.com/invoice.png"
            }
          },
          {
            "type": "text",
            "text": "Extract all line items from this invoice with quantities and prices."
          }
        ]
      }
    ],
    "max_tokens": 1024
  }'
```

**Authentication**: Replace `${OPENAI_API_KEY}` with the value you set in your `.env` file.

**For detailed vision model usage**: See [VISION_MODEL_USAGE.md](VISION_MODEL_USAGE.md) for comprehensive examples including multi-image requests, document intelligence, and troubleshooting.

### Monitoring Deployment Status

```bash
# Check overall status
make status

# View Tilt UI for detailed resource status
# Open http://localhost:10350 in your browser

# Check specific Kubernetes resources
kubectl get gateway llm-gateway
kubectl get rayservice ray-serve-llm
kubectl get pods -l app.kubernetes.io/name=kuberay-operator
```

## Development Workflow

For detailed development workflows, code style guidelines, and agentic coding instructions, see [AGENTS.md](./AGENTS.md).

### Common Commands

```bash
make help       # Show all available commands
make status     # Check deployment status
make up         # Start Tilt (after infrastructure provisioned)
make down       # Stop Tilt resources (keeps cluster running)
make test       # Test the LLM API endpoint
make destroy    # Destroy the entire LKE cluster
make clean      # Clean up local files
```

### Making Changes

- **Kubernetes Manifests** (`manifests/*.yaml`) - Tilt auto-reloads on save
- **Tiltfile** - Tilt auto-reloads on save
- **Terraform** (`*.tf`) - Run `make plan` then `make apply`

## Cleanup

### Stop Kubernetes Resources (Keep Cluster)

```bash
make down
```

This tears down the Ray Serve deployment, Gateway, and operators while keeping your LKE cluster running.

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
├── Makefile                    # Convenient commands for operations
├── Tiltfile                    # Kubernetes deployment orchestration
├── main.tf                     # Terraform: LKE cluster definition
├── variables.tf                # Terraform: Input variables
├── outputs.tf                  # Terraform: Outputs (kubeconfig, etc.)
├── terraform.tfvars.example    # Example Terraform configuration
├── .env.example                # Example environment variables
├── hack/                       # random scripts and utilities
│   ├── monitoring-values.yaml  # values for the grafana deployment
├── manifests/                  # Kubernetes manifests
│   ├── gateway.yaml            # Envoy Gateway + SecurityPolicy
│   ├── rayservice.yaml         # Ray Serve LLM deployment
│   └── kustomization.yaml      # Kustomize configuration
├── scripts/
│   └── test-llm.sh             # LLM API test script
├── AGENTS.md                   # Detailed guide for AI coding agents
└── README.md                   # This file
```

## Roadmap

Future enhancements planned for this project:

- [ ] Multi-modal model support (vision + language models)
- [ ] Multiple concurrent models with intelligent routing
- [ ] Horizontal autoscaling based on request load
- [ ] Comprehensive monitoring and observability stack (Prometheus, Grafana)
- [ ] CI/CD pipeline for automated testing and deployment
- [ ] Support for additional cloud providers (AWS, GCP, Azure)

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
# HuggingFace model downloads can take 10-15 minutes
# Check Ray Serve pod logs for progress
kubectl logs -l ray.io/node-type=worker --tail=100 -f
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

### Getting More Help

- **Tilt UI**: http://localhost:10350 - Shows detailed resource status and logs
- **Ray Dashboard**: http://localhost:8265 - View cluster and serving metrics
- **Kubernetes Logs**: `kubectl logs <pod-name>` - View detailed pod logs
- **AGENTS.md**: Detailed development workflows and troubleshooting

---

**Questions or Issues?** This is a learning/demo project. Feel free to experiment, break things, and rebuild! The entire environment can be recreated with `make all`.
