terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region

  default_labels = {
    project     = "shifter"
    managed_by  = "terraform"
    environment = var.environment
  }
}

locals {
  name_prefix = "${var.environment}-range"
}

# ------------------------------------------------------------------------------
# Network Foundation (VPC, GKE subnet, Cloud NAT)
# ------------------------------------------------------------------------------

module "network" {
  source = "../../modules/gcp-network"

  project_id      = var.project_id
  region          = var.region
  name_prefix     = local.name_prefix
  gke_subnet_cidr = var.gke_subnet_cidr
  gke_pods_cidr   = var.gke_pods_cidr
  gke_services_cidr = var.gke_services_cidr
  enable_flow_logs  = var.enable_flow_logs

  labels = var.labels
}

# ------------------------------------------------------------------------------
# GKE Cluster (KubeVirt-ready, with system + KubeVirt node pools)
# ------------------------------------------------------------------------------

module "gke" {
  source = "../../modules/gcp-gke"

  project_id = var.project_id
  region     = var.region
  name_prefix = local.name_prefix

  # Network inputs from network module
  network_id              = module.network.network_id
  gke_subnet_id           = module.network.gke_subnet_id
  gke_pods_range_name     = module.network.gke_pods_range_name
  gke_services_range_name = module.network.gke_services_range_name

  # Cluster settings
  master_authorized_cidrs = var.master_authorized_cidrs
  deletion_protection     = var.deletion_protection

  # KubeVirt node pool
  kubevirt_machine_type = var.kubevirt_machine_type
  kubevirt_node_count   = var.kubevirt_node_count

  labels = var.labels
}
