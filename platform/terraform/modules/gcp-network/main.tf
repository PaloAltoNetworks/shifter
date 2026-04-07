# GCP Network Foundation for Shifter
#
# Bare minimum networking required before GKE can be deployed:
# - VPC with a GKE subnet (primary + secondary ranges for pods/services)
# - Cloud Router + Cloud NAT for outbound internet
# - Firewall rules for cluster operation
#
# Intentionally does NOT include (added in later slices):
# - Portal subnet and load balancer
# - Cloud SQL / Private Services Access
# - Cloud NGFW FQDN egress policies
# - Cloud Armor WAF

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
    module = "gcp-network"
  })
}

# ------------------------------------------------------------------------------
# VPC
# ------------------------------------------------------------------------------

resource "google_compute_network" "this" {
  name                    = "${var.name_prefix}-vpc"
  auto_create_subnetworks = false
  project                 = var.project_id
}

# ------------------------------------------------------------------------------
# GKE Subnet
#
# GCP subnets are regional (span all zones). One subnet is sufficient for GKE.
# Secondary ranges provide dedicated CIDRs for pods and services, keeping them
# separate from node IPs (required for VPC-native GKE clusters).
# ------------------------------------------------------------------------------

resource "google_compute_subnetwork" "gke" {
  name          = "${var.name_prefix}-gke"
  network       = google_compute_network.this.id
  region        = var.region
  ip_cidr_range = var.gke_subnet_cidr
  project       = var.project_id

  secondary_ip_range {
    range_name    = "${var.name_prefix}-pods"
    ip_cidr_range = var.gke_pods_cidr
  }

  secondary_ip_range {
    range_name    = "${var.name_prefix}-services"
    ip_cidr_range = var.gke_services_cidr
  }

  private_ip_google_access = true

  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = var.enable_flow_logs ? 0.5 : 0
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

# ------------------------------------------------------------------------------
# Cloud Router (required by Cloud NAT)
# ------------------------------------------------------------------------------

resource "google_compute_router" "this" {
  name    = "${var.name_prefix}-router"
  network = google_compute_network.this.id
  region  = var.region
  project = var.project_id
}

# ------------------------------------------------------------------------------
# Cloud NAT
#
# Provides outbound internet for GKE nodes and pods (no public IPs needed).
# Distributed — no single-instance bottleneck like AWS NAT Gateway.
# Covers all primary and secondary ranges in the GKE subnet.
# ------------------------------------------------------------------------------

resource "google_compute_router_nat" "this" {
  name                               = "${var.name_prefix}-nat"
  router                             = google_compute_router.this.name
  region                             = var.region
  project                            = var.project_id
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"

  subnetwork {
    name                    = google_compute_subnetwork.gke.id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }

  log_config {
    enable = var.enable_nat_logging
    filter = "ERRORS_ONLY"
  }
}

# ------------------------------------------------------------------------------
# Firewall Rules
#
# GCP firewall rules are VPC-level (not per-subnet like AWS security groups).
# They target instances via network tags.
# ------------------------------------------------------------------------------

# Allow internal traffic within the VPC (nodes, pods, services)
resource "google_compute_firewall" "allow_internal" {
  name    = "${var.name_prefix}-allow-internal"
  network = google_compute_network.this.id
  project = var.project_id

  allow {
    protocol = "tcp"
  }
  allow {
    protocol = "udp"
  }
  allow {
    protocol = "icmp"
  }

  source_ranges = [
    var.gke_subnet_cidr,
    var.gke_pods_cidr,
    var.gke_services_cidr,
  ]

  description = "Allow internal traffic between nodes, pods, and services"
}

# Allow GCP health check probes (required for load balancers and GKE)
resource "google_compute_firewall" "allow_health_checks" {
  name    = "${var.name_prefix}-allow-health-checks"
  network = google_compute_network.this.id
  project = var.project_id

  allow {
    protocol = "tcp"
  }

  # Google health check source ranges (documented, stable)
  source_ranges = [
    "35.191.0.0/16",
    "130.211.0.0/22",
  ]

  target_tags = ["gke-node"]

  description = "Allow GCP health check probes to GKE nodes"
}

# Allow SSH for debugging (IAP tunnel only — no open SSH from internet)
resource "google_compute_firewall" "allow_iap_ssh" {
  name    = "${var.name_prefix}-allow-iap-ssh"
  network = google_compute_network.this.id
  project = var.project_id

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  # IAP's source range (documented, stable)
  source_ranges = ["35.235.240.0/20"]

  target_tags = ["gke-node"]

  description = "Allow SSH via IAP tunnel for node debugging"
}
