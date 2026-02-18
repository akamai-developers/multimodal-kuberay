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
    port_forwards=[port_forward(3000, 3000, name='grafana')]
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
    "envoy:gatewayclass"
    ],
    resource_deps=["envoy-gateway", "llm-gateway-auth"],
    labels=["gateway"],
)

# RayService
k8s_yaml("manifests/rayservice.yaml")
k8s_resource(
    new_name="ray-service",
    objects=[
        "ray-serve-llm:rayservice",
    ],
    resource_deps=["kuberay-operator", "hf-secret"],
    labels=["kuberay"],
    port_forwards=["8265:8265", "8000:8000"],
)
