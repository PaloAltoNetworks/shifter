locals {
  name_prefix                = "shifter-${var.environment}"
  normalized_public_hostname = trimspace(trim(var.public_hostname, "."))
  portal_network_cidrs       = compact([var.gke_subnet_cidr, var.gke_pods_cidr])
  identity_authorized_domains = distinct(compact([
    local.normalized_public_hostname,
    "${var.project_id}.firebaseapp.com",
    "localhost",
  ]))
  common_labels = merge(var.labels, {
    environment = var.environment
    managed_by  = "terraform"
    project     = "shifter"
  })

  artifact_repositories = toset([
    "portal",
    "guacd",
    "guacamole-client",
    "pulumi-provisioner",
  ])

  platform_event_subscriptions = toset([
    "cms",
    "engine",
    "mc",
  ])

  # Email is opt-in: the ESP API-key secret is created (unseeded, operator-
  # populated) only when email_backend is set (PLAT-002, #671). Unlike the other
  # bundles this one is NOT seeded by Terraform — the API key is never committed.
  email_runtime_secrets = var.email_backend == "" ? {} : {
    "email" = "Transactional-email ESP (SendGrid/Mailgun) API key; operator-populated, never seeded by Terraform."
  }

  runtime_secrets = merge({
    "app"                 = "Django runtime secret bundle (SECRET_KEY and field encryption key)."
    "db"                  = "Database connection secret bundle for the platform control plane."
    "guacamole-db"        = "Database connection secret bundle for the Guacamole client."
    "guacamole-json-auth" = "Guacamole JSON auth signing key."
    "redis"               = "Redis AUTH token for the platform control-plane cache (ADR-008-R6)."
  }, local.email_runtime_secrets)

  required_services = toset([
    "artifactregistry.googleapis.com",
    "binaryauthorization.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudfunctions.googleapis.com",
    "cloudkms.googleapis.com",
    "compute.googleapis.com",
    "container.googleapis.com",
    "identitytoolkit.googleapis.com",
    "monitoring.googleapis.com",
    "pubsub.googleapis.com",
    "redis.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "servicenetworking.googleapis.com",
    "sqladmin.googleapis.com",
    "storage.googleapis.com",
  ])
}

module "project_services" {
  source = "../project-services"

  project_id        = var.project_id
  required_services = local.required_services
}

module "portal_vpc" {
  source = "../portal/vpc"

  project_id                                = var.project_id
  region                                    = var.region
  name_prefix                               = local.name_prefix
  gke_subnet_cidr                           = var.gke_subnet_cidr
  gke_pods_cidr                             = var.gke_pods_cidr
  gke_services_cidr                         = var.gke_services_cidr
  gke_provisioner_pods_cidr                 = var.gke_provisioner_pods_cidr
  gke_pods_secondary_range_name             = var.gke_pods_secondary_range_name
  gke_services_secondary_range_name         = var.gke_services_secondary_range_name
  gke_provisioner_pods_secondary_range_name = var.gke_provisioner_pods_secondary_range_name
  private_service_range_prefix_length       = var.private_service_range_prefix_length
  operator_admin_cidrs                      = var.operator_admin_cidrs

  depends_on = [module.project_services]
}

module "range_vpc" {
  source = "../range/vpc"

  project_id                 = var.project_id
  region                     = var.region
  name_prefix                = local.name_prefix
  gke_provisioner_pods_cidr  = var.gke_provisioner_pods_cidr
  range_provisioner_ports    = var.range_provisioner_ports
  operator_admin_cidrs       = var.operator_admin_cidrs
  range_egress_mode          = var.range_egress_mode
  range_egress_allowed_cidrs = var.range_egress_allowed_cidrs

  depends_on = [module.project_services]
}

resource "google_compute_network_peering" "platform_to_range" {
  name         = "${local.name_prefix}-platform-to-range"
  network      = module.portal_vpc.platform_network_id
  peer_network = module.range_vpc.range_network_id
}

