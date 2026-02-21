# ============================================================================
# KubeRay GPU LLM Quickstart - Makefile
# ============================================================================
# This Makefile provides convenient targets for managing the infrastructure
# and deployment lifecycle.

.PHONY: help init plan apply destroy kubeconfig up ci down status test test-vision test-tts test-pipeline clean all

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
	@echo "  make test        - Run text-only API test (both models)"
	@echo "  make test-vision - Run vision-language API test (both models)"
	@echo "  make test-tts    - Run TTS API test"
	@echo "  make test-pipeline - Run VLM→TTS pipeline test"
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

up: kubeconfig
	@if [ ! -f .env ]; then \
		echo "WARNING: .env file not found. Copy .env.example to .env and fill in required values."; \
		echo "Continuing anyway..."; \
	fi
	@if [ -z "$$KUBECONFIG" ]; then \
		echo "Setting KUBECONFIG to ./kubeconfig"; \
		export KUBECONFIG=$$(pwd)/kubeconfig; \
	fi
	KUBECONFIG=$${KUBECONFIG:-$$(pwd)/kubeconfig} tilt up

ci: kubeconfig
	@if [ ! -f .env ]; then \
		echo "WARNING: .env file not found. Copy .env.example to .env and fill in required values."; \
		echo "Continuing anyway..."; \
	fi
	@if [ -z "$$KUBECONFIG" ]; then \
		echo "Setting KUBECONFIG to ./kubeconfig"; \
		export KUBECONFIG=$$(pwd)/kubeconfig; \
	fi
	KUBECONFIG=$${KUBECONFIG:-$$(pwd)/kubeconfig} tilt ci

down:
	@if [ -z "$$KUBECONFIG" ]; then \
		export KUBECONFIG=$$(pwd)/kubeconfig; \
	fi
	KUBECONFIG=$${KUBECONFIG:-$$(pwd)/kubeconfig} tilt down

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
	@KUBECONFIG=$${KUBECONFIG:-$$(pwd)/kubeconfig} kubectl get gateway,httproute,raycluster,rayservice -A 2>/dev/null || echo "No resources found or cluster not accessible"

test:
	@if [ ! -f scripts/test-llm.sh ]; then \
		echo "ERROR: scripts/test-llm.sh not found"; \
		exit 1; \
	fi
	@echo "Running text-only API test (both models)..."
	@KUBECONFIG=$${KUBECONFIG:-$$(pwd)/kubeconfig} ./scripts/test-llm.sh

test-vision:
	@if [ ! -f scripts/test-vision-llm.sh ]; then \
		echo "ERROR: scripts/test-vision-llm.sh not found"; \
		exit 1; \
	fi
	@echo "Running vision-language API test (both models)..."
	@KUBECONFIG=$${KUBECONFIG:-$$(pwd)/kubeconfig} ./scripts/test-vision-llm.sh

test-tts:
	@if [ ! -f scripts/test-tts.sh ]; then \
		echo "ERROR: scripts/test-tts.sh not found"; \
		exit 1; \
	fi
	@echo "Running TTS API test..."
	@KUBECONFIG=$${KUBECONFIG:-$$(pwd)/kubeconfig} ./scripts/test-tts.sh

test-pipeline:
	@if [ ! -f scripts/test-pipeline.sh ]; then \
		echo "ERROR: scripts/test-pipeline.sh not found"; \
		exit 1; \
	fi
	@echo "Running VLM→TTS pipeline test..."
	@KUBECONFIG=$${KUBECONFIG:-$$(pwd)/kubeconfig} ./scripts/test-pipeline.sh

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
	@echo "=== Deployment Complete ==="
	@echo "Tilt UI available at: http://localhost:10350"
	@echo "Ray Dashboard available at: http://localhost:8265"
	@echo "Ray Serve available at: http://localhost:8000"
