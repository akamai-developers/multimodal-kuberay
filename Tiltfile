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

allow_k8s_contexts('lke573757-ctx')
# Capture start time for total deployment timing
_tilt_start_ts = str(local("date +%s")).strip()

# ░█░█░█▀█░█▀▄░▀█▀░█▀█░█▀▄░█░░░█▀▀░█▀▀
# ░▀▄▀░█▀█░█▀▄░░█░░█▀█░█▀▄░█░░░█▀▀░▀▀█
# ░░▀░░▀░▀░▀░▀░▀▀▀░▀░▀░▀▀░░▀▀▀░▀▀▀░▀▀▀
# Load environment variables from .env file
huggingface_token = os.getenv("HUGGINGFACE_TOKEN", "")
openai_api_key = os.getenv("OPENAI_API_KEY", "")
s3_endpoint_hostname = os.getenv("S3_ENDPOINT_HOSTNAME", "")
obj_access_key = os.getenv("OBJ_ACCESS_KEY", "")
obj_secret_key = os.getenv("OBJ_SECRET_KEY", "")
obj_region = os.getenv("OBJ_REGION", "")
model_bucket = os.getenv("MODEL_BUCKET", "model-cache")

# Optional: Allow version overrides from env
nvidia_gpu_operator_version = os.getenv("NVIDIA_GPU_OPERATOR_VERSION", "v25.10.0")
kuberay_operator_version = os.getenv("KUBERAY_OPERATOR_VERSION", "1.5.1")
envoy_gateway_version = os.getenv("ENVOY_GATEWAY_VERSION", "v1.7.0")
kueue_version = os.getenv("KUEUE_VERSION", "0.16.1")

# Validate required environment variables
if not huggingface_token:
    fail("HUGGINGFACE_TOKEN environment variable is required.")
if not openai_api_key:
    fail("OPENAI_API_KEY environment variable is required.")
if not s3_endpoint_hostname:
    fail("S3_ENDPOINT_HOSTNAME environment variable is required.")
if not obj_access_key:
    fail("OBJ_ACCESS_KEY environment variable is required.")
if not obj_secret_key:
    fail("OBJ_SECRET_KEY environment variable is required.")
if not obj_region:
    fail("OBJ_REGION environment variable is required.")

# Detect and allow the LKE context
if k8s_context().startswith("lke"):
    allow_k8s_contexts(k8s_context())
else:
    print("WARNING: Not running on LKE context. Current context: %s" % k8s_context())
    print("Make sure you're connected to the correct cluster!")

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
    resource_deps=["kuberay-operator-repo", "gpu-operator", "kube-prometheus-stack"],
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
    resource_deps=["prometheus-community", "kueue"],
    flags=[
        "--values=./hack/monitoring-values.yaml",
        "--timeout=600s",
    ],
    labels=["monitoring"],
)
local_resource(
    "grafana",
    serve_cmd="kubectl port-forward -n kube-system svc/kube-prometheus-stack-grafana 3000:80",
    resource_deps=["kube-prometheus-stack"],
    labels=["monitoring"],
    links=[link("http://localhost:3000", "Grafana")],
)

# ░█░█░█░█░█▀▀░█░█░█▀▀
# ░█▀▄░█░█░█▀▀░█░█░█▀▀
# ░▀░▀░▀▀▀░▀▀▀░▀▀▀░▀▀▀

