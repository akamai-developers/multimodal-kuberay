# ░▀█▀░▀█▀░█░░░▀█▀░█▀▀░▀█▀░█░░░█▀▀
# ░░█░░░█░░█░░░░█░░█▀▀░░█░░█░░░█▀▀
# ░░▀░░▀▀▀░▀▀▀░░▀░░▀░░░▀▀▀░▀▀▀░▀▀▀
#
# KubeRay GPU LLM Quickstart - Tiltfile
#
# This Tiltfile manages the installation of all Kubernetes components
# for the GPU LLM deployment on LKE. The LKE cluster itself is created
# by Terraform (see terraform/ directory).
#
# Prerequisites:
# 1. LKE cluster created via Terraform
# 2. kubectl configured with cluster context
# 3. .env file created from .env.example with required secrets
#
# Run with: tilt up

# Load Tilt extensions
load("ext://helm_resource", "helm_resource", "helm_repo")
load("ext://secret", "secret_from_dict")

# Set a longer upsert timeout to avoid apply timeouts during heavy operations
update_settings(k8s_upsert_timeout_secs=900)

# Detect and allow the LKE context (must come before any local() calls)
if k8s_context().startswith("lke"):
    allow_k8s_contexts(k8s_context())
else:
    print("WARNING: Not running on LKE context. Current context: %s" % k8s_context())
    print("Make sure you're connected to the correct cluster!")

# Capture start time for total deployment timing
_tilt_start_ts = str(local("date +%s")).strip()

# ░█░█░█▀█░█▀▄░▀█▀░█▀█░█▀▄░█░░░█▀▀░█▀▀
# ░▀▄▀░█▀█░█▀▄░░█░░█▀█░█▀▄░█░░░█▀▀░▀▀█
# ░░▀░░▀░▀░▀░▀░▀▀▀░▀░▀░▀▀░░▀▀▀░▀▀▀░▀▀▀
# Load environment variables from .env file
huggingface_token = os.getenv("HUGGINGFACE_TOKEN", "")
openai_api_key = os.getenv("OPENAI_API_KEY", "")
webui_admin_email = os.getenv("WEBUI_ADMIN_EMAIL", "admin@demo.local")
webui_admin_password = os.getenv("WEBUI_ADMIN_PASSWORD", "demo1234")
obj_endpoint_hostname = os.getenv("OBJ_ENDPOINT_HOSTNAME", "")
obj_access_key = os.getenv("OBJ_ACCESS_KEY", "")
obj_secret_key = os.getenv("OBJ_SECRET_KEY", "")
obj_region = os.getenv("OBJ_REGION", "")
model_bucket = os.getenv("MODEL_BUCKET", "model-cache")

# Optional: Allow version overrides from env
nvidia_gpu_operator_version = os.getenv("NVIDIA_GPU_OPERATOR_VERSION", "v25.10.0")
kuberay_operator_version = os.getenv("KUBERAY_OPERATOR_VERSION", "1.5.1")
envoy_gateway_version = os.getenv("ENVOY_GATEWAY_VERSION", "v1.7.0")

# Validate required environment variables (skip during teardown)
_required_vars = {
    "HUGGINGFACE_TOKEN": huggingface_token,
    "OPENAI_API_KEY": openai_api_key,
    "OBJ_ENDPOINT_HOSTNAME": obj_endpoint_hostname,
    "OBJ_ACCESS_KEY": obj_access_key,
    "OBJ_SECRET_KEY": obj_secret_key,
    "OBJ_REGION": obj_region,
}
_missing = [k for k, v in _required_vars.items() if not v]
if _missing:
    if config.tilt_subcommand == "down":
        print("WARNING: Missing env vars (ignored during teardown): %s" % ", ".join(_missing))
    else:
        fail("Missing required environment variables: %s" % ", ".join(_missing))

