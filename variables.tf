variable "linode_token" {
  description = "Linode API token with permissions for Kubernetes, NodeBalancers, and Events"
  type        = string
  sensitive   = true
}

variable "cluster_label" {
  description = "Label for the LKE cluster"
  type        = string
  default     = "myllm"
}

variable "kubernetes_version" {
  description = "Kubernetes version for the LKE cluster"
  type        = string
  default     = "1.34"
}

variable "region" {
  description = "Linode region for the cluster (us-sea, us-east, etc.)"
  type        = string
  default     = "us-lax"
}

variable "gpu_big_node_type" {
  description = "Linode type for GPU nodes (Blackwell or Ada)"
  type        = string
  default     = "g3-gpu-rtxpro6000-blackwell-4"
}

variable "gpu_big_node_count" {
  description = "Number of GPU nodes in the cluster"
  type        = number
  default     = 1
}

variable "gpu_node_type" {
  description = "Linode type for GPU nodes (Blackwell or Ada)"
  type        = string
  default     = "g3-gpu-rtxpro6000-blackwell-2"
}

variable "gpu_node_count" {
  description = "Number of GPU nodes in the cluster"
  type        = number
  default     = 2
}

variable "tags" {
  description = "Tags to apply to Linode resources for organization and cost tracking"
  type        = list(string)
  default     = ["kuberay", "llm", "gpu"]
}
