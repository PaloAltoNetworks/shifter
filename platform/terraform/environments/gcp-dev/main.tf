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