# ░█▀█░█░█░▀█▀░█▀▄░▀█▀░█▀█░░░█▀▀░█▀█░█░█░░░█▀█░█▀█░█▀▀░█▀▄░█▀█░▀█▀░█▀█░█▀▄
# ░█░█░▀▄▀░░█░░█░█░░█░░█▀█░░░█░█░█▀▀░█░█░░░█░█░█▀▀░█▀▀░█▀▄░█▀█░░█░░█░█░█▀▄
# ░▀░▀░░▀░░▀▀▀░▀▀░░▀▀▀░▀░▀░░░▀▀▀░▀░░░▀▀▀░░░▀▀▀░▀░░░▀▀▀░▀░▀░▀░▀░░▀░░▀▀▀░▀░▀

helm_repo(
    "gpu-operator-repo",
    "https://helm.ngc.nvidia.com/nvidia",
    labels=["nvidia"],
)

helm_resource(
    "gpu-operator",
    "gpu-operator-repo/gpu-operator",
    namespace="gpu-operator",
    resource_deps=["gpu-operator-repo"],
    flags=[
        "--create-namespace",
        "--version=%s" % nvidia_gpu_operator_version,
        "--set=dcgmExporter.serviceMonitor.enabled=true",
        "--set=dcgmExporter.serviceMonitor.additionalLabels.release=kube-prometheus-stack",
        "--wait",
        "--timeout=900s",
    ],
    labels=["nvidia"],
)

# ░█▄█░▀█▀░█▀▀░░░█▀▀░█▀█░█▀█░█▀▀░▀█▀░█▀▀
# ░█░█░░█░░█░█░░░█░░░█░█░█░█░█▀▀░░█░░█░█
# ░▀░▀░▀▀▀░▀▀▀░░░▀▀▀░▀▀▀░▀░▀░▀░░░▀▀▀░▀▀▀
#
# Enable MIG (Multi-Instance GPU) on the 2-GPU Nemotron nodes.
# Each physical GPU is partitioned into 4x 1g.24gb instances (24 GB each)
# giving 8 MIG devices per node (16 total across both 2-GPU nodes).
# The 4-GPU MiniMax node is left untouched (whole GPUs, 2x TP=2 replicas).

local_resource(
    "mig-config",
    cmd="""set -euo pipefail
DESIRED="all-1g.24gb"

# Wait for GPU feature discovery to label the 2-GPU nodes
# (needed on fresh clusters — GFD takes a moment after GPU Operator install)
echo "Waiting for GPU feature discovery to label 2-GPU nodes..."
for i in $(seq 1 60); do
  new=$(kubectl get nodes -l nvidia.com/gpu.count=2 -o name 2>/dev/null | wc -l | tr -d ' ')
  existing=$(kubectl get nodes -l nvidia.com/mig.config=$DESIRED -o name 2>/dev/null | wc -l | tr -d ' ')
  total=$((new + existing))
  if [ "$total" -ge 2 ]; then
    echo "Found $total target nodes"
    break
  fi
  echo "  $total/2 target nodes discovered..."
  sleep 5
done

# Discover the 2-GPU nodes (pre-MIG) plus any already MIG-configured
NEW=$(kubectl get nodes -l nvidia.com/gpu.count=2 -o name 2>/dev/null || true)
EXISTING=$(kubectl get nodes -l nvidia.com/mig.config=$DESIRED -o name 2>/dev/null || true)
NODES=$(printf '%s\n%s' "$NEW" "$EXISTING" | sort -u | grep -v '^$' || true)
if [ -z "$NODES" ]; then
  echo "ERROR: No 2-GPU nodes found for MIG configuration"
  exit 1
fi
TOTAL=$(echo "$NODES" | wc -l | tr -d ' ')
for node in $NODES; do
  echo "Labeling $node -> nvidia.com/mig.config=$DESIRED"
  kubectl label "$node" nvidia.com/mig.config="$DESIRED" --overwrite
done
echo "Waiting for MIG manager to finish configuration..."
for i in $(seq 1 60); do
  ready=$(kubectl get nodes -l nvidia.com/mig.config=$DESIRED,nvidia.com/mig.config.state=success -o name 2>/dev/null | wc -l | tr -d ' ')
  if [ "$ready" = "$TOTAL" ]; then
    echo "MIG configuration complete ($ready/$TOTAL nodes)"
    exit 0
  fi
  echo "  $ready/$TOTAL nodes ready..."
  sleep 5
done
echo "ERROR: Timeout waiting for MIG configuration after 300s"
exit 1""",
    resource_deps=["gpu-operator"],
    labels=["nvidia"],
)

