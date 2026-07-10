resource "google_compute_network" "platform" {
  name                    = "${var.name_prefix}-platform"
  project                 = var.project_id
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "gke" {
  name                     = "${var.name_prefix}-gke"
  project                  = var.project_id
  region                   = var.region
  network                  = google_compute_network.platform.id
  ip_cidr_range            = var.gke_subnet_cidr
  private_ip_google_access = true

  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }

  secondary_ip_range {
    range_name    = var.gke_pods_secondary_range_name
    ip_cidr_range = var.gke_pods_cidr
  }

  secondary_ip_range {
    range_name    = var.gke_services_secondary_range_name
    ip_cidr_range = var.gke_services_cidr
  }

  secondary_ip_range {
    range_name    = var.gke_provisioner_pods_secondary_range_name
    ip_cidr_range = var.gke_provisioner_pods_cidr
  }
}

resource "google_compute_router" "nat" {
  name    = "${var.name_prefix}-nat"
  project = var.project_id
  region  = var.region
  network = google_compute_network.platform.id
}

resource "google_compute_address" "nat" {
  name         = "${var.name_prefix}-nat-egress"
  project      = var.project_id
  region       = var.region
  address_type = "EXTERNAL"
}

resource "google_compute_router_nat" "nat" {
  name                               = "${var.name_prefix}-nat"
  project                            = var.project_id
  region                             = var.region
  router                             = google_compute_router.nat.name
  nat_ip_allocate_option             = "MANUAL_ONLY"
  nat_ips                            = [google_compute_address.nat.self_link]
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

resource "google_compute_firewall" "platform_deny_external_ssh_rdp" {
  name        = "${var.name_prefix}-platform-deny-external-ssh-rdp"
  project     = var.project_id
  network     = google_compute_network.platform.name
  description = "ADR-008-R4: SSH/RDP from 0.0.0.0/0 is never allowed into the platform VPC."
  direction   = "INGRESS"
  priority    = 900

  source_ranges = ["0.0.0.0/0"]

  deny {
    protocol = "tcp"
    ports    = ["22", "3389"]
  }
}

resource "google_compute_firewall" "platform_allow_gke_health_checks" {
  name        = "${var.name_prefix}-platform-allow-gke-health-checks"
  project     = var.project_id
  network     = google_compute_network.platform.name
  description = "ADR-008-R4: Google LB health-check ranges reach GKE nodes; required for backend probes."
  direction   = "INGRESS"
  priority    = 1000

  source_ranges = [
    "35.191.0.0/16",
    "130.211.0.0/22",
  ]

  target_tags = ["gke"]

  allow {
    protocol = "tcp"
    ports    = ["80", "443", "8000", "8080", "30000-32767"]
  }
}

resource "google_compute_firewall" "platform_allow_operator_admin_ssh" {
  count = length(var.operator_admin_cidrs) > 0 ? 1 : 0

  name        = "${var.name_prefix}-platform-allow-operator-admin-ssh"
  project     = var.project_id
  network     = google_compute_network.platform.name
  description = "ADR-008-R4: break-glass direct SSH onto GKE platform nodes from the operator-admin CIDR allowlist (not IAP)."
  direction   = "INGRESS"
  priority    = 800

  source_ranges = var.operator_admin_cidrs
  target_tags   = ["gke"]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_compute_global_address" "services" {
  name          = "${var.name_prefix}-services"
  project       = var.project_id
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = var.private_service_range_prefix_length
  network       = google_compute_network.platform.id
}

resource "google_service_networking_connection" "services" {
  network                 = google_compute_network.platform.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.services.name]
}
