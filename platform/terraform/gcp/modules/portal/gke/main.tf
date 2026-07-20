resource "google_container_cluster" "platform" {
  name     = "${var.name_prefix}-gke"
  project  = var.project_id
  location = var.region

  network    = var.platform_network_id
  subnetwork = var.gke_subnetwork_id

  deletion_protection      = false
  remove_default_node_pool = true
  initial_node_count       = 1

  networking_mode = "VPC_NATIVE"

  ip_allocation_policy {
    cluster_secondary_range_name  = var.gke_pods_secondary_range_name
    services_secondary_range_name = var.gke_services_secondary_range_name

    additional_pod_ranges_config {
      pod_range_names = [var.gke_provisioner_pods_secondary_range_name]
    }
  }

  # Private control plane, secure by default (#1723): no public IP endpoint on the
  # control plane (satisfies org policies such as custom.disableGkePublicControlPlane
  # and is universally the hardened posture). Operator and CI reach the control
  # plane through Connect Gateway via the fleet membership below (IAM-authenticated,
  # no public IP, no DNS endpoint, no bastion), so private-by-default does not cost
  # remote access.
  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = true
    master_ipv4_cidr_block  = var.gke_master_ipv4_cidr
  }

  # Always present (enabled): a private control plane requires
  # master_authorized_networks_config to be enabled. cidr_blocks may be empty —
  # remote access is via the IAM-authenticated DNS endpoint, not a network
  # allowlist (#1723). gcp_public_cidrs_access_enabled defaults false.
  master_authorized_networks_config {
    dynamic "cidr_blocks" {
      for_each = var.gke_master_authorized_cidrs

      content {
        cidr_block   = cidr_blocks.value
        display_name = "admin-${replace(replace(cidr_blocks.value, "/", "-"), ".", "-")}"
      }
    }
  }

  release_channel {
    channel = var.gke_release_channel
  }

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  # Register the cluster to the project fleet so operator/CI reach the private
  # control plane through Connect Gateway (IAM-authenticated, no public endpoint,
  # no DNS endpoint, no bastion) — the access path for a private control plane
  # when both the public endpoint and the Google DNS endpoint are disallowed
  # (#1723). Credentials: `gcloud container fleet memberships get-credentials`.
  fleet {
    project = var.project_id
  }

  binary_authorization {
    evaluation_mode = "PROJECT_SINGLETON_POLICY_ENFORCE"
  }

  logging_config {
    enable_components = ["SYSTEM_COMPONENTS", "WORKLOADS"]
  }

  monitoring_config {
    enable_components = ["SYSTEM_COMPONENTS"]
  }

  resource_labels = var.common_labels
}

resource "google_container_node_pool" "web" {
  name       = "${var.name_prefix}-web"
  project    = var.project_id
  location   = var.region
  cluster    = google_container_cluster.platform.name
  node_count = var.web_node_count

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  node_config {
    machine_type    = var.web_machine_type
    service_account = var.node_service_account_email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    labels          = merge(var.common_labels, { role = "web" })
    tags            = ["shifter", "gke", "web"]

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

resource "google_container_node_pool" "workers" {
  name       = "${var.name_prefix}-workers"
  project    = var.project_id
  location   = var.region
  cluster    = google_container_cluster.platform.name
  node_count = var.worker_node_count

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  node_config {
    machine_type    = var.worker_machine_type
    service_account = var.node_service_account_email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    labels          = merge(var.common_labels, { role = "workers" })
    tags            = ["shifter", "gke", "workers"]

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

resource "google_container_node_pool" "provisioner" {
  name       = "${var.name_prefix}-provisioner"
  project    = var.project_id
  location   = var.region
  cluster    = google_container_cluster.platform.name
  node_count = var.provisioner_node_count

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  network_config {
    # Private nodes (no external IP): egress is via Cloud NAT, matching the web/
    # workers pools and the cluster default. Specifying network_config without
    # enable_private_nodes otherwise defaults it to false (public/external IP),
    # which is both a needless exposure and a violation of the
    # constraints/compute.vmExternalIpAccess org policy (#1723).
    enable_private_nodes = true
    create_pod_range     = false
    pod_range            = var.gke_provisioner_pods_secondary_range_name
  }

  node_config {
    machine_type    = var.provisioner_machine_type
    service_account = var.node_service_account_email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    labels          = merge(var.common_labels, { role = "provisioner" })
    tags            = ["shifter", "gke", "provisioner"]

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