# ░█░█░█░█░█▀▄░█▀▀░█▀▄░█▀█░█░█░░░█▀█░█▀█░█▀▀░█▀▄░█▀█░▀█▀░█▀█░█▀▄
# ░█▀▄░█░█░█▀▄░█▀▀░█▀▄░█▀█░░█░░░░█░█░█▀▀░█▀▀░█▀▄░█▀█░░█░░█░█░█▀▄
# ░▀░▀░▀▀▀░▀▀░░▀▀▀░▀░▀░▀░▀░░▀░░░░▀▀▀░▀░░░▀▀▀░▀░▀░▀░▀░░▀░░▀▀▀░▀░▀

helm_repo(
    "kuberay-operator-repo",
    "https://ray-project.github.io/kuberay-helm/",
    labels=["kuberay"],
)

helm_resource(
    "kuberay-operator",
    "kuberay-operator-repo/kuberay-operator",
    namespace="default",
    resource_deps=["kuberay-operator-repo", "kube-prometheus-stack"],
    flags=[
        "--version=%s" % kuberay_operator_version,
        "--set=metrics.serviceMonitor.enabled=true",
        "--set=metrics.serviceMonitor.selector.release=kube-prometheus-stack",
        "--wait",
        "--timeout=600s",
    ],
    labels=["kuberay"],
)

# ░█▀▀░█▀█░█░█░█▀█░█░█░░░█▀▀░█▀█░▀█▀░█▀▀░█░█░█▀█░█░█
# ░█▀▀░█░█░▀▄▀░█░█░░█░░░░█░█░█▀█░░█░░█▀▀░█▄█░█▀█░░█░
# ░▀▀▀░▀░▀░░▀░░▀▀▀░░▀░░░░▀▀▀░▀░▀░░▀░░▀▀▀░▀░▀░▀░▀░░▀░

helm_resource(
    "envoy-gateway",
    "oci://docker.io/envoyproxy/gateway-helm",
    namespace="envoy-gateway-system",
    flags=[
        "--create-namespace",
        "--version=%s" % envoy_gateway_version,
        "--wait",
        "--timeout=300s",
    ],
    labels=["gateway"],
)

# ░█▀█░█▀▄░█▀█░█▄█░█▀▀░▀█▀░█░█░█▀▀░█░█░█▀▀
# ░█▀▀░█▀▄░█░█░█░█░█▀▀░░█░░█▀█░█▀▀░█░█░▀▀█
# ░▀░░░▀░▀░▀▀▀░▀░▀░▀▀▀░░▀░░▀░▀░▀▀▀░▀▀▀░▀▀▀

helm_repo(
    "prometheus-community",
    "https://prometheus-community.github.io/helm-charts",
    labels=["monitoring"],
)
helm_resource(
    "kube-prometheus-stack",
    "prometheus-community/kube-prometheus-stack",
    namespace="kube-system",
    resource_deps=["prometheus-community"],
    flags=[
        "--values=./hack/monitoring-values.yaml",
        "--timeout=600s",
        "--set=grafana.adminUser=%s" % webui_admin_email,
        "--set=grafana.adminPassword=%s" % webui_admin_password,
    ],
    labels=["monitoring"],
)
# Grafana is exposed via the llm-gateway at /grafana/ (native auth).
# The gateway IP link is registered in the llm-gateway k8s_resource below.

# Prometheus Pushgateway — receives model download metrics from short-lived
# init containers that finish before Prometheus can scrape them.
helm_resource(
    "prometheus-pushgateway",
    "prometheus-community/prometheus-pushgateway",
    namespace="kube-system",
    resource_deps=["prometheus-community", "kube-prometheus-stack"],
    flags=[
        "--set=serviceMonitor.enabled=true",
        "--set=serviceMonitor.namespace=kube-system",
        "--set=serviceMonitor.additionalLabels.release=kube-prometheus-stack",
        "--set=persistentVolume.enabled=false",
    ],
    labels=["monitoring"],
)



