# AGENTS.md - Guide for Agentic Coding Assistants

This document provides coding standards, workflows, and commands for AI agents working in the `multimodal-kuberay` repository.

## Project Overview

**KubeRay GPU LLM Quickstart** - Infrastructure-as-Code project deploying GPU-accelerated LLM inference on Linode Kubernetes Engine (LKE) using KubeRay, Envoy Gateway, and Ray Serve.

**Tech Stack**:
- Terraform (HCL) - Linode LKE cluster provisioning
- Tiltfile (Starlark) - Kubernetes deployment orchestration
- Kubernetes manifests (YAML) - Gateway, RayService resources
- Bash scripts - Manual testing utilities
- direnv - Development environment management

**Key Components**:
- NVIDIA GPU Operator (Blackwell/Ada GPUs)
- KubeRay Operator + RayService (Qwen3-VL-8B + Nemotron VL 12B vision-language models)
- Envoy Gateway (OpenAI-compatible API)
- Kueue (workload queue management)

---

## Build/Test/Lint Commands

### Quick Start (Makefile)
```bash
# View all available commands
make help

# Complete workflow: init → apply → deploy
make all

# Infrastructure only
make apply

# Deployment only
make up

# Check status
make status

# Run LLM test
make test

# Cleanup
make down      # Tear down Tilt resources
make destroy   # Destroy infrastructure
make clean     # Remove local files
```

### Environment Setup
```bash
# Required: Create .env from template
cp .env.example .env
# Edit .env with: HUGGINGFACE_TOKEN, OPENAI_API_KEY
```

### Terraform Commands
```bash
# Makefile (recommended)
make init      # Initialize Terraform
make plan      # Run Terraform plan
make apply     # Apply + download kubeconfig
make destroy   # Destroy infrastructure

# Direct terraform commands
terraform init
terraform plan
terraform apply
terraform destroy
terraform fmt      # Format Terraform files
terraform validate # Validate configuration
```

### Kubeconfig Management
```bash
# Download/update kubeconfig from Terraform
make kubeconfig

# The Makefile automatically:
# - Extracts kubeconfig from Terraform output
# - Saves to ./kubeconfig with secure permissions (600)
# - Sets KUBECONFIG environment variable if not already set
```

### Tilt Commands
```bash
# Makefile (recommended - handles KUBECONFIG automatically)
make up   # Interactive mode
make ci   # CI/non-interactive mode
make down # Tear down resources

# Direct tilt commands (ensure KUBECONFIG is set)
export KUBECONFIG=$(pwd)/kubeconfig
tilt up        # Interactive
tilt ci        # Non-interactive/CI mode
tilt down      # Tear down

# View Tilt UI
# Open browser to http://localhost:10350
```

### Testing Commands
```bash
# Makefile (recommended)
make test    # Run LLM API test
make status  # Show cluster and deployment status

# Manual testing
./scripts/test-llm.sh

# Get Gateway service IP
kubectl get gateway llm-gateway -ojsonpath="{.status.addresses[0].value}"

# Check Ray dashboard (via port-forward from Tilt)
# http://localhost:8265

# Check Ray Serve (via port-forward from Tilt)
# http://localhost:8000
```

### Kubernetes Commands
```bash
# Apply manifests directly (NOT RECOMMENDED - use Tilt instead)
kubectl apply -f manifests/gateway.yaml

# Check RayService status
kubectl get rayservice ray-serve-llm

# Check Gateway status
kubectl get gateway llm-gateway

# View logs
kubectl logs -l app.kubernetes.io/name=kuberay-operator
```

### Linting/Formatting
**No automated linting configured**. Follow style guidelines below manually.

---

## Code Style Guidelines

### General Principles
1. **Security First**: Never commit secrets. Use `.env` files (gitignored) and inject via Tiltfile
2. **Explicit Versions**: Always pin component versions (allow env var overrides)
3. **Clear Dependencies**: Specify resource dependencies explicitly in Tiltfile
4. **Descriptive Naming**: Use function-component-suffix pattern

### File Naming Conventions

