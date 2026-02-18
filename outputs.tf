output "cluster_id" {
  description = "LKE cluster ID"
  value       = linode_lke_cluster.gpu_cluster.id
}

output "cluster_label" {
  description = "LKE cluster label"
  value       = linode_lke_cluster.gpu_cluster.label
}

output "cluster_region" {
  description = "LKE cluster region"
  value       = linode_lke_cluster.gpu_cluster.region
}

output "kubeconfig" {
  description = "Kubeconfig for accessing the cluster (base64 encoded)"
  value       = linode_lke_cluster.gpu_cluster.kubeconfig
  sensitive   = true
}

output "kubeconfig_raw" {
  description = "Kubeconfig for accessing the cluster (decoded)"
  value       = base64decode(linode_lke_cluster.gpu_cluster.kubeconfig)
  sensitive   = true
}