resource "google_compute_network_peering" "range_to_platform" {
  name         = "${local.name_prefix}-range-to-platform"
  network      = module.range_vpc.range_network_id
  peer_network = module.portal_vpc.platform_network_id

  depends_on = [google_compute_network_peering.platform_to_range]
}

module "portal_gcs" {
  source = "../portal/gcs"

  project_id    = var.project_id
  region        = var.region
  environment   = var.environment
  common_labels = local.common_labels

  depends_on = [module.project_services]
}

module "portal_artifact_registry" {
  source = "../portal/artifact-registry"

  project_id                 = var.project_id
  artifact_registry_location = var.artifact_registry_location
  name_prefix                = local.name_prefix
  common_labels              = local.common_labels
  artifact_repositories      = local.artifact_repositories
  environment                = var.environment
  project_number             = module.project_services.project_number

  depends_on = [module.project_services]
}

module "portal_ingress" {
  source = "../portal/ingress"

  project_id                 = var.project_id
  name_prefix                = local.name_prefix
  common_labels              = local.common_labels
  normalized_public_hostname = local.normalized_public_hostname
  create_dns_managed_zone    = var.create_dns_managed_zone
  dns_managed_zone_name      = var.dns_managed_zone_name
  dns_zone_dns_name          = var.dns_zone_dns_name
  dns_record_ttl             = var.dns_record_ttl
  environment                = var.environment

  depends_on = [module.project_services]
}

module "portal_messaging" {
  source = "../portal/messaging"

  project_id                   = var.project_id
  name_prefix                  = local.name_prefix
  common_labels                = local.common_labels
  platform_event_subscriptions = local.platform_event_subscriptions

  enable_dlq            = var.messaging_enable_dlq
  max_delivery_attempts = var.messaging_max_delivery_attempts
  dlq_retention         = var.messaging_dlq_retention
  retry_min_backoff     = var.messaging_retry_min_backoff
  retry_max_backoff     = var.messaging_retry_max_backoff

  enable_alarms               = var.messaging_enable_alarms
  alarm_queue_depth_threshold = var.messaging_alarm_queue_depth_threshold
  alarm_message_age_threshold = var.messaging_alarm_message_age_threshold
  alarm_dlq_threshold         = var.messaging_alarm_dlq_threshold
  notification_channels       = var.messaging_notification_channels

  depends_on = [module.project_services]
}

# The gen1 Identity Platform `beforeCreate` function is built by Cloud Build
# running as the project's default compute service account. New projects no
# longer auto-grant Editor to default service accounts
# (iam.automaticIamGrantsForDefaultServiceAccounts is off by default), so the
# build fails reading its `gcf-sources-*` bucket unless the build-worker role is
# granted explicitly. `roles/cloudbuild.builds.builder` bundles the source-read,
# logging, and Artifact Registry permissions a build needs. Only required when
# the blocking function is deployed.
resource "google_project_iam_member" "default_compute_cloud_build" {
  # checkov:skip=CKV_GCP_46:The gen1 Identity Platform beforeCreate function is built by Cloud Build, which runs as the project default compute SA on GCP; granting that SA the build-worker role is the minimal way to let the build read its gcf-sources bucket. Gated on enable_identity_blocking_function (off in projects that forbid it). See ADR-004-R11 exception (#615).
  # checkov:skip=CKV_GCP_49:roles/cloudbuild.builds.builder is the predefined build-worker role Cloud Build itself requires; the binding does not let the SA manage or impersonate other SAs beyond the Cloud Build agent it already runs as. Single project, gated grant. See ADR-004-R11 exception (#615).
  count   = var.enable_identity_blocking_function ? 1 : 0
  project = var.project_id
  role    = "roles/cloudbuild.builds.builder"
  member  = "serviceAccount:${module.project_services.project_number}-compute@developer.gserviceaccount.com"

  depends_on = [module.project_services]
}

module "portal_identity_platform" {
  source = "../portal/identity-platform"

  project_id                        = var.project_id
  region                            = var.region
  name_prefix                       = local.name_prefix
  identity_authorized_domains       = local.identity_authorized_domains
  identity_allowed_email_domain     = var.identity_allowed_email_domain
  identity_allowed_emails           = var.identity_allowed_emails
  assets_bucket_name                = module.portal_gcs.assets_bucket_name
  enable_identity_blocking_function = var.enable_identity_blocking_function

