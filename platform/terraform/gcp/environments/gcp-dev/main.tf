terraform {
  required_version = ">= 1.5.0"

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
  name_prefix = "shifter-${var.environment}"
  labels = {
    environment = var.environment
    managed_by  = "terraform"
    project     = "shifter"
  }
}

# GitHub Actions -> GCP federation for the packer GCE image builds
# (.github/workflows/packer-gcp.yml). Emits the GCP_WORKLOAD_IDENTITY_PROVIDER
# and GCP_SERVICE_ACCOUNT values consumed as GitHub secrets.
module "cicd_github_oidc" {
  source = "../../modules/cicd-github-oidc"

  project_id       = var.project_id
  environment      = var.environment
  name_prefix      = local.name_prefix
  region           = var.region
  github_org       = var.github_org
  github_repo      = var.github_repo
  platform_network = module.platform_core.network_name
  # The GDC VM Runtime reads gs:// disk images using the bare-metal GCR
  # service account key carried in GDC_VM_IMAGE_GCS_SECRET_ID.
  image_reader_service_accounts = ["baremetal-gcr@${var.project_id}.iam.gserviceaccount.com"]
  labels                        = local.labels
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
  web_machine_type                  = var.web_machine_type
  worker_machine_type               = var.worker_machine_type
  provisioner_machine_type          = var.provisioner_machine_type
  web_node_count                    = var.web_node_count
  worker_node_count                 = var.worker_node_count
  provisioner_node_count            = var.provisioner_node_count
  cloud_sql_database_version        = var.cloud_sql_database_version
  cloud_sql_tier                    = var.cloud_sql_tier
  cloud_sql_availability_type       = var.cloud_sql_availability_type
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
  identity_allowed_email_domain     = var.identity_allowed_email_domain
  identity_allowed_emails           = var.identity_allowed_emails
  enable_identity_blocking_function = var.enable_identity_blocking_function
  email_backend                     = var.email_backend
  email_from_address                = var.email_from_address
  email_sender_domain               = var.email_sender_domain
  range_egress_mode                 = var.range_egress_mode
  range_egress_allowed_cidrs        = var.range_egress_allowed_cidrs
  labels                            = local.labels

  messaging_enable_dlq                  = var.messaging_enable_dlq
  messaging_max_delivery_attempts       = var.messaging_max_delivery_attempts
  messaging_dlq_retention               = var.messaging_dlq_retention
  messaging_retry_min_backoff           = var.messaging_retry_min_backoff
  messaging_retry_max_backoff           = var.messaging_retry_max_backoff
  messaging_enable_alarms               = var.messaging_enable_alarms
  messaging_alarm_queue_depth_threshold = var.messaging_alarm_queue_depth_threshold
  messaging_alarm_message_age_threshold = var.messaging_alarm_message_age_threshold
  messaging_alarm_dlq_threshold         = var.messaging_alarm_dlq_threshold
  messaging_notification_channels       = var.messaging_notification_channels
}