# ░█▀▀░█▀▀░█▀▀░█▀▄░█▀▀░▀█▀░█▀▀
# ░▀▀█░█▀▀░█░░░█▀▄░█▀▀░░█░░▀▀█
# ░▀▀▀░▀▀▀░▀▀▀░▀░▀░▀▀▀░░▀░░▀▀▀

# HuggingFace Secret
k8s_yaml(secret_from_dict(
    name="hf-secret",
    namespace="default",
    inputs={
        "hf_token": huggingface_token
    }
))

k8s_resource(
    new_name="hf-secret",
    objects=["hf-secret:Secret:default"],
    labels=["kuberay"],
)

# BasicAuth Secret for Gateway
k8s_yaml(secret_from_dict(
    name="llm-gateway-auth",
    namespace="default",
    inputs={
        ".htpasswd": "api-key:" + openai_api_key
    }
))

k8s_resource(
    new_name="llm-gateway-auth",
    objects=["llm-gateway-auth:secret"],
    labels=["gateway"],
)

# Object Storage Secret for model caching
# Key names match standard AWS env vars so manifests can use envFrom directly.
k8s_yaml(secret_from_dict(
    name="obj-store-secret",
    namespace="default",
    inputs={
        "OBJ_ACCESS_KEY": obj_access_key,
        "OBJ_SECRET_KEY": obj_secret_key,
        "OBJ_ENDPOINT_HOSTNAME": obj_endpoint_hostname,
        "OBJ_REGION": obj_region,
        "MODEL_BUCKET": model_bucket,
    }
))

k8s_resource(
    new_name="obj-store-secret",
    objects=["obj-store-secret:Secret:default"],
    labels=["kuberay"],
)

# ░█░█░█▀█░█▀▀░░░█▄█░█▀█░█▀█░▀█▀░█▀▀░█▀▀░█▀▀░▀█▀░█▀▀
# ░█▀▄░█▀█░▀▀█░░░█░█░█▀█░█░█░░█░░█▀▀░█▀▀░▀▀█░░█░░▀▀█
# ░▀░▀░▀▀▀░▀▀▀░░░▀░▀░▀░▀░▀░▀░▀▀▀░▀░░░▀▀▀░▀▀▀░░▀░░▀▀▀

# Gateway - Load and inject authorization with API key
gateway_yaml = read_yaml_stream("manifests/gateway.yaml")

# Inject the authorization rule with the OpenAI API key
for resource in gateway_yaml:
    if resource["kind"] == "SecurityPolicy" and resource["metadata"]["name"] == "llm-gateway-auth":
        resource["spec"]["authorization"]["rules"] = [{
            "name": "allow-with-api-key",
            "action": "Allow",
            "principal": {
                "headers": [{
                    "name": "Authorization",
                    "values": ["Bearer " + openai_api_key]
                }]
            }
        }]

k8s_yaml(encode_yaml_stream(gateway_yaml))

k8s_resource(
    new_name="llm-gateway",
    objects=[
    "llm-gateway:gateway",
    "llm-route:httproute",
    "llm-gateway-auth:securitypolicy",
    "llm-gateway-client-policy:clienttrafficpolicy",
    "envoy:gatewayclass",
    "grafana-route:httproute",
    "grafana-route-auth:securitypolicy",
    "allow-grafana-from-default:referencegrant",
    ],
    resource_deps=["envoy-gateway", "llm-gateway-auth", "kube-prometheus-stack"],
    labels=["gateway"],
)

# ░█▀▄░█▀▀░█▀▀░█▀▀░█▀█░█▀▄░█▀▀░█░█░░░█▀█░▀█▀░█▀█░█▀▀░█░░░▀█▀░█▀█░█▀▀
# ░█▀▄░█▀▀░▀▀█░█▀▀░█▀█░█▀▄░█░░░█▀█░░░█▀▀░░█░░█▀▀░█▀▀░█░░░░█░░█░█░█▀▀
# ░▀░▀░▀▀▀░▀▀▀░▀▀▀░▀░▀░▀░▀░▀▀▀░▀░▀░░░▀░░░▀▀▀░▀░░░▀▀▀░▀▀▀░▀▀▀░▀░▀░▀▀▀

