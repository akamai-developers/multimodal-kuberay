# ============================================================================
# KubeRay GPU LLM Quickstart - Makefile
# ============================================================================
# This Makefile provides convenient targets for managing the infrastructure
# and deployment lifecycle.

.PHONY: help init plan apply destroy kubeconfig up ci down status test test-research clean all _check-env

# Load .env file if it exists, and export all variables to subprocesses (Tilt)
-include .env
export

# Default KUBECONFIG path if not set
KUBECONFIG ?= $(shell pwd)/kubeconfig

# Default target - show help
help:
	@echo "KubeRay GPU LLM Quickstart - Available Commands"
	@echo ""
	@echo "Infrastructure Management:"
	@echo "  make init        - Initialize Terraform"
	@echo "  make plan        - Run Terraform plan"
	@echo "  make apply       - Apply Terraform and download kubeconfig"
	@echo "  make destroy     - Destroy infrastructure"
	@echo "  make kubeconfig  - Download/update kubeconfig from Terraform"
	@echo ""
	@echo "Deployment:"
	@echo "  make up          - Start Tilt in interactive mode"
	@echo "  make ci          - Run Tilt in CI mode (non-interactive)"
	@echo "  make down        - Tear down Tilt resources"
	@echo ""
	@echo "Utilities:"
	@echo "  make status      - Show cluster and deployment status"
	@echo "  make test        - Run deep research agent API smoke test"
	@echo "  make test-research - Run full research pipeline test"
	@echo "  make nuke-cache  - Delete all cached models and destroy the bucket"
	@echo "  make clean       - Clean local terraform and kubeconfig files"
	@echo ""
	@echo "Workflows:"
	@echo "  make all         - Full workflow: init → apply → up"
	@echo ""
	@echo "Prerequisites:"
	@echo "  - Copy .env.example to .env and fill in required values"
	@echo "  - Ensure LINODE_TOKEN is set in your environment"

# ============================================================================
# Terraform Infrastructure Targets
# ============================================================================

init:
	@echo "Initializing Terraform..."
	terraform init

plan: init
	@echo "Planning Terraform changes..."
	terraform plan

apply: init
	@echo "Applying Terraform configuration..."
	terraform apply
	@echo ""
	@echo "Downloading kubeconfig..."
	@$(MAKE) kubeconfig

destroy:
	@echo "WARNING: This will destroy all infrastructure!"
	@echo "Press Ctrl+C to cancel, or Enter to continue..."
	@read confirm
	terraform destroy

kubeconfig:
	@echo "Extracting kubeconfig from Terraform output..."
	@terraform output -raw kubeconfig_raw > kubeconfig
	@chmod 600 kubeconfig
	@echo "Kubeconfig saved to ./kubeconfig"
	@echo "Export KUBECONFIG=\$$(pwd)/kubeconfig to use it"

# ============================================================================
# Tilt Deployment Targets
# ============================================================================

_check-env:
	@if [ ! -f .env ]; then \
		echo "WARNING: .env file not found. Copy .env.example to .env and fill in required values."; \
		echo "Continuing anyway..."; \
	fi

up: kubeconfig _check-env
	tilt up

ci: kubeconfig _check-env
	tilt ci

