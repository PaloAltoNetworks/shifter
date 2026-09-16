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
  # Deterministic emails of the purpose identities created in the foundational
  # global/cicd-oidc root. This root references them without importing state.
  build_service_account_email        = "${replace("shifter-${var.environment}", "-", "")}-packer@${var.project_id}.iam.gserviceaccount.com"
  release_scan_service_account_email = "${replace("shifter-${var.environment}", "-", "")}-scan@${var.project_id}.iam.gserviceaccount.com"
  deploy_service_account_email       = "${replace("shifter-${var.environment}", "-", "")}-deploy@${var.project_id}.iam.gserviceaccount.com"
  labels = {
    environment = var.environment
    managed_by  = "terraform"
    project     = "shifter"
  }
}

# Packer build-infra for the GCE image bakes (.github/workflows/packer-gcp.yml):
# the dedicated builder subnet, the IAP-scoped ingress firewall, and the GCS
# image bucket. It is network-coupled (needs the platform VPC + Cloud NAT), so it
# stays in the platform root. The GitHub Actions WIF pool/provider and the packer
# build service account it references now live in the foundational root
# platform/terraform/gcp/global/cicd-oidc so they survive a platform destroy (the
# credentials CI authenticates as). This references that SA by its deterministic
# email rather than creating it.
module "packer_build_infra" {
  source = "../../modules/packer-build-infra"

  project_id                   = var.project_id
  name_prefix                  = local.name_prefix
  region                       = var.region
  platform_network             = module.platform_core.network_name
  packer_service_account_email = local.build_service_account_email
  access_log_bucket_name       = module.platform_core.audit_logs_bucket_name
  # baremetal-gcr (GDC substrate SA) is absent on the default GCE backend; empty
  # unless a GDC deployment sets it (ADR: GDC plumbing must not be selected by
  # default). See the gdc_vm_runtime_image_readers variable.
  image_reader_service_accounts = var.gdc_vm_runtime_image_readers
}

module "platform_core" {
  model_broker = var.model_broker

  source = "../../modules/platform-core"

  project_id                         = var.project_id
  dynamic_secret_project_id          = var.dynamic_secret_project_id
  provisioner_static_secret_refs     = var.provisioner_static_secret_refs
  environment                        = var.environment
  region                             = var.region
  deploy_service_account_email       = local.deploy_service_account_email
  release_scan_service_account_email = local.release_scan_service_account_email
  artifact_registry_location         = var.artifact_registry_location
  gke_release_channel                = var.gke_release_channel
  range_network_cidr                 = var.range_network_cidr
  range_host_identity_pool_size      = var.range_host_identity_pool_size
  gke_subnet_cidr                    = var.gke_subnet_cidr
  gke_pods_cidr                      = var.gke_pods_cidr
  gke_services_cidr                  = var.gke_services_cidr
  gke_master_ipv4_cidr               = var.gke_master_ipv4_cidr
  gke_master_authorized_cidrs        = var.gke_master_authorized_cidrs
  web_machine_type                   = var.web_machine_type
  worker_machine_type                = var.worker_machine_type
  provisioner_machine_type           = var.provisioner_machine_type
  access_machine_type                = var.access_machine_type
  web_node_count                     = var.web_node_count
  worker_node_count                  = var.worker_node_count
  provisioner_node_count             = var.provisioner_node_count
  access_node_count                  = var.access_node_count
  cloud_sql_database_version         = var.cloud_sql_database_version
  cloud_sql_tier                     = var.cloud_sql_tier
  cloud_sql_availability_type        = var.cloud_sql_availability_type
  cloud_sql_disk_size_gb             = var.cloud_sql_disk_size_gb
  cloud_sql_database_name            = var.cloud_sql_database_name
  cloud_sql_user_name                = var.cloud_sql_user_name
  redis_tier                         = var.redis_tier
  redis_memory_size_gb               = var.redis_memory_size_gb
  public_hostname                    = var.public_hostname
  enable_managed_tls                 = var.enable_managed_tls
  create_dns_managed_zone            = var.create_dns_managed_zone
  dns_managed_zone_name              = var.dns_managed_zone_name
  dns_zone_dns_name                  = var.dns_zone_dns_name
  dns_record_ttl                     = var.dns_record_ttl
  identity_allowed_email_domain      = var.identity_allowed_email_domain
  identity_allowed_emails            = var.identity_allowed_emails
  enable_gcs_usage_log_delivery      = var.enable_gcs_usage_log_delivery
  enable_identity_blocking_function  = var.enable_identity_blocking_function
  email_backend                      = var.email_backend
  email_from_address                 = var.email_from_address
  email_sender_domain                = var.email_sender_domain
  range_egress_mode                  = var.range_egress_mode
  range_egress_allowed_cidrs         = var.range_egress_allowed_cidrs
  range_network_zones                = var.range_network_zones
  raes_package_bucket_name           = var.raes_package_bucket_name
  ctf_content_bucket_name            = var.ctf_content_bucket_name
  labels                             = local.labels

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