# Research Pipeline ConfigMap — auto-updates when serve/mcp_research_pipeline.py changes
mcp_pipeline_code = str(read_file("serve/mcp_research_pipeline.py"))
k8s_yaml(encode_yaml({
    "apiVersion": "v1",
    "kind": "ConfigMap",
    "metadata": {
        "name": "research-pipeline-code",
        "namespace": "default",
    },
    "data": {
        "mcp_research_pipeline.py": mcp_pipeline_code,
    },
}))

k8s_resource(
    new_name="research-pipeline-code",
    objects=["research-pipeline-code:configmap"],
    labels=["openwebui"],
)

# Model Sync Script ConfigMap — shared scripts for init containers
# Includes the s5cmd-based object storage downloader and the warmup
# script (sends dummy requests to pre-heat CUDA caches).
model_sync_script = str(read_file("scripts/model-sync.sh"))
warmup_nemotron_script = str(read_file("scripts/warmup-nemotron.sh"))
k8s_yaml(encode_yaml({
    "apiVersion": "v1",
    "kind": "ConfigMap",
    "metadata": {
        "name": "model-sync-scripts",
        "namespace": "default",
    },
    "data": {
        "model-sync.sh": model_sync_script,
        "warmup-nemotron.sh": warmup_nemotron_script,
    },
}))

k8s_resource(
    new_name="model-sync-scripts",
    objects=["model-sync-scripts:configmap"],
    labels=["kuberay"],
)

# ░█░█░█▀█░█▀▀░░░█▄█░█▀█░█▀▄░█▀▀░█░░░░░█▀▀░█▀█░█▀▀░█░█░█▀▀
# ░█▀▄░█▀█░▀▀█░░░█░█░█░█░█░█░█▀▀░█░░░░░█░░░█▀█░█░░░█▀█░█▀▀
# ░▀░▀░▀▀▀░▀▀▀░░░▀░▀░▀▀▀░▀▀░░▀▀▀░▀▀▀░░░▀▀▀░▀░▀░▀▀▀░▀░▀░▀▀▀

# Model Upload Script ConfigMap — HuggingFace → Object Storage caching script
model_upload_script = str(read_file("scripts/model-upload.sh"))
k8s_yaml(encode_yaml({
    "apiVersion": "v1",
    "kind": "ConfigMap",
    "metadata": {
        "name": "model-upload-scripts",
        "namespace": "default",
    },
    "data": {
        "model-upload.sh": model_upload_script,
    },
}))

k8s_resource(
    new_name="model-upload-scripts",
    objects=["model-upload-scripts:configmap"],
    labels=["kuberay"],
)

# Model Upload Job — caches MiniMax-M2.5-NVFP4 and Nemotron-Parse-v1.2 in Object Storage
k8s_yaml("manifests/model-upload-job.yaml")
k8s_resource(
    "model-upload",
    resource_deps=["hf-secret", "obj-store-secret", "model-upload-scripts"],
    labels=["kuberay"],
)

# ░█▄█░▀█▀░█▀█░▀█▀░█▄█░█▀█░█░█░░░█▄█░▀▀▄░░░█▀▀░
# ░█░█░░█░░█░█░░█░░█░█░█▀█░▀▄▀░░░█░█░▄▀░░░░▀▀█░
# ░▀░▀░▀▀▀░▀░▀░▀▀▀░▀░▀░▀░▀░░▀░░░░▀░▀░▀▀▀░░░▀▀▀░

# MiniMax M2.5 NVFP4 — quantized MoE, 2× TP=2 replicas on the 4× Blackwell node
k8s_yaml("manifests/rayservice-minimax.yaml")
k8s_resource(
    new_name="minimax-service",
    objects=[
        "ray-serve-minimax:rayservice",
        "minimax-llm-svc:service",
    ],
    resource_deps=["kuberay-operator", "hf-secret", "obj-store-secret", "model-upload", "model-sync-scripts", "prometheus-pushgateway"],
    labels=["kuberay"],
)