  depends_on = [module.project_services, module.portal_gcs, google_project_iam_member.default_compute_cloud_build]
}

module "portal_cloud_sql" {
  source = "../portal/cloud-sql"

  project_id                    = var.project_id
  region                        = var.region
  name_prefix                   = local.name_prefix
  common_labels                 = local.common_labels
  platform_network_id           = module.portal_vpc.platform_network_id
  cloud_sql_database_version    = var.cloud_sql_database_version
  cloud_sql_tier                = var.cloud_sql_tier
  cloud_sql_availability_type   = var.cloud_sql_availability_type
  cloud_sql_disk_size_gb        = var.cloud_sql_disk_size_gb
  cloud_sql_database_name       = var.cloud_sql_database_name
  cloud_sql_user_name           = var.cloud_sql_user_name
  cloud_sql_deletion_protection = var.cloud_sql_deletion_protection

  depends_on = [module.project_services, module.portal_vpc]
}

module "portal_redis" {
  source = "../portal/redis"

  project_id           = var.project_id
  region               = var.region
  name_prefix          = local.name_prefix
  environment          = var.environment
  common_labels        = local.common_labels
  platform_network_id  = module.portal_vpc.platform_network_id
  redis_tier           = var.redis_tier
  redis_memory_size_gb = var.redis_memory_size_gb

  depends_on = [module.project_services, module.portal_vpc]
}

module "portal_secrets" {
  source = "../portal/secrets"

  project_id                        = var.project_id
  name_prefix                       = local.name_prefix
  common_labels                     = local.common_labels
  runtime_secrets                   = local.runtime_secrets
  cloud_sql_private_ip              = module.portal_cloud_sql.private_ip_address
  cloud_sql_platform_database_name  = module.portal_cloud_sql.platform_database_name
  cloud_sql_platform_user_name      = module.portal_cloud_sql.platform_user_name
  cloud_sql_db_password             = module.portal_cloud_sql.db_password
  cloud_sql_guacamole_database_name = module.portal_cloud_sql.guacamole_database_name
  cloud_sql_guacamole_user_name     = module.portal_cloud_sql.guacamole_user_name
  cloud_sql_guacamole_db_password   = module.portal_cloud_sql.guacamole_db_password
  redis_auth_string                 = module.portal_redis.auth_string
  redis_server_ca_cert              = module.portal_redis.server_ca_cert

  depends_on = [module.project_services, module.portal_cloud_sql, module.portal_redis]
}

module "portal_iam" {
  source = "../portal/iam"

  project_id  = var.project_id
  environment = var.environment
  name_prefix = local.name_prefix
}

module "portal_gke" {
  source = "../portal/gke"

  project_id                                = var.project_id
  region                                    = var.region
  name_prefix                               = local.name_prefix
  common_labels                             = local.common_labels
  platform_network_id                       = module.portal_vpc.platform_network_id
  gke_subnetwork_id                         = module.portal_vpc.gke_subnetwork_id
  gke_pods_secondary_range_name             = var.gke_pods_secondary_range_name
  gke_services_secondary_range_name         = var.gke_services_secondary_range_name
  gke_provisioner_pods_secondary_range_name = var.gke_provisioner_pods_secondary_range_name
  gke_master_ipv4_cidr                      = var.gke_master_ipv4_cidr
  gke_master_authorized_cidrs               = var.gke_master_authorized_cidrs
  gke_release_channel                       = var.gke_release_channel
  web_machine_type                          = var.web_machine_type
  worker_machine_type                       = var.worker_machine_type
  provisioner_machine_type                  = var.provisioner_machine_type
  web_node_count                            = var.web_node_count
  worker_node_count                         = var.worker_node_count
  provisioner_node_count                    = var.provisioner_node_count
  node_service_account_email                = module.portal_iam.node_service_account_email

  depends_on = [module.project_services, module.portal_vpc, module.portal_iam]
}
