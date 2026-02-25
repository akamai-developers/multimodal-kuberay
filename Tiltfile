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
    resource_deps=["prometheus-community"],
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
    "tts-route:httproute",
    "llm-gateway-auth:securitypolicy",
    "llm-gateway-client-policy:clienttrafficpolicy",
    "tts-backend-policy:backendtrafficpolicy",
    "envoy:gatewayclass"
    ],
    resource_deps=["envoy-gateway", "llm-gateway-auth"],
    labels=["gateway"],
)

# ░▀█▀░▀█▀░█▀▀░░░█▀▀░█▀▀░█▀▄░█░█░▀█▀░█▀▀░█▀▀
# ░░█░░░█░░▀▀█░░░▀▀█░█▀▀░█▀▄░▀▄▀░░█░░█░░░█▀▀
# ░░▀░░░▀░░▀▀▀░░░▀▀▀░▀▀▀░▀░▀░░▀░░▀▀▀░▀▀▀░▀▀▀

# TTS Serve Code ConfigMap — auto-updates when serve/tts_app.py changes
tts_serve_code = str(read_file("serve/tts_app.py"))
k8s_yaml(encode_yaml({
    "apiVersion": "v1",
    "kind": "ConfigMap",
    "metadata": {
        "name": "tts-serve-code",
        "namespace": "default",
    },
    "data": {
        "tts_app.py": tts_serve_code,
    },
}))

k8s_resource(
    new_name="tts-serve-code",
    objects=["tts-serve-code:configmap"],
    labels=["tts"],
)

# ░█▄█░█▀█░█▀▄░█▀▀░█░░░░░█▀▀░█▀█░█▀▀░█░█░█▀▀
# ░█░█░█░█░█░█░█▀▀░█░░░░░█░░░█▀█░█░░░█▀█░█▀▀
# ░▀░▀░▀▀▀░▀▀░░▀▀▀░▀▀▀░░░▀▀▀░▀░▀░▀▀▀░▀░▀░▀▀▀

# Model Upload Job — seeds Linode Object Storage with model weights
k8s_yaml("manifests/model-upload-job.yaml")
k8s_resource(
    "model-upload",
    resource_deps=["hf-secret", "obj-store-secret"],
    labels=["kuberay"],
)

# TTS RayService
k8s_yaml("manifests/rayservice-tts.yaml")
k8s_resource(
    new_name="tts-service",
    objects=[
        "ray-serve-tts:rayservice",
    ],
    resource_deps=["kuberay-operator", "hf-secret", "obj-store-secret", "tts-serve-code", "model-upload"],
    labels=["tts"],
    port_forwards=["8266:8265", "8001:8000"],
)

k8s_yaml("manifests/rayservice.yaml")
k8s_resource(
    new_name="ray-service",
    objects=[
        "ray-serve-llm:rayservice",
    ],
    resource_deps=["kuberay-operator", "hf-secret", "obj-store-secret", "model-upload"],
    labels=["kuberay"],
    port_forwards=["8265:8265", "8000:8000"],
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
