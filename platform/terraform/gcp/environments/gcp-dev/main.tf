terraform {
  required_version = ">= 1.0"

  required_providers {
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
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
}

module "platform_core" {
  source = "../../modules/platform-core"

  project_id                    = var.project_id
  environment                   = var.environment
  region                        = var.region
  artifact_registry_location    = var.artifact_registry_location
  gke_release_channel           = var.gke_release_channel
  range_network_cidr            = var.range_network_cidr
  gke_subnet_cidr               = var.gke_subnet_cidr
  gke_pods_cidr                 = var.gke_pods_cidr
  gke_services_cidr             = var.gke_services_cidr
  gke_master_ipv4_cidr          = var.gke_master_ipv4_cidr
  gke_master_authorized_cidrs   = var.gke_master_authorized_cidrs
  web_machine_type              = var.web_machine_type
  worker_machine_type           = var.worker_machine_type
  provisioner_machine_type      = var.provisioner_machine_type
  web_node_count                = var.web_node_count
  worker_node_count             = var.worker_node_count
  provisioner_node_count        = var.provisioner_node_count
  cloud_sql_database_version    = var.cloud_sql_database_version
  cloud_sql_tier                = var.cloud_sql_tier
  cloud_sql_disk_size_gb        = var.cloud_sql_disk_size_gb
  cloud_sql_database_name       = var.cloud_sql_database_name
  cloud_sql_user_name           = var.cloud_sql_user_name
  redis_tier                    = var.redis_tier
  redis_memory_size_gb          = var.redis_memory_size_gb
  public_hostname               = var.public_hostname
  enable_managed_tls            = var.enable_managed_tls
  create_dns_managed_zone       = var.create_dns_managed_zone
  dns_managed_zone_name         = var.dns_managed_zone_name
  dns_zone_dns_name             = var.dns_zone_dns_name
  dns_record_ttl                = var.dns_record_ttl
  identity_allowed_email_domain = var.identity_allowed_email_domain
  identity_allowed_emails       = var.identity_allowed_emails
  labels                        = local.labels
}
