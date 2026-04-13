terraform {
  required_version = ">= 1.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.12"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  labels = {
    environment = var.environment
    managed_by  = "terraform"
    project     = "shifter"
  }
  asset_bucket_cors_allowed_origins = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:18080",
    "http://127.0.0.1:18080",
  ]
}

data "google_compute_network" "platform" {
  name    = module.platform_core.network_name
  project = var.project_id
}

data "google_compute_network" "gdc_control_plane" {
  name    = var.gdc_control_plane_network_name
  project = var.project_id
}

module "platform_core" {
  source = "../../modules/platform-core"

  project_id                        = var.project_id
  environment                       = var.environment
  region                            = var.region
  artifact_registry_location        = var.artifact_registry_location
  gke_release_channel               = var.gke_release_channel
  range_network_cidr                = var.range_network_cidr
  gke_subnet_cidr                   = var.gke_subnet_cidr
  gke_pods_cidr                     = var.gke_pods_cidr
  gke_services_cidr                 = var.gke_services_cidr
  gke_master_ipv4_cidr              = var.gke_master_ipv4_cidr
  gke_master_authorized_cidrs       = var.gke_master_authorized_cidrs
  gke_master_authorized_ci_cidrs    = var.gke_master_authorized_ci_cidrs
  web_machine_type                  = var.web_machine_type
  worker_machine_type               = var.worker_machine_type
  provisioner_machine_type          = var.provisioner_machine_type
  web_node_count                    = var.web_node_count
  worker_node_count                 = var.worker_node_count
  provisioner_node_count            = var.provisioner_node_count
  cloud_sql_database_version        = var.cloud_sql_database_version
  cloud_sql_tier                    = var.cloud_sql_tier
  cloud_sql_disk_size_gb            = var.cloud_sql_disk_size_gb
  cloud_sql_database_name           = var.cloud_sql_database_name
  cloud_sql_user_name               = var.cloud_sql_user_name
  redis_tier                        = var.redis_tier
  redis_memory_size_gb              = var.redis_memory_size_gb
  public_hostname                   = var.public_hostname
  enable_managed_tls                = var.enable_managed_tls
  create_dns_managed_zone           = var.create_dns_managed_zone
  dns_managed_zone_name             = var.dns_managed_zone_name
  dns_zone_dns_name                 = var.dns_zone_dns_name
  dns_record_ttl                    = var.dns_record_ttl
  asset_bucket_cors_allowed_origins = local.asset_bucket_cors_allowed_origins
  identity_allowed_email_domain     = var.identity_allowed_email_domain
  identity_allowed_emails           = var.identity_allowed_emails
  monitoring_alert_email            = var.monitoring_alert_email
  ctfd_enabled                      = var.ctfd_enabled
  ctfd_machine_type                 = var.ctfd_machine_type
  ctfd_disk_size_gb                 = var.ctfd_disk_size_gb
  ctfd_subnet_cidr                  = var.ctfd_subnet_cidr
  ctfd_ssh_source_cidrs             = var.ctfd_ssh_source_cidrs
  labels                            = local.labels
}

resource "google_compute_network_peering" "platform_to_gdc_control_plane" {
  name         = "${module.platform_core.network_name}-to-${var.gdc_control_plane_network_name}"
  network      = data.google_compute_network.platform.id
  peer_network = data.google_compute_network.gdc_control_plane.id
}

resource "google_compute_network_peering" "gdc_control_plane_to_platform" {
  name         = "${var.gdc_control_plane_network_name}-to-${module.platform_core.network_name}"
  network      = data.google_compute_network.gdc_control_plane.id
  peer_network = data.google_compute_network.platform.id

  depends_on = [google_compute_network_peering.platform_to_gdc_control_plane]
}

resource "google_compute_firewall" "gdc_control_plane_api_from_platform" {
  name    = "${var.gdc_control_plane_network_name}-allow-platform-k8s-api"
  project = var.project_id
  network = data.google_compute_network.gdc_control_plane.name

  description = "Allow the Shifter platform VPC to reach the GDC Kubernetes API for range provisioning."
  direction   = "INGRESS"
  priority    = 1000

  allow {
    protocol = "tcp"
    ports    = ["443", "6444"]
  }

  source_ranges = module.platform_core.portal_network_cidrs
  target_tags   = [var.gdc_control_plane_network_name]
}
