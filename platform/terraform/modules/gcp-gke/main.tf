# GKE Cluster for KubeVirt Range Workloads
#
# GKE Standard cluster configured for running full VMs via KubeVirt:
# - Ubuntu node image (provides /dev/kvm kernel module)
# - Nested virtualization enabled on node pool
# - Dataplane V2 (Cilium) for native NetworkPolicy enforcement
# - Private nodes (no public IPs), public API endpoint with authorized networks
# - Separate node pool for KubeVirt VMs (can be scaled independently)
#
# KubeVirt itself is installed post-cluster via operator manifests (not Terraform).

terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

locals {
  labels = merge(var.labels, {
    module = "gcp-gke"
  })
}

# ------------------------------------------------------------------------------
# Service Account for GKE Nodes
#
# Least-privilege SA instead of the default compute SA.
# Grants only what nodes need: pull images, write logs/metrics, read secrets.
# ------------------------------------------------------------------------------

resource "google_service_account" "gke_nodes" {
  account_id   = "${var.name_prefix}-gke-nodes"
  display_name = "GKE nodes for ${var.name_prefix}"
  project      = var.project_id
}

resource "google_project_iam_member" "gke_nodes_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.gke_nodes.email}"
}

resource "google_project_iam_member" "gke_nodes_metric_writer" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.gke_nodes.email}"
}

resource "google_project_iam_member" "gke_nodes_monitoring_viewer" {
  project = var.project_id
  role    = "roles/monitoring.viewer"
  member  = "serviceAccount:${google_service_account.gke_nodes.email}"
}

resource "google_project_iam_member" "gke_nodes_artifact_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.gke_nodes.email}"
}

# ------------------------------------------------------------------------------
# GKE Cluster
# ------------------------------------------------------------------------------

resource "google_container_cluster" "this" {
  name     = "${var.name_prefix}-gke"
  location = var.region
  project  = var.project_id

  # Remove default node pool — we manage our own
  remove_default_node_pool = true
  initial_node_count       = 1

  # VPC-native networking (required for Dataplane V2)
  network    = var.network_id
  subnetwork = var.gke_subnet_id

  ip_allocation_policy {
    cluster_secondary_range_name  = var.gke_pods_range_name
    services_secondary_range_name = var.gke_services_range_name
  }

  # Dataplane V2 (Cilium) — native NetworkPolicy enforcement
  datapath_provider = "ADVANCED_DATAPATH"

  # Private cluster — nodes get internal IPs only
  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = false
    master_ipv4_cidr_block  = var.master_cidr
  }

  # Authorized networks for API server access
  master_authorized_networks_config {
    dynamic "cidr_blocks" {
      for_each = var.master_authorized_cidrs
      content {
        cidr_block   = cidr_blocks.value.cidr
        display_name = cidr_blocks.value.name
      }
    }
  }

  # Release channel
  release_channel {
    channel = "REGULAR"
  }

  # Workload Identity for pod-level GCP auth
  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  # Logging and monitoring
  logging_config {
    enable_components = ["SYSTEM_COMPONENTS", "WORKLOADS"]
  }
  monitoring_config {
    enable_components = ["SYSTEM_COMPONENTS"]
    managed_prometheus {
      enabled = true
    }
  }

  # Binary authorization (disabled for now — KubeVirt images aren't signed)
  binary_authorization {
    evaluation_mode = "DISABLED"
  }

  resource_labels = local.labels

  deletion_protection = var.deletion_protection
}

# ------------------------------------------------------------------------------
# System Node Pool (small, for cluster services: CoreDNS, KubeVirt operator, etc.)
# ------------------------------------------------------------------------------

resource "google_container_node_pool" "system" {
  name     = "${var.name_prefix}-system"
  cluster  = google_container_cluster.this.name
  location = var.region
  project  = var.project_id

  node_count = var.system_node_count

  node_config {
    machine_type = var.system_machine_type
    image_type   = "COS_CONTAINERD"
    disk_size_gb = 50
    disk_type    = "pd-ssd"

    service_account = google_service_account.gke_nodes.email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]

    labels = merge(local.labels, {
      role = "system"
    })

    tags = ["gke-node", "gke-system"]

    workload_metadata_config {
      mode = "GKE_METADATA"
    }
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }
}

# ------------------------------------------------------------------------------
# KubeVirt Node Pool (Ubuntu + nested virt for running VMs)
#
# This is the pool that runs actual KubeVirt VMs. Uses:
# - Ubuntu image (provides /dev/kvm)
# - Nested virtualization enabled
# - Larger instances for VM density
# - SSD disks for VM disk I/O
# ------------------------------------------------------------------------------

resource "google_container_node_pool" "kubevirt" {
  name     = "${var.name_prefix}-kubevirt"
  cluster  = google_container_cluster.this.name
  location = var.region
  project  = var.project_id

  node_count = var.kubevirt_node_count

  node_config {
    machine_type = var.kubevirt_machine_type
    image_type   = "UBUNTU_CONTAINERD"
    disk_size_gb = var.kubevirt_disk_size_gb
    disk_type    = "pd-ssd"

    # Nested virtualization — exposes /dev/kvm to pods
    advanced_machine_features {
      enable_nested_virtualization = true
    }

    service_account = google_service_account.gke_nodes.email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]

    labels = merge(local.labels, {
      role = "kubevirt"
    })

    tags = ["gke-node", "gke-kubevirt"]

    taint {
      key    = "kubevirt.io/schedulable"
      value  = "true"
      effect = "PREFER_NO_SCHEDULE"
    }

    workload_metadata_config {
      mode = "GKE_METADATA"
    }
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  upgrade_settings {
    max_surge       = 1
    max_unavailable = 0
  }
}