local_resource(
    "minimax-dashboard",
    serve_cmd="until kubectl get endpoints minimax-llm-svc -o jsonpath='{.subsets[0].addresses}' 2>/dev/null | grep -q ip; do echo 'Waiting for minimax-llm-svc endpoints...'; sleep 10; done && kubectl port-forward svc/minimax-llm-svc 8265:8265 8000:8000",
    resource_deps=["minimax-service"],
    labels=["kuberay"],
    links=[link("http://localhost:8265", "MiniMax Ray Dashboard")],
)

# ░█▀█░█▀▀░█▄█░█▀█░▀█▀░█▀▄░█▀█░█▀█░░░█▀█░█▀█░█▀▄░█▀▀░█▀▀
# ░█░█░█▀▀░█░█░█░█░░█░░█▀▄░█░█░█░█░░░█▀▀░█▀█░█▀▄░▀▀█░█▀▀
# ░▀░▀░▀▀▀░▀░▀░▀▀▀░▀▀▀░▀░▀░▀▀▀░▀░▀░░░▀░░░▀░▀░▀░▀░▀▀▀░▀▀▀

# Nemotron Parse v1.2 — KubeRay RayService on MIG-partitioned GPUs
# 16 workers (1 per MIG device) across the 2x 2-GPU nodes.
# Each pod gets 1 MIG 1g.24gb instance via CDI as CUDA device 0.
# No runtime patching needed — clean GPU enumeration.

# Per-node model cache DaemonSet — downloads weights from Object Storage
# once per MIG node to a hostPath.  Workers mount it read-only, avoiding
# 16 redundant downloads (2 downloads total instead of 16).
k8s_yaml("manifests/nemotron-model-cache.yaml")
k8s_resource(
    "nemotron-model-cache",
    resource_deps=["obj-store-secret", "model-upload", "model-sync-scripts", "mig-config", "prometheus-pushgateway"],
    labels=["kuberay"],
)

k8s_yaml("manifests/rayservice-nemotron-parse.yaml")
k8s_resource(
    new_name="nemotron-parse-service",
    objects=[
        "ray-serve-nemotron-parse:rayservice",
        "nemotron-parse-svc:service",
    ],
    resource_deps=["kuberay-operator", "hf-secret", "obj-store-secret", "model-upload", "model-sync-scripts", "gpu-operator", "mig-config", "nemotron-model-cache"],
    labels=["kuberay"],
)

local_resource(
    "nemotron-parse-dashboard",
    serve_cmd="until kubectl get endpoints nemotron-parse-svc -o jsonpath='{.subsets[0].addresses}' 2>/dev/null | grep -q ip; do echo 'Waiting for nemotron-parse-svc endpoints...'; sleep 5; done && kubectl port-forward svc/nemotron-parse-svc 18265:8265 18000:8000",
    resource_deps=["nemotron-parse-service"],
    labels=["kuberay"],
    links=[link("http://localhost:18265", "Nemotron Parse Ray Dashboard")],
)

# Nemotron Parse Warmup — sends 256 concurrent dummy requests to pre-heat
# CUDA kernels, flash-attention JIT, and image processor on all 16 replicas.
# Runs in parallel with MiniMax weight loading so replicas are hot when the
# research pipeline first calls OCR.
k8s_yaml("manifests/nemotron-warmup-job.yaml")
k8s_resource(
    "nemotron-warmup",
    resource_deps=["nemotron-parse-service", "model-sync-scripts"],
    labels=["kuberay"],
)

# ░█▀█░█▀█░█▀▀░█▀█░█░█░█▀▀░█▀▄░█░█░▀█▀
# ░█░█░█▀▀░█▀▀░█░█░▀▄▀░█▀▀░█▀▄░█░█░░█░
# ░▀▀▀░▀░░░▀▀▀░▀░▀░░▀░░▀▀▀░▀▀░░▀▀▀░▀▀▀

# OpenWebUI secret — raw API key for intra-cluster auth (no .htpasswd wrapping)
k8s_yaml(secret_from_dict(
    name="openwebui-secret",
    namespace="default",
    inputs={
        "api_key": openai_api_key,
        "admin_email": webui_admin_email,
        "admin_password": webui_admin_password,
    }
))