**Terraform**: Lowercase, snake_case
- Files: `main.tf`, `variables.tf`, `outputs.tf`
- Resources: `gpu_cluster`, `gpu_node_type`
- Example files: `terraform.tfvars.example`

**Kubernetes Manifests**: Lowercase, hyphenated
- Files: `gateway.yaml`, `rayservice.yaml`, `kustomization.yaml`
- Resources: `llm-gateway`, `ray-serve-llm`, `llm-gateway-auth`

**Scripts**: Lowercase, hyphenated, executable
- Files: `test-llm.sh` (chmod +x)

**Config Files**: Lowercase with dots
- `.env.example`, `.envrc`

### YAML Formatting (Kubernetes Manifests)

**Indentation**: 2 spaces (no tabs)
```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: llm-gateway
  namespace: default
spec:
  gatewayClassName: envoy
  listeners:
  - name: http
    protocol: HTTP
    port: 80
```

**List Items**: Hyphen inline with parent indent level

**Document Separators**: Use `---` between resources in multi-resource files

**String Quoting**:
- Version numbers: Always quoted (`"2.52.0"`, `"1.34"`)
- Simple values: Unquoted when possible (`port: 80`, `namespace: default`)

**Inline Comments**: Use sparingly, 2 spaces after value
```yaml
tensor_parallel_size: 2  # Use both GPUs
```

### Terraform (HCL) Style

**Section Headers**: Use comment blocks
```hcl
# ============================================================================
# GPU NODE POOL CONFIGURATION
# ============================================================================
```

**Resource Naming**: Snake_case
```hcl
resource "linode_lke_cluster" "gpu_cluster" {
variable "gpu_node_count" {
output "cluster_id" {
```

**Variable Structure**: Always include description, type, and default (when applicable)
```hcl
variable "gpu_node_count" {
  description = "Number of GPU nodes in the cluster"
  type        = number
  default     = 1
}
```

**Sensitive Data**: Mark appropriately
```hcl
variable "linode_api_token" {
  description = "Linode API token"
  type        = string
  sensitive   = true
}
```

### Tiltfile (Starlark) Style

**Section Headers**: Use ASCII art (preserve existing style)
```python
# ░█▀█░█░█░▀█▀░█▀▄░▀█▀░█▀█░░░█▀▀░█▀█░█░█░░░█▀█░█▀█░█▀▀░█▀▄░█▀█░▀█▀░█▀█░█▀▄
# ░█░█░▀▄▀░░█░░█░█░░█░░█▀█░░░█░█░█▀▀░█░█░░░█░█░█▀▀░█▀▀░█▀▄░█▀█░░█░░█░█░█▀▄
# ░▀░▀░░▀░░▀▀▀░▀▀░░▀▀▀░▀░▀░░░▀▀▀░▀░░░▀▀▀░░░▀▀▀░▀░░░▀▀▀░▀░▀░▀░▀░░▀░░▀▀▀░▀░▀
```

**Variable Naming**: Snake_case
```python
nvidia_gpu_operator_version = os.getenv("NVIDIA_GPU_OPERATOR_VERSION", "v25.10.0")
huggingface_token = os.getenv("HUGGINGFACE_TOKEN", "")
```

**Validation**: Use `fail()` for required env vars
```python
if not huggingface_token:
    fail("HUGGINGFACE_TOKEN environment variable is required.")
```

**Resource Organization**: Use labels for grouping
```python
labels=["nvidia"]    # GPU operator resources
labels=["kuberay"]   # Ray-related resources
labels=["gateway"]   # Gateway resources
labels=["kueue"]     # Queue management
```

**Dependencies**: Explicit resource_deps
```python
resource_deps=["kuberay-operator-repo", "gpu-operator"]
```

**Dynamic YAML Manipulation**: Load, modify, encode pattern
```python
gateway_yaml = read_yaml("manifests/gateway.yaml", allow_duplicates=True)
for doc in gateway_yaml:
    if doc.get("kind") == "SecurityPolicy":
        doc["spec"]["authorization"]["rules"] = [...]
k8s_yaml(encode_yaml_stream(gateway_yaml))
```

### Bash Script Style