helm_resource(
    "kueue",
    "oci://registry.k8s.io/kueue/charts/kueue",
    namespace="kueue-system",
    flags=[
        "--create-namespace",
        "--version=%s" % kueue_version,
        "--wait",
        "--timeout=300s",
    ],
    labels=["kueue"],
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
k8s_yaml(secret_from_dict(
    name="obj-store-secret",
    namespace="default",
    inputs={
        "access_key": obj_access_key,
        "secret_key": obj_secret_key,
        "endpoint_hostname": s3_endpoint_hostname,
        "region": obj_region,
        "bucket": model_bucket,
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
    "envoy:gatewayclass"
    ],
    resource_deps=["envoy-gateway", "llm-gateway-auth"],
    labels=["gateway"],
)

# ░█▀▄░█▀▀░█▀▀░█▀▀░█▀█░█▀▄░█▀▀░█░█░░░█▀█░▀█▀░█▀█░█▀▀░█░░░▀█▀░█▀█░█▀▀
# ░█▀▄░█▀▀░▀▀█░█▀▀░█▀█░█▀▄░█░░░█▀█░░░█▀▀░░█░░█▀▀░█▀▀░█░░░░█░░█░█░█▀▀
# ░▀░▀░▀▀▀░▀▀▀░▀▀▀░▀░▀░▀░▀░▀▀▀░▀░▀░░░▀░░░▀▀▀░▀░░░▀▀▀░▀▀▀░▀▀▀░▀░▀░▀▀▀

# Research Pipeline ConfigMap — auto-updates when serve/research_pipeline.py changes
research_pipeline_code = str(read_file("serve/research_pipeline.py"))
k8s_yaml(encode_yaml({
    "apiVersion": "v1",
    "kind": "ConfigMap",
    "metadata": {
        "name": "research-pipeline-code",
        "namespace": "default",
    },
    "data": {
        "research_pipeline.py": research_pipeline_code,
    },
}))

k8s_resource(
    new_name="research-pipeline-code",
    objects=["research-pipeline-code:configmap"],
    labels=["openwebui"],
)

# ░█░█░█▀█░█▀▀░░░█▄█░█▀█░█▀▄░█▀▀░█░░░░░█▀▀░█▀█░█▀▀░█░█░█▀▀
# ░█▀▄░█▀█░▀▀█░░░█░█░█░█░█░█░█▀▀░█░░░░░█░░░█▀█░█░░░█▀█░█▀▀
# ░▀░▀░▀▀▀░▀▀▀░░░▀░▀░▀▀▀░▀▀░░▀▀▀░▀▀▀░░░▀▀▀░▀░▀░▀▀▀░▀░▀░▀▀▀

# Model Upload Job — caches MiniMax-M2.5 and Nemotron-Parse-v1.2 in Object Storage
k8s_yaml("manifests/model-upload-job.yaml")
k8s_resource(
    "model-upload",
    resource_deps=["hf-secret", "obj-store-secret", "kueue"],
    labels=["kuberay"],
)

# ░█▄█░▀█▀░█▀█░▀█▀░█▄█░█▀█░█░█░░░█▄█░▀▀▄░░░█▀▀░
# ░█░█░░█░░█░█░░█░░█░█░█▀█░▀▄▀░░░█░█░▄▀░░░░▀▀█░
# ░▀░▀░▀▀▀░▀░▀░▀▀▀░▀░▀░▀░▀░░▀░░░░▀░▀░▀▀▀░░░▀▀▀░

# MiniMax M2.5 — large MoE on the 4× Blackwell node
k8s_yaml("manifests/rayservice-minimax.yaml")
k8s_resource(
    new_name="minimax-service",
    objects=[
        "ray-serve-minimax:rayservice",
        "minimax-llm-svc:service",
    ],
    resource_deps=["kuberay-operator", "hf-secret", "obj-store-secret", "model-upload"],
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

# Nemotron Parse v1.2 — KubeRay RayService with fractional GPUs (0.5 GPU/replica)
# 2 workers on the 2× 2-GPU nodes, Ray Serve packs 2 replicas per GPU → up to 8 replicas
k8s_yaml("manifests/rayservice-nemotron-parse.yaml")
k8s_resource(
    new_name="nemotron-parse-service",
    objects=[
        "ray-serve-nemotron-parse:rayservice",
        "nemotron-parse-svc:service",
    ],
    resource_deps=["kuberay-operator", "hf-secret", "obj-store-secret", "model-upload", "gpu-operator"],
    labels=["kuberay"],
)

local_resource(
    "nemotron-parse-dashboard",
    serve_cmd="until kubectl get endpoints nemotron-parse-svc -o jsonpath='{.subsets[0].addresses}' 2>/dev/null | grep -q ip; do echo 'Waiting for nemotron-parse-svc endpoints...'; sleep 5; done && kubectl port-forward svc/nemotron-parse-svc 18265:8265 18000:8000",
    resource_deps=["nemotron-parse-service"],
    labels=["kuberay"],
    links=[link("http://localhost:18265", "Nemotron Parse Ray Dashboard")],
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
    }
))

k8s_resource(
    new_name="openwebui-secret",
    objects=["openwebui-secret:Secret:default"],
    labels=["openwebui"],
)

k8s_yaml("manifests/openwebui.yaml")
k8s_resource(
    "openwebui",
    objects=[
        "openwebui-data:persistentvolumeclaim:default",
    ],
    resource_deps=["openwebui-secret", "minimax-service", "kueue"],
    labels=["openwebui"],
)

k8s_resource(
    "openwebui-pipelines",
    resource_deps=["research-pipeline-code", "openwebui-secret", "kueue"],
    labels=["openwebui"],
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

# Ray Grafana Dashboards — auto-provisioned via Grafana sidecar (7 dashboards)
ray_dashboard_cms = []
for dashboard_path in listdir("hack/grafana-dashboards"):
    if not dashboard_path.endswith(".json"):
        continue
    # listdir returns full paths; extract just the filename
    dashboard_file = dashboard_path.split("/")[-1]
    cm_name = "ray-grafana-" + dashboard_file.replace("_grafana_dashboard.json", "").replace("_", "-")
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
    ray_dashboard_cms.append(cm_name + ":configmap")

k8s_resource(
    new_name="ray-grafana-dashboards",
    objects=ray_dashboard_cms,
    resource_deps=["kube-prometheus-stack"],
    labels=["monitoring"],
)

# ░▀█▀░▀█▀░█▄█░▀█▀░█▀█░█▀▀
# ░░█░░░█░░█░█░░█░░█░█░█░█
# ░░▀░░▀▀▀░▀░▀░▀▀▀░▀░▀░▀▀▀

# Print total deployment time once every resource is ready.
_timer_cmd = "START=%s; NOW=$(date +%%s); ELAPSED=$((NOW - START)); MIN=$((ELAPSED / 60)); SEC=$((ELAPSED %% 60)); echo ''; echo '══════════════════════════════════════════'; echo \"  ✅ All resources ready in ${MIN}m ${SEC}s\"; echo '══════════════════════════════════════════'; echo ''" % _tilt_start_ts
local_resource(
    "deployment-timer",
    cmd=_timer_cmd,
    resource_deps=[
        "openwebui",
        "openwebui-pipelines",
        "minimax-service",
        "nemotron-parse-service",
        "llm-gateway",
        "ray-grafana-dashboards",
    ],
    labels=["status"],
)
