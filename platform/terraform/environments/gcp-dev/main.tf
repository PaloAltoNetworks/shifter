terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    kubectl = {
      source  = "gavinbunney/kubectl"
      version = ">= 1.14.0"
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

# kubectl provider — authenticates to GKE cluster for KubeVirt operator install
provider "kubectl" {
  host                   = "https://${module.gke.cluster_endpoint}"
  cluster_ca_certificate = base64decode(module.gke.cluster_ca_certificate)
  token                  = data.google_client_config.default.access_token
  load_config_file       = false
}

data "google_client_config" "default" {}

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

# ------------------------------------------------------------------------------
# KubeVirt + CDI Operators + Artifact Registry
# ------------------------------------------------------------------------------

module "kubevirt" {
  source = "../../modules/gcp-kubevirt"

  project_id  = var.project_id
  region      = var.region
  name_prefix = local.name_prefix

  kubevirt_version = var.kubevirt_version
  cdi_version      = var.cdi_version

  gke_node_service_account_email = module.gke.node_service_account_email
  cicd_service_account_email     = var.cicd_service_account_email

  labels = var.labels
}

# ------------------------------------------------------------------------------
# Object Storage (GCS — agent files, artifacts)
# ------------------------------------------------------------------------------

module "storage" {
  source = "../../modules/gcp-storage"

  project_id  = var.project_id
  region      = var.region
  name_prefix = local.name_prefix

  gke_node_service_account_email = module.gke.node_service_account_email
  cicd_service_account_email     = var.cicd_service_account_email

  labels = var.labels
}

# ------------------------------------------------------------------------------
# Pub/Sub (range status events)
# ------------------------------------------------------------------------------

module "pubsub" {
  source = "../../modules/gcp-pubsub"

  project_id  = var.project_id
  name_prefix = local.name_prefix

  labels = var.labels
}

# ------------------------------------------------------------------------------
# Secret Manager (platform secrets — containers only, values set manually)
# ------------------------------------------------------------------------------

module "secrets" {
  source = "../../modules/gcp-secrets"

  project_id  = var.project_id
  name_prefix = local.name_prefix

  labels = var.labels
}

# ------------------------------------------------------------------------------
# Cloud SQL PostgreSQL (private IP via Private Services Access)
# ------------------------------------------------------------------------------

module "database" {
  source = "../../modules/gcp-database"

  project_id  = var.project_id
  region      = var.region
  name_prefix = local.name_prefix
  network_id  = module.network.network_id

  tier                = var.db_tier
  availability_type   = var.db_availability_type
  deletion_protection = var.deletion_protection

  labels = var.labels
}

# ------------------------------------------------------------------------------
# Memorystore Redis (sessions, Django Channels)
# Uses the Private Services Access peering created by the database module.
# ------------------------------------------------------------------------------

module "redis" {
  source = "../../modules/gcp-redis"

  project_id     = var.project_id
  region         = var.region
  name_prefix    = local.name_prefix
  network_id     = module.network.network_id
  tier           = var.redis_tier
  memory_size_gb = var.redis_memory_size_gb

  labels = var.labels

  depends_on = [module.database]
}
