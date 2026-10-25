locals {
  name_prefix                         = "shifter-${var.environment}"
  dynamic_secret_project_id           = trimspace(var.dynamic_secret_project_id)
  dynamic_secret_project_is_dedicated = local.dynamic_secret_project_id != var.project_id
  normalized_public_hostname          = trimspace(trim(var.public_hostname, "."))
  # Management-source identity for per-range host management ingress and the
  # OpenVPN health probe (#1711 / ADR-039-R9). Narrowed to the provisioner pod
  # range: provisioner Jobs are pinned to the tainted provisioner node pool, so
  # this is the only platform source that drives range hosts. Participant SSH/RDP
  # is a separate rule sourced from access_network_cidrs (the access pod range),
  # never from this management source. Do not widen this back to the node subnet
  # or the broad default-pod range.
  portal_network_cidrs = compact([var.gke_provisioner_pods_cidr])
  access_network_cidrs = compact([var.gke_access_pods_cidr])
  # Full network topology (#1711 / ADR-039-R9): every statically-known GKE,
  # service, control-plane, and range CIDR must be canonical and mutually
  # disjoint. Overlap is computed as integer [start,end] range intersection
  # (version-safe: no cidrcontains, required_version is >= 1.5.0) and asserted
  # before apply by terraform_data.network_topology_invariant, so an invalid
  # environment fails deterministically rather than relying on provider
  # rejection as the first line of defense. private-service is auto-allocated by
  # google_compute_global_address, so its final range is provider-owned.
  topology_cidrs = {
    gke_subnet       = var.gke_subnet_cidr
    gke_pods         = var.gke_pods_cidr
    gke_services     = var.gke_services_cidr
    provisioner_pods = var.gke_provisioner_pods_cidr
    access_pods      = var.gke_access_pods_cidr
    control_plane    = var.gke_master_ipv4_cidr
    range_network    = var.range_network_cidr
    openvpn_pool     = var.openvpn_pool_subnet_cidr
  }
  topology_cidr_names = keys(local.topology_cidrs)
  topology_cidr_bounds = {
    for name, cidr in local.topology_cidrs : name => {
      start = (tonumber(split(".", cidrhost(cidr, 0))[0]) * 16777216
        + tonumber(split(".", cidrhost(cidr, 0))[1]) * 65536
        + tonumber(split(".", cidrhost(cidr, 0))[2]) * 256
      + tonumber(split(".", cidrhost(cidr, 0))[3]))
      end = (tonumber(split(".", cidrhost(cidr, 0))[0]) * 16777216
        + tonumber(split(".", cidrhost(cidr, 0))[1]) * 65536
        + tonumber(split(".", cidrhost(cidr, 0))[2]) * 256
        + tonumber(split(".", cidrhost(cidr, 0))[3])
      + pow(2, 32 - tonumber(split("/", cidr)[1])) - 1)
    }
  }
  # Index-based dedup: HCL `<` requires numbers, so compare positions in the
  # sorted key list rather than the string keys themselves.
  topology_cidr_overlaps = [
    for pair in setproduct(range(length(local.topology_cidr_names)), range(length(local.topology_cidr_names))) :
    "${local.topology_cidr_names[pair[0]]} (${local.topology_cidrs[local.topology_cidr_names[pair[0]]]}) overlaps ${local.topology_cidr_names[pair[1]]} (${local.topology_cidrs[local.topology_cidr_names[pair[1]]]})"
    if pair[0] < pair[1]
    && local.topology_cidr_bounds[local.topology_cidr_names[pair[0]]].start <= local.topology_cidr_bounds[local.topology_cidr_names[pair[1]]].end
    && local.topology_cidr_bounds[local.topology_cidr_names[pair[1]]].start <= local.topology_cidr_bounds[local.topology_cidr_names[pair[0]]].end
  ]
  identity_authorized_domains = distinct(compact([
    local.normalized_public_hostname,
    "${var.project_id}.firebaseapp.com",
    "localhost",
  ]))
  common_labels = merge(var.labels, {
    environment              = var.environment
    managed_by               = "terraform"
    project                  = "shifter"
    shifter_capacity_profile = var.shared_service_capacity_profile
  })

  artifact_repositories = toset([
    "portal",
    "guacd",
    "guacamole-client",
    "pulumi-provisioner",
    "openvpn",
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
    "db-provisioner"      = "Function-bound database connection bundle restricted to the provisioner launcher."
    "db-migration"        = "Schema-owner database connection bundle restricted to the migration workload."
    "guacamole-db"        = "Database connection secret bundle for the Guacamole client."
    "guacamole-json-auth" = "Guacamole JSON auth signing key."
    "redis"               = "Redis AUTH token for the platform control-plane cache (ADR-008-R6)."
    "dc-domain-password"  = "Prebaked Windows DC domain Administrator password applied per range (DC_DOMAIN_PASSWORD)."
  }, local.email_runtime_secrets)

  required_services = toset([
    # Default-on, keyless range model access (ADR-064): range guests call Vertex
    # publisher models directly via the attached predict-only range host SA.
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "binaryauthorization.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudfunctions.googleapis.com",
    "cloudkms.googleapis.com",
    "compute.googleapis.com",
    "connectgateway.googleapis.com",
    "container.googleapis.com",
    "gkeconnect.googleapis.com",
    "gkehub.googleapis.com",
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

module "dynamic_secret_project_services" {
  count  = local.dynamic_secret_project_is_dedicated ? 1 : 0
  source = "../project-services"

  project_id        = local.dynamic_secret_project_id
  required_services = toset(["secretmanager.googleapis.com"])
}

# Secret payload reads are not logged by default. Enable DATA_READ explicitly
# on the deployment-scoped secret project so participant, range-host, and
# provisioner reads have an auditable revocation trail.
module "dynamic_secret_data_access_audit" {
  source = "../project-audit-config"

  project_id = local.dynamic_secret_project_id
  service    = "secretmanager.googleapis.com"
  log_types  = ["DATA_READ"]

  depends_on = [module.dynamic_secret_project_services]
}

# #1711 / ADR-039-R9: fail deterministically before any cloud mutation when the
# GKE/service/control-plane/range CIDRs are not mutually disjoint. The access pod
# range is the GCE firewall's participant-access source identity, so an overlap
# with the provisioner/management, node, default-pod, service, control-plane, or
# range network would collapse the very isolation this issue establishes.
resource "terraform_data" "network_topology_invariant" {
  lifecycle {
    precondition {
      condition     = length(local.topology_cidr_overlaps) == 0
      error_message = "Network CIDRs must be mutually disjoint (#1711/ADR-039-R9). Overlaps: ${join("; ", local.topology_cidr_overlaps)}."
    }
  }
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
  gke_access_pods_cidr                      = var.gke_access_pods_cidr
  gke_pods_secondary_range_name             = var.gke_pods_secondary_range_name
  gke_services_secondary_range_name         = var.gke_services_secondary_range_name
  gke_provisioner_pods_secondary_range_name = var.gke_provisioner_pods_secondary_range_name
  gke_access_pods_secondary_range_name      = var.gke_access_pods_secondary_range_name
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
  range_network_zones        = var.range_network_zones
  nat_logs                   = var.range_telemetry.nat_logs

  depends_on = [module.project_services]
}

# #2535: Vertex AI Data Access audit logs. Range guests call Vertex publisher models
# in this project with the predict-only range host identity (ADR-064), so the audit
# configuration belongs to this project. This module is the only owner of the
# aiplatform.googleapis.com audit config here.
module "vertex_data_access_audit" {
  source = "../project-audit-config"

  project_id = var.project_id
  service    = "aiplatform.googleapis.com"
  log_types  = ["DATA_READ", "DATA_WRITE"]
  enabled    = var.range_telemetry.vertex_data_access_logs.enabled

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

  project_id                    = var.project_id
  region                        = var.region
  environment                   = var.environment
  common_labels                 = local.common_labels
  public_hostname               = local.normalized_public_hostname
  enable_gcs_usage_log_delivery = var.enable_gcs_usage_log_delivery
  force_destroy                 = var.gcs_force_destroy

  depends_on = [module.project_services]
}

module "portal_artifact_registry" {
  source = "../portal/artifact-registry"

  project_id                         = var.project_id
  artifact_registry_location         = var.artifact_registry_location
  name_prefix                        = local.name_prefix
  common_labels                      = local.common_labels
  artifact_repositories              = local.artifact_repositories
  environment                        = var.environment
  project_number                     = module.project_services.project_number
  release_scan_service_account_email = var.release_scan_service_account_email

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
  project_number                    = module.project_services.project_number

  depends_on = [module.project_services, module.portal_gcs]
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
  cloud_sql_iam_auth            = var.cloud_sql_iam_auth
  openfga_enabled               = var.openfga_enabled

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
  cloud_sql_runtime_user_name       = module.portal_cloud_sql.runtime_user_name
  cloud_sql_runtime_db_password     = module.portal_cloud_sql.runtime_db_password
  cloud_sql_provisioner_user_name   = module.portal_cloud_sql.provisioner_user_name
  cloud_sql_provisioner_db_password = module.portal_cloud_sql.provisioner_db_password
  cloud_sql_migration_user_name     = module.portal_cloud_sql.platform_user_name
  cloud_sql_migration_db_password   = module.portal_cloud_sql.db_password
  cloud_sql_guacamole_database_name = module.portal_cloud_sql.guacamole_database_name
  cloud_sql_guacamole_user_name     = module.portal_cloud_sql.guacamole_user_name
  cloud_sql_guacamole_db_password   = module.portal_cloud_sql.guacamole_db_password
  redis_auth_string                 = module.portal_redis.auth_string
  redis_server_ca_cert              = module.portal_redis.server_ca_cert

  depends_on = [module.project_services, module.portal_cloud_sql, module.portal_redis]
}

module "portal_iam" {
  model_broker = var.model_broker

  source = "../portal/iam"

  project_id                = var.project_id
  dynamic_secret_project_id = local.dynamic_secret_project_id
  environment               = var.environment
  name_prefix               = local.name_prefix
  cloud_sql_iam_auth        = var.cloud_sql_iam_auth
  cloud_sql_instance_name   = module.portal_cloud_sql.instance_name
  openfga_enabled           = var.openfga_enabled

  # ADR-008-R7: resource IDs from the owning modules so workload Secret Manager /
  # Cloud Storage access is bound per named resource instead of at project scope.
  runtime_secret_ids             = module.portal_secrets.runtime_secret_ids
  provisioner_static_secret_ids  = toset(values(var.provisioner_static_secret_refs))
  assets_bucket_name             = module.portal_gcs.assets_bucket_name
  terraform_state_bucket_name    = "${var.project_id}-terraform-state"
  vmseries_bootstrap_bucket_name = var.vmseries_bootstrap_bucket_name
  raes_package_bucket_name       = var.raes_package_bucket_name
  ctf_content_bucket_name        = var.ctf_content_bucket_name
  workload_identity_pool         = module.portal_gke.workload_identity_pool
  range_host_identity_pool_size  = var.range_host_identity_pool_size
  deploy_service_account_email   = var.deploy_service_account_email

  depends_on = [module.portal_secrets, module.portal_gcs, module.dynamic_secret_project_services]
}

# Shared participant OpenVPN server pool (#2480): deployed only when the tenant
# opts in to participant OpenVPN access.
module "vpn_pool" {
  source = "../vpn-pool"
  count  = var.openvpn_pool_enabled ? 1 : 0

  project_id                        = var.project_id
  region                            = var.region
  name_prefix                       = local.name_prefix
  common_labels                     = local.common_labels
  network_id                        = module.range_vpc.range_network_id
  network_name                      = module.range_vpc.range_network_name
  subnet_cidr                       = var.openvpn_pool_subnet_cidr
  range_network_cidr                = var.range_network_cidr
  public_hostname                   = local.normalized_public_hostname
  portal_ingress_ip                 = module.portal_ingress.public_ingress_ip_address
  artifact_registry_location        = var.artifact_registry_location
  artifact_repository               = module.portal_artifact_registry.artifact_registry_repositories["openvpn"]
  provisioner_service_account_email = module.portal_iam.workload_service_accounts["provisioner"]
  deploy_service_account_email      = var.deploy_service_account_email
  machine_type                      = var.openvpn_pool_machine_type
  min_vms                           = var.openvpn_pool_min_vms
  max_vms                           = var.openvpn_pool_max_vms
  cpu_target_pct                    = var.openvpn_pool_cpu_target_pct
  vpc_flow_logs                     = var.range_telemetry.vpc_flow_logs
  nat_logs                          = var.range_telemetry.nat_logs

  depends_on = [module.project_services]
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
  gke_access_pods_secondary_range_name      = var.gke_access_pods_secondary_range_name
  gke_master_ipv4_cidr                      = var.gke_master_ipv4_cidr
  gke_master_authorized_cidrs               = var.gke_master_authorized_cidrs
  gke_release_channel                       = var.gke_release_channel
  web_machine_type                          = var.web_machine_type
  worker_machine_type                       = var.worker_machine_type
  provisioner_machine_type                  = var.provisioner_machine_type
  access_machine_type                       = var.access_machine_type
  web_node_count                            = var.web_node_count
  worker_node_count                         = var.worker_node_count
  provisioner_node_count                    = var.provisioner_node_count
  access_node_count                         = var.access_node_count
  access_node_max_count                     = var.access_node_max_count
  node_service_account_email                = module.portal_iam.node_service_account_email

  # The cluster already orders after the node service account via the
  # node_service_account_email output reference above. It must NOT depend on the
  # whole portal_iam module: portal_iam creates the workload_identity SA bindings
  # whose member is PROJECT.svc.id.goog[...], which only exists once this
  # workload-identity-enabled cluster is created. Depending on the whole module
  # deadlocks a fresh project (cluster waits for bindings that wait for the
  # cluster). Instead, the bindings depend on the cluster through its
  # workload_identity_pool output, so a fresh project converges in one apply.
  depends_on = [module.project_services, module.portal_vpc]
}
