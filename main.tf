terraform {
  required_providers {
    linode = {
      source = "linode/linode"
    }
  }
}

# ============================================================================
# PROVIDERS
# ============================================================================

provider "linode" {
  token = var.linode_token
}

# ============================================================================
# LKE CLUSTER WITH GPU NODE POOL
# ============================================================================

resource "linode_lke_cluster" "gpu_cluster" {
  label       = var.cluster_label
  k8s_version = var.kubernetes_version
  region      = var.region
  tags        = var.tags

  control_plane {
    high_availability = true
  }

  # GPU Node Pool
  pool {
    type  = var.gpu_node_type
    count = var.gpu_node_count

    autoscaler {
      min = var.gpu_node_count
      max = var.gpu_node_count
    }
  }
}
