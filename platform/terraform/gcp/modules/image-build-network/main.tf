# Optional foundation-owned image network breaks the first-bake/platform cycle.
# It has no peering to runtime or runner networks and outlives platform teardown.
variable "project_id" {
  description = "Project that owns the isolated image-build network."
  type        = string
}

variable "region" {
  description = "Region for the image-build subnet and Cloud NAT."
  type        = string
}

variable "name_prefix" {
  description = "Stable foundation resource name prefix."
  type        = string
}

variable "packer_build_service_account_email" {
  description = "Build identity permitted through the IAP management firewall."
  type        = string
}

variable "enable_image_build_network" {
  description = "Create an isolated private image-build network before platform bootstrap."
  type        = bool
  default     = false
}

variable "image_build_subnet_cidr" {
  description = "Private subnet used only by disposable image builders and validators."
  type        = string
  default     = "10.201.0.0/24"
}

resource "google_compute_network" "image_build" {
  count                   = var.enable_image_build_network ? 1 : 0
  project                 = var.project_id
  name                    = "${var.name_prefix}-image-build"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
}

resource "google_compute_subnetwork" "image_build" {
  count                    = var.enable_image_build_network ? 1 : 0
  project                  = var.project_id
  name                     = "${var.name_prefix}-image-build"
  region                   = var.region
  network                  = google_compute_network.image_build[0].id
  ip_cidr_range            = var.image_build_subnet_cidr
  private_ip_google_access = true
  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

resource "google_compute_router" "image_build" {
  count   = var.enable_image_build_network ? 1 : 0
  project = var.project_id
  name    = "${var.name_prefix}-image-build"
  region  = var.region
  network = google_compute_network.image_build[0].id
}

resource "google_compute_router_nat" "image_build" {
  count                              = var.enable_image_build_network ? 1 : 0
  project                            = var.project_id
  name                               = "${var.name_prefix}-image-build"
  region                             = var.region
  router                             = google_compute_router.image_build[0].name
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"
  subnetwork {
    name                    = google_compute_subnetwork.image_build[0].id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }
  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

resource "google_compute_firewall" "image_build_iap" {
  count                   = var.enable_image_build_network ? 1 : 0
  project                 = var.project_id
  name                    = "${var.name_prefix}-image-build-iap"
  network                 = google_compute_network.image_build[0].id
  direction               = "INGRESS"
  source_ranges           = ["35.235.240.0/20"] # Google IAP TCP forwarding.
  target_service_accounts = [var.packer_build_service_account_email]
  allow {
    protocol = "tcp"
    # Linux bake hosts expose their dedicated management SSH endpoint on 2222.
    # Keep the Windows build endpoint on 5986 and the standard SSH endpoint for
    # generic image tooling.
    ports = ["22", "2222", "5986"]
  }
  log_config {
    metadata = "INCLUDE_ALL_METADATA"
  }
}

resource "google_compute_firewall" "image_validate_iap" {
  count         = var.enable_image_build_network ? 1 : 0
  project       = var.project_id
  name          = "${var.name_prefix}-image-validate-iap"
  network       = google_compute_network.image_build[0].id
  direction     = "INGRESS"
  source_ranges = ["35.235.240.0/20"] # Google IAP TCP forwarding.
  target_tags   = ["shifter-validation"]
  allow {
    protocol = "tcp"
    ports    = ["22", "389", "2222"]
  }
  log_config {
    metadata = "INCLUDE_ALL_METADATA"
  }
}

output "image_build_network_name" {
  description = "GCP_PACKER_NETWORK and GCP_VALIDATE_NETWORK for first-project image jobs."
  value       = try(google_compute_network.image_build[0].name, "")
}

output "image_build_subnetwork_name" {
  description = "GCP_PACKER_SUBNETWORK and GCP_VALIDATE_SUBNETWORK for first-project image jobs."
  value       = try(google_compute_subnetwork.image_build[0].name, "")
}
