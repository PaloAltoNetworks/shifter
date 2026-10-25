# Untrusted tenant code has a distinct sandbox pool. RuntimeClass admission and
# node placement are mandatory; a missing pool cannot fall back to platform nodes.
resource "google_container_node_pool" "runtime_plugins" {
  provider           = google-beta
  name               = "${var.name_prefix}-runtime-plugins"
  project            = var.project_id
  location           = var.region
  cluster            = google_container_cluster.platform.name
  initial_node_count = 1

  autoscaling {
    total_min_node_count = 1
    total_max_node_count = 3
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  network_config {
    enable_private_nodes = true
    create_pod_range     = false
    pod_range            = var.gke_pods_secondary_range_name
  }

  node_config {
    machine_type    = "e2-standard-4"
    image_type      = "COS_CONTAINERD"
    service_account = var.node_service_account_email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    labels          = merge(var.common_labels, { "node-restriction.kubernetes.io/shifter-pool" = "runtime-plugin" })
    tags            = ["shifter", "gke", "runtime-plugin"]

    sandbox_config {
      type = "GVISOR"
    }

    taint {
      key    = "shifter.dev/runtime-plugin"
      value  = "true"
      effect = "NO_SCHEDULE"
    }

    metadata = {
      disable-legacy-endpoints = "true"
    }

    shielded_instance_config {
      enable_secure_boot          = true
      enable_integrity_monitoring = true
    }

    workload_metadata_config {
      mode = "GKE_METADATA"
    }
  }
}