**Variables**: UPPERCASE for exported/environment variables
```bash
export SERVICE_IP=$(kubectl get gateway llm-gateway -ojsonpath="{.status.addresses[0].value}")
```

**Line Continuation**: Backslash with 2-space indent
```bash
curl --location "http://${SERVICE_IP}/v1/chat/completions" \
  --header "Authorization: Bearer ${OPENAI_API_KEY}" \
  --header "Content-Type: application/json" \
  --data '{...}'
```

---

## Architecture Patterns

### Resource Naming Convention
Pattern: `{function}-{component}-{optional-suffix}`

Examples:
- `llm-gateway` (Gateway resource)
- `llm-route` (HTTPRoute)
- `llm-gateway-auth` (SecurityPolicy)
- `ray-serve-llm` (RayService)
- `hf-secret` (HuggingFace token secret)

### Namespace Strategy
- **Operators**: Dedicated namespaces (`gpu-operator`, `envoy-gateway-system`, `kueue-system`)
- **Applications**: `default` namespace (RayService, Gateway)

### Secret Management
1. **Never commit secrets** - Use `.env` (gitignored)
2. **Provide examples** - Create `.env.example` templates
3. **Inject at runtime** - Tiltfile loads from env vars and creates Kubernetes secrets
4. **Security-first manifests** - Raw manifests should deny by default (see `gateway.yaml`)

### Version Pinning
All component versions must be:
- Explicitly defined with defaults
- Overridable via environment variables
- Documented in variable descriptions

---

## Development Workflow

### Initial Setup
1. Provision LKE cluster: `make apply`
2. Download kubeconfig (automatic with `make apply`)
3. Create `.env` from `.env.example` with secrets
4. Deploy all components: `make up`

**Alternative - Complete workflow in one command:**
```bash
make all  # Runs: init → apply → up
```

### Making Changes
1. **Manifests**: Edit YAML files, Tilt auto-reloads
2. **Tiltfile**: Edit and save, Tilt auto-reloads
3. **Terraform**: Run `make plan` → `make apply`

### Testing Changes
1. Check Tilt UI for resource status: `http://localhost:10350`
2. Use port-forwards (`:8265` for Ray dashboard, `:8000` for Serve)
3. Run `make test` for API validation
4. Check status: `make status`

### Cleanup
1. Tear down Kubernetes resources: `make down`
2. Destroy infrastructure: `make destroy`
3. Clean local files: `make clean`

---

## Important Constraints for Agents

1. **No Automated Tests**: This project has no unit/integration tests. Manual verification only.
2. **No CI/CD**: No automated pipelines. All deployments are manual via Tilt.
3. **No Linting Tools**: Follow style guidelines manually. No pre-commit hooks.
4. **Security Critical**: Authorization rules are injected by Tiltfile. Direct manifest applies result in deny-only.
5. **GPU Resources**: This deployment requires expensive GPU nodes. Be mindful of resource changes.
6. **Tilt is Primary**: Always prefer Tilt workflow over raw `kubectl apply`.
7. **Version Sensitivity**: Ray, KubeRay, and GPU operator versions must be compatible. Test before updating.
8. **HuggingFace Token**: Required for downloading models. Ensure `.env` is configured before deployment.

---

## Common Tasks for Agents

### Adding a New Kubernetes Resource
1. Create manifest in `manifests/` directory
2. Add to Tiltfile with appropriate labels and dependencies
3. Update `k8s_resource()` objects list if needed

### Updating Component Versions
1. Update default in Tiltfile or override via environment variable
2. Test compatibility before committing
3. Update any related documentation

### Modifying Security Policies
1. **Never** hardcode secrets in `manifests/gateway.yaml`
2. Inject dynamic values via Tiltfile using `read_yaml()`/`encode_yaml_stream()`
3. Ensure raw manifest defaults to secure (deny) behavior

### Adding Environment Variables
1. Add to `.env.example` with placeholder value
2. Load in Tiltfile with `os.getenv("VAR_NAME", "default")`
3. Add validation if required: `if not var: fail("...")`

---

**Last Updated**: 2026-02-17  
**Maintained By**: Repository contributors  
**Questions**: Check Tiltfile header comments or manifest inline documentation