k8s_resource(
    new_name="openwebui-secret",
    objects=["openwebui-secret:Secret:default"],
    labels=["openwebui"],
)

# OpenWebUI custom CSS ConfigMap — Akamai brand overrides
custom_css_code = str(read_file("assets/custom.css"))
k8s_yaml(encode_yaml({
    "apiVersion": "v1",
    "kind": "ConfigMap",
    "metadata": {
        "name": "openwebui-custom-css",
        "namespace": "default",
    },
    "data": {
        "custom.css": custom_css_code,
    },
}))

# OpenWebUI logos ConfigMap — Akamai brand logos for splash & main icon
# Binary PNG files need base64 encoding; kubectl --dry-run handles this cleanly.
_logos_cmd = (
    "kubectl create configmap openwebui-logos"
    + " --from-file=logo.png='assets/Akamai Cloud - Horizontal.png'"
    + " --from-file=splash.png='assets/Akamai Cloud - Stacked.png'"
    + " --from-file=splash-dark.png='assets/Akamai Cloud - Stacked WHITE.png'"
    + " --namespace=default --dry-run=client -o yaml"
)
k8s_yaml(local(_logos_cmd, quiet=True))

# Seed Streaming Config Script — postStart hook for OpenWebUI
seed_config_script = str(read_file("scripts/seed-streaming-config.sh"))
k8s_yaml(encode_yaml({
    "apiVersion": "v1",
    "kind": "ConfigMap",
    "metadata": {
        "name": "seed-config-scripts",
        "namespace": "default",
    },
    "data": {
        "seed-streaming-config.sh": seed_config_script,
    },
}))

k8s_yaml("manifests/openwebui.yaml")
k8s_resource(
    "openwebui",
    objects=[
        "openwebui-data:persistentvolumeclaim:default",
        "openwebui-custom-css:configmap",
        "openwebui-logos:configmap",
        "seed-config-scripts:configmap",
        "openwebui-route:httproute",
        "openwebui-route-auth:securitypolicy",
    ],
    resource_deps=["openwebui-secret", "minimax-service", "llm-gateway"],
    labels=["openwebui"],
)

k8s_resource(
    "openwebui-pipelines",
    resource_deps=["research-pipeline-code", "openwebui-secret"],
    labels=["openwebui"],
)

# ░█▄█░█▀▀░█▀█░░░█▀▀░█▀▀░█▀▄░█░█░█▀▀░█▀▄░█▀▀
# ░█░█░█░░░█▀▀░░░▀▀█░█▀▀░█▀▄░▀▄▀░█▀▀░█▀▄░▀▀█
# ░▀░▀░▀▀▀░▀░░░░░▀▀▀░▀▀▀░▀░▀░░▀░░▀▀▀░▀░▀░▀▀▀

# MCP shared code (auth middleware)
mcp_common_code = str(read_file("mcp/common.py"))

# ArXiv Search MCP Server — ConfigMap + Deployment
arxiv_search_code = str(read_file("mcp/arxiv_search_server.py"))
k8s_yaml(encode_yaml({
    "apiVersion": "v1",
    "kind": "ConfigMap",
    "metadata": {
        "name": "mcp-arxiv-search-code",
        "namespace": "default",
    },
    "data": {
        "arxiv_search_server.py": arxiv_search_code,
        "common.py": mcp_common_code,
    },
}))

k8s_resource(
    new_name="mcp-arxiv-search-code",
    objects=["mcp-arxiv-search-code:configmap"],
    labels=["mcp"],
)

k8s_yaml("manifests/mcp-arxiv-search.yaml")
k8s_resource(
    "mcp-arxiv-search",
    resource_deps=["mcp-arxiv-search-code", "openwebui-secret"],
    labels=["mcp"],
)

# Paper-to-Text MCP Server — ConfigMap + Deployment
paper_to_text_code = str(read_file("mcp/paper_to_text_server.py"))
k8s_yaml(encode_yaml({
    "apiVersion": "v1",
    "kind": "ConfigMap",
    "metadata": {
        "name": "mcp-paper-to-text-code",
        "namespace": "default",
    },
    "data": {
        "paper_to_text_server.py": paper_to_text_code,
        "common.py": mcp_common_code,
    },
}))