down:
	@if [ -z "$$KUBECONFIG" ]; then \
		export KUBECONFIG=$$(pwd)/kubeconfig; \
	fi
	@echo "=== Tearing down Tilt resources ==="
	KUBECONFIG=$${KUBECONFIG:-$$(pwd)/kubeconfig} tilt down || true
	@KC=$${KUBECONFIG:-$$(pwd)/kubeconfig}; \
	echo "=== Reverting MIG configuration ==="; \
	for node in $$(KUBECONFIG=$$KC kubectl get nodes -l nvidia.com/gpu.count=2,nvidia.com/mig.config -o name 2>/dev/null); do \
		echo "Labeling $$node -> nvidia.com/mig.config=all-disabled"; \
		KUBECONFIG=$$KC kubectl label $$node nvidia.com/mig.config=all-disabled --overwrite 2>/dev/null || true; \
	done; \
	echo "Waiting for MIG manager to disable MIG (up to 120s)..."; \
	for i in $$(seq 1 24); do \
		pending=$$(KUBECONFIG=$$KC kubectl get nodes -l nvidia.com/gpu.count=2,nvidia.com/mig.config=all-disabled -o jsonpath='{range .items[*]}{.metadata.labels.nvidia\.com/mig\.config\.state}{"\n"}{end}' 2>/dev/null | { grep -cv success 2>/dev/null || true; }); \
		pending=$${pending:-0}; \
		if [ "$$pending" = "0" ]; then echo "MIG disabled on all nodes"; break; fi; \
		echo "  $$pending node(s) still reconfiguring..."; \
		sleep 5; \
	done
	@echo ""
	@echo "=== Cleaning up residual resources ==="
	@KC=$${KUBECONFIG:-$$(pwd)/kubeconfig}; \
	echo "Removing kube-prometheus-stack-kubelet service..."; \
	KUBECONFIG=$$KC kubectl delete svc kube-prometheus-stack-kubelet -n kube-system --ignore-not-found; \
	echo "Removing NVIDIA node labels and annotations..."; \
	for node in $$(KUBECONFIG=$$KC kubectl get nodes -o name); do \
		KUBECONFIG=$$KC kubectl label $$node --overwrite $$(KUBECONFIG=$$KC kubectl get $$node -o json \
			| python3 -c "import json,sys; labels=json.load(sys.stdin)['metadata'].get('labels',{}); print(' '.join(k+'-' for k in labels if k.startswith('nvidia.com/')))" 2>/dev/null) 2>/dev/null || true; \
		KUBECONFIG=$$KC kubectl annotate $$node $$(KUBECONFIG=$$KC kubectl get $$node -o json \
			| python3 -c "import json,sys; annots=json.load(sys.stdin)['metadata'].get('annotations',{}); print(' '.join(k+'-' for k in annots if k.startswith('nvidia.com/')))" 2>/dev/null) 2>/dev/null || true; \
	done; \
	echo "Deleting Tilt-created namespaces..."; \
	for ns in gpu-operator envoy-gateway-system; do \
		KUBECONFIG=$$KC kubectl delete ns $$ns --ignore-not-found --wait=false; \
	done; \
	echo "Cleaning up Tilt-installed CRDs..."; \
	KUBECONFIG=$$KC kubectl get crd -o name 2>/dev/null \
		| grep -E 'nvidia\.com|monitoring\.coreos\.com|envoyproxy\.io|gateway\.networking\.k8s\.io|ray\.io' \
		| xargs -r KUBECONFIG=$$KC kubectl delete --ignore-not-found 2>/dev/null || true; \
	echo "Removing stale webhook configurations..."; \
	for wh in $$(KUBECONFIG=$$KC kubectl get mutatingwebhookconfigurations -o name 2>/dev/null \
		| grep -E 'envoy|gpu-operator|nvidia'); do \
		KUBECONFIG=$$KC kubectl delete $$wh --ignore-not-found 2>/dev/null || true; \
	done; \
	for wh in $$(KUBECONFIG=$$KC kubectl get validatingwebhookconfigurations -o name 2>/dev/null \
		| grep -E 'envoy|gpu-operator|nvidia'); do \
		KUBECONFIG=$$KC kubectl delete $$wh --ignore-not-found 2>/dev/null || true; \
	done; \
	echo "Waiting for namespace deletion..."; \
	for ns in gpu-operator envoy-gateway-system; do \
		KUBECONFIG=$$KC kubectl wait --for=delete ns/$$ns --timeout=60s 2>/dev/null || true; \
	done; \
	echo ""; \
	echo "=== Cleanup complete — vanilla LKE cluster restored ==="

# ============================================================================
# Utility Targets
# ============================================================================

status:
	@echo "=== Terraform Status ==="
	@terraform output 2>/dev/null || echo "No Terraform state found. Run 'make apply' first."
	@echo ""
	@echo "=== Kubernetes Cluster Info ==="
	@KUBECONFIG=$${KUBECONFIG:-$$(pwd)/kubeconfig} kubectl cluster-info 2>/dev/null || echo "Cannot connect to cluster"
	@echo ""
	@echo "=== Kubernetes Resources ==="
	@KUBECONFIG=$${KUBECONFIG:-$$(pwd)/kubeconfig} kubectl get gateway,httproute,rayservice,deployment,svc -A 2>/dev/null || echo "No resources found or cluster not accessible"

test:
	@if [ ! -f scripts/test-llm.sh ]; then \
		echo "ERROR: scripts/test-llm.sh not found"; \
		exit 1; \
	fi
	@echo "Running deep research agent smoke test..."
	@KUBECONFIG=$${KUBECONFIG:-$$(pwd)/kubeconfig} ./scripts/test-llm.sh

test-research:
	@if [ ! -f scripts/test-pipeline.sh ]; then \
		echo "ERROR: scripts/test-pipeline.sh not found"; \
		exit 1; \
	fi
	@echo "Running research pipeline test..."
	@KUBECONFIG=$${KUBECONFIG:-$$(pwd)/kubeconfig} ./scripts/test-pipeline.sh

nuke-cache:
	@./scripts/nuke-bucket.sh

clean:
	@echo "Cleaning up local files..."
	@echo "This will remove:"
	@echo "  - kubeconfig"
	@echo "  - .terraform/"
	@echo "  - .terraform.lock.hcl"
	@echo ""
	@echo "This will NOT remove:"
	@echo "  - terraform.tfstate (use 'make destroy' first)"
	@echo "  - .env file"
	@echo ""
	@echo "Press Ctrl+C to cancel, or Enter to continue..."
	@read confirm
	@rm -f kubeconfig
	@rm -rf .terraform
	@rm -f .terraform.lock.hcl
	@echo "Cleanup complete!"

# ============================================================================
# Workflow Targets
# ============================================================================

all: init apply up
	@echo ""
	@echo "=== Deep Research Agent Deployment Complete ==="
	@echo "Tilt UI:             http://localhost:10350"
	@echo "MiniMax Dashboard:   http://localhost:8265"
	@echo "MiniMax API:         http://localhost:8000"
	@echo "OpenWebUI:           check 'kubectl get svc openwebui-svc' for external IP"