k8s_resource(
    new_name="mcp-paper-to-text-code",
    objects=["mcp-paper-to-text-code:configmap"],
    labels=["mcp"],
)

k8s_yaml("manifests/mcp-paper-to-text.yaml")
k8s_resource(
    "mcp-paper-to-text",
    resource_deps=["mcp-paper-to-text-code", "openwebui-secret", "nemotron-parse-service"],
    labels=["mcp"],
)

# ░█▀▄░█▀█░█░█░░░█▄█░█▀▀░▀█▀░█▀▄░▀█▀░█▀▀░█▀▀
# ░█▀▄░█▀█░░█░░░░█░█░█▀▀░░█░░█▀▄░░█░░█░░░▀▀█
# ░▀░▀░▀░▀░░▀░░░░▀░▀░▀▀▀░░▀░░▀░▀░▀▀▀░▀▀▀░▀▀▀

# Ray Metrics PodMonitor — scrapes all Ray pods for Prometheus
k8s_yaml("manifests/ray-podmonitor.yaml")
k8s_resource(
    new_name="ray-metrics",
    objects=["ray-workers-monitor:podmonitor"],
    resource_deps=["kube-prometheus-stack"],
    labels=["monitoring"],
)

# Grafana Dashboards — auto-provisioned via Grafana sidecar (Ray + DCGM)
grafana_dashboard_cms = []
for dashboard_path in listdir("hack/grafana-dashboards"):
    if not dashboard_path.endswith(".json"):
        continue
    # listdir returns full paths; extract just the filename
    dashboard_file = dashboard_path.split("/")[-1]
    cm_name = "grafana-" + dashboard_file.replace("_grafana_dashboard.json", "").replace("_", "-")
    dashboard_json = str(read_file(dashboard_path))
    k8s_yaml(encode_yaml({
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": cm_name,
            "namespace": "kube-system",
            "labels": {
                "grafana_dashboard": "1",
            },
        },
        "data": {
            dashboard_file: dashboard_json,
        },
    }))
    grafana_dashboard_cms.append(cm_name + ":configmap")

k8s_resource(
    new_name="grafana-dashboards",
    objects=grafana_dashboard_cms,
    resource_deps=["kube-prometheus-stack"],
    labels=["monitoring"],
)

# ░▀█▀░▀█▀░█▄█░▀█▀░█▀█░█▀▀
# ░░█░░░█░░█░█░░█░░█░█░█░█
# ░░▀░░▀▀▀░▀░▀░▀▀▀░▀░▀░▀▀▀

# Print total deployment time once every resource is ready.
_timer_cmd = """
START=%s; NOW=$(date +%%s); ELAPSED=$((NOW - START)); MIN=$((ELAPSED / 60)); SEC=$((ELAPSED %% 60))
GW_IP=$(kubectl get gateway llm-gateway -o jsonpath='{.status.addresses[0].value}' 2>/dev/null || echo '<pending>')
echo ''
echo '══════════════════════════════════════════════════════════════'
echo "  ✅ All resources ready in ${MIN}m ${SEC}s"
echo '══════════════════════════════════════════════════════════════'
echo ''
echo "  🌐 OpenWebUI:          http://${GW_IP}/"
echo "  🔗 API (chat):         http://${GW_IP}/v1/chat/completions"
echo "  📊 Tilt Dashboard:     http://localhost:10350"
echo "  🔬 MiniMax Ray:        http://localhost:8265"
echo "  🧩 Nemotron Ray:       http://localhost:18265"
echo "  📈 Grafana:            http://${GW_IP}/grafana/"
echo ''
echo '══════════════════════════════════════════════════════════════'
echo ''
""".strip() % _tilt_start_ts
local_resource(
    "deployment-timer",
    cmd=_timer_cmd,
    resource_deps=[
        "openwebui",
        "openwebui-pipelines",
        "minimax-service",
        "nemotron-parse-service",
        "nemotron-warmup",
        "llm-gateway",
        "grafana-dashboards",
        "mcp-arxiv-search",
        "mcp-paper-to-text",
    ],
    labels=["status"],
)
