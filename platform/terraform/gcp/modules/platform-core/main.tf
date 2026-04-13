locals {
  name_prefix                = "shifter-${var.environment}"
  normalized_public_hostname = trimspace(trim(var.public_hostname, "."))
  portal_network_cidrs       = compact([var.gke_subnet_cidr, var.gke_pods_cidr])
  identity_authorized_domains = distinct(compact([
    local.normalized_public_hostname,
    "${var.project_id}.firebaseapp.com",
    "localhost",
  ]))
  compute_default_service_account = "${data.google_project.project.number}-compute@developer.gserviceaccount.com"
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
    "experiments",
  ])

  runtime_secrets = {
    "app"                 = "Django runtime secret bundle (SECRET_KEY and field encryption key)."
    "db"                  = "Database connection secret bundle for the platform control plane."
    "guacamole-db"        = "Database connection secret bundle for the Guacamole client."
    "guacamole-json-auth" = "Guacamole JSON auth signing key."
  }

  workload_service_accounts = toset([
    "portal",
    "workers",
    "provisioner",
  ])

  workload_identity_members = {
    portal      = "serviceAccount:${var.project_id}.svc.id.goog[shifter-platform/portal]"
    workers     = "serviceAccount:${var.project_id}.svc.id.goog[shifter-platform/workers]"
    provisioner = "serviceAccount:${var.project_id}.svc.id.goog[shifter-jobs/provisioner]"
  }

  node_roles = toset([
    "roles/artifactregistry.reader",
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/stackdriver.resourceMetadata.writer",
  ])

  workload_roles = {
    portal = toset([
      "roles/firebaseauth.viewer",
      "roles/pubsub.publisher",
      "roles/secretmanager.secretAccessor",
      "roles/storage.objectAdmin",
    ])
    workers = toset([
      "roles/pubsub.publisher",
      "roles/pubsub.subscriber",
      "roles/secretmanager.secretAccessor",
      "roles/storage.objectViewer",
    ])
    provisioner = toset([
      "roles/pubsub.publisher",
      "roles/secretmanager.secretAccessor",
      "roles/storage.objectAdmin",
    ])
  }

  required_services = toset([
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudfunctions.googleapis.com",
    "compute.googleapis.com",
    "container.googleapis.com",
    "identitytoolkit.googleapis.com",
    "logging.googleapis.com",
    "pubsub.googleapis.com",
    "redis.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "servicenetworking.googleapis.com",
    "sqladmin.googleapis.com",
    "storage.googleapis.com",
  ])
}

resource "google_project_service" "required" {
  for_each = local.required_services

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "time_sleep" "required_services_propagated" {
  create_duration = "60s"

  depends_on = [google_project_service.required]
}

data "google_project" "project" {
  project_id = var.project_id
}

resource "google_project_service_identity" "identity_platform" {
  provider = google-beta
  project  = var.project_id
  service  = "identitytoolkit.googleapis.com"
}

resource "time_sleep" "identity_platform_service_agent_propagated" {
  create_duration = "60s"

  depends_on = [google_project_service_identity.identity_platform]
}

resource "google_project_iam_member" "cloud_run_builder" {
  project = var.project_id
  role    = "roles/run.builder"
  member  = "serviceAccount:${local.compute_default_service_account}"
}

resource "time_sleep" "cloud_run_builder_propagated" {
  create_duration = "90s"

  depends_on = [google_project_iam_member.cloud_run_builder]
}

resource "google_compute_network" "platform" {
  name                    = "${local.name_prefix}-platform"
  project                 = var.project_id
  auto_create_subnetworks = false
}

resource "google_compute_network" "range" {
  name                    = "${local.name_prefix}-range"
  project                 = var.project_id
  auto_create_subnetworks = false

  depends_on = [google_project_service.required]
}

resource "google_compute_subnetwork" "gke" {
  name                     = "${local.name_prefix}-gke"
  project                  = var.project_id
  region                   = var.region
  network                  = google_compute_network.platform.id
  ip_cidr_range            = var.gke_subnet_cidr
  private_ip_google_access = true

  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }

  secondary_ip_range {
    range_name    = var.gke_pods_secondary_range_name
    ip_cidr_range = var.gke_pods_cidr
  }

  secondary_ip_range {
    range_name    = var.gke_services_secondary_range_name
    ip_cidr_range = var.gke_services_cidr
  }

  depends_on = [google_project_service.required]
}

resource "google_compute_router" "nat" {
  name    = "${local.name_prefix}-nat"
  project = var.project_id
  region  = var.region
  network = google_compute_network.platform.id
}

resource "google_compute_router_nat" "nat" {
  name                               = "${local.name_prefix}-nat"
  project                            = var.project_id
  region                             = var.region
  router                             = google_compute_router.nat.name
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

resource "google_compute_router" "range_nat" {
  name    = "${local.name_prefix}-range-nat"
  project = var.project_id
  region  = var.region
  network = google_compute_network.range.id
}

resource "google_compute_router_nat" "range_nat" {
  name                               = "${local.name_prefix}-range-nat"
  project                            = var.project_id
  region                             = var.region
  router                             = google_compute_router.range_nat.name
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

resource "google_compute_network_peering" "platform_to_range" {
  name         = "${local.name_prefix}-platform-to-range"
  network      = google_compute_network.platform.id
  peer_network = google_compute_network.range.id
}

resource "google_compute_network_peering" "range_to_platform" {
  name         = "${local.name_prefix}-range-to-platform"
  network      = google_compute_network.range.id
  peer_network = google_compute_network.platform.id

  # GCP rejects concurrent peering operations touching the same networks.
  depends_on = [google_compute_network_peering.platform_to_range]
}

resource "google_compute_global_address" "services" {
  name          = "${local.name_prefix}-services"
  project       = var.project_id
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = var.private_service_range_prefix_length
  network       = google_compute_network.platform.id
}

resource "google_service_networking_connection" "services" {
  network                 = google_compute_network.platform.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.services.name]

  depends_on = [google_project_service.required]
}

resource "google_service_account" "gke_nodes" {
  project      = var.project_id
  account_id   = "${replace(local.name_prefix, "-", "")}nodes"
  display_name = "Shifter ${var.environment} GKE nodes"
}

resource "google_service_account" "workload" {
  for_each = local.workload_service_accounts

  project      = var.project_id
  account_id   = "${replace(local.name_prefix, "-", "")}-${each.key}"
  display_name = "Shifter ${var.environment} ${each.key}"
}

resource "google_artifact_registry_repository" "docker" {
  for_each = local.artifact_repositories

  project       = var.project_id
  location      = var.artifact_registry_location
  repository_id = "${local.name_prefix}-${each.key}"
  description   = "Docker images for ${each.key} in ${var.environment}"
  format        = "DOCKER"

  depends_on = [google_project_service.required]
}

resource "google_storage_bucket" "assets" {
  name                        = lower("${var.project_id}-${replace(var.environment, "_", "-")}-assets")
  project                     = var.project_id
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = local.common_labels

  versioning {
    enabled = true
  }

  logging {
    log_bucket        = google_storage_bucket.audit_logs.name
    log_object_prefix = "assets/"
  }

  depends_on = [google_project_service.required]
}

resource "google_storage_bucket" "audit_logs" {
  name                        = lower("${var.project_id}-${replace(var.environment, "_", "-")}-audit-logs")
  project                     = var.project_id
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = local.common_labels

  versioning {
    enabled = true
  }

  lifecycle_rule {
    action {
      type = "Delete"
    }

    condition {
      age = 30
    }
  }

  depends_on = [google_project_service.required]
}

data "archive_file" "identity_platform_hooks" {
  type        = "zip"
  source_dir  = "${path.module}/functions/identity-platform"
  output_path = "${path.root}/.terraform/${local.name_prefix}-identity-platform-hooks.zip"
  # Local `node --test` runs and CI lint steps drop a node_modules/ tree into
  # source_dir; Cloud Functions Gen2 re-runs npm install from package.json at
  # build time, so excluding local artifacts keeps the deploy zip deterministic
  # and small and prevents an accidentally stale local node_modules from
  # shadowing the pinned runtime dependency tree on GCP.
  excludes = [
    "node_modules",
    "node_modules/**",
    "package-lock.json",
  ]
}

resource "google_storage_bucket_object" "identity_platform_hooks" {
  name   = "identity-platform/identity-platform-hooks-${data.archive_file.identity_platform_hooks.output_md5}.zip"
  bucket = google_storage_bucket.assets.name
  source = data.archive_file.identity_platform_hooks.output_path
}

resource "google_cloudfunctions2_function" "identity_platform_before_create" {
  name        = "${local.name_prefix}-identity-before-create"
  project     = var.project_id
  location    = var.region
  description = "Identity Platform beforeCreate blocking function — enforces @${var.identity_allowed_email_domain} registrations."

  build_config {
    runtime     = "nodejs22"
    entry_point = "beforeCreate"

    source {
      storage_source {
        bucket = google_storage_bucket.assets.name
        object = google_storage_bucket_object.identity_platform_hooks.name
      }
    }
  }

  service_config {
    available_memory               = "128Mi"
    timeout_seconds                = 10
    ingress_settings               = "ALLOW_ALL"
    all_traffic_on_latest_revision = true

    environment_variables = {
      ALLOWED_EMAIL_DOMAIN = var.identity_allowed_email_domain
      ALLOWED_EMAILS       = join(",", var.identity_allowed_emails)
    }
  }

  depends_on = [
    time_sleep.required_services_propagated,
    time_sleep.cloud_run_builder_propagated,
  ]
}

# beforeSignIn is the second server-side gate. beforeCreate only fires on
# self-registration through the portal; a user seeded via the Firebase Console,
# Admin SDK, or bootstrap tooling bypasses that hook entirely. beforeSignIn
# re-evaluates the corporate allow-list on every authentication attempt so a
# stale or accidentally created non-PAN account cannot establish a session.
# The Django IdentityPlatformBackend is the third and authoritative layer.
resource "google_cloudfunctions2_function" "identity_platform_before_sign_in" {
  name        = "${local.name_prefix}-identity-before-sign-in"
  project     = var.project_id
  location    = var.region
  description = "Identity Platform beforeSignIn blocking function — re-enforces the corporate allow-list on every sign-in."

  build_config {
    runtime     = "nodejs22"
    entry_point = "beforeSignIn"

    source {
      storage_source {
        bucket = google_storage_bucket.assets.name
        object = google_storage_bucket_object.identity_platform_hooks.name
      }
    }
  }

  service_config {
    available_memory               = "128Mi"
    timeout_seconds                = 10
    ingress_settings               = "ALLOW_ALL"
    all_traffic_on_latest_revision = true

    environment_variables = {
      ALLOWED_EMAIL_DOMAIN = var.identity_allowed_email_domain
      ALLOWED_EMAILS       = join(",", var.identity_allowed_emails)
    }
  }

  depends_on = [
    time_sleep.required_services_propagated,
    time_sleep.cloud_run_builder_propagated,
  ]
}

resource "google_cloud_run_service_iam_member" "identity_platform_before_create_invoker" {
  project  = var.project_id
  location = var.region
  service  = google_cloudfunctions2_function.identity_platform_before_create.service_config[0].service
  role     = "roles/run.invoker"
  member   = google_project_service_identity.identity_platform.member

  depends_on = [time_sleep.identity_platform_service_agent_propagated]
}

resource "google_cloudfunctions2_function_iam_member" "identity_platform_before_create_invoker" {
  project        = var.project_id
  location       = var.region
  cloud_function = google_cloudfunctions2_function.identity_platform_before_create.name
  role           = "roles/cloudfunctions.invoker"
  member         = google_project_service_identity.identity_platform.member

  depends_on = [time_sleep.identity_platform_service_agent_propagated]
}

resource "google_cloud_run_service_iam_member" "identity_platform_before_sign_in_invoker" {
  project  = var.project_id
  location = var.region
  service  = google_cloudfunctions2_function.identity_platform_before_sign_in.service_config[0].service
  role     = "roles/run.invoker"
  member   = google_project_service_identity.identity_platform.member

  depends_on = [time_sleep.identity_platform_service_agent_propagated]
}

resource "google_cloudfunctions2_function_iam_member" "identity_platform_before_sign_in_invoker" {
  project        = var.project_id
  location       = var.region
  cloud_function = google_cloudfunctions2_function.identity_platform_before_sign_in.name
  role           = "roles/cloudfunctions.invoker"
  member         = google_project_service_identity.identity_platform.member

  depends_on = [time_sleep.identity_platform_service_agent_propagated]
}

# Identity Platform invokes blocking hooks through the public HTTPS function URL
# without attaching a caller credential, so the hooks themselves must allow
# unauthenticated invocation. The hook bodies reject non-corporate requests —
# the public allow is only a transport layer.
resource "google_cloud_run_service_iam_member" "identity_platform_before_create_public_invoker" {
  project  = var.project_id
  location = var.region
  service  = google_cloudfunctions2_function.identity_platform_before_create.service_config[0].service
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloudfunctions2_function_iam_member" "identity_platform_before_create_public_invoker" {
  project        = var.project_id
  location       = var.region
  cloud_function = google_cloudfunctions2_function.identity_platform_before_create.name
  role           = "roles/cloudfunctions.invoker"
  member         = "allUsers"
}

resource "google_cloud_run_service_iam_member" "identity_platform_before_sign_in_public_invoker" {
  project  = var.project_id
  location = var.region
  service  = google_cloudfunctions2_function.identity_platform_before_sign_in.service_config[0].service
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloudfunctions2_function_iam_member" "identity_platform_before_sign_in_public_invoker" {
  project        = var.project_id
  location       = var.region
  cloud_function = google_cloudfunctions2_function.identity_platform_before_sign_in.name
  role           = "roles/cloudfunctions.invoker"
  member         = "allUsers"
}

resource "google_compute_global_address" "platform_ingress" {
  name    = "${local.name_prefix}-platform-ip"
  project = var.project_id

  # External DNS (shifter.keplerops.com) is pinned to this IP. Releasing it
  # would force a new allocation, stranding DNS until someone re-points the
  # record and the ManagedCertificate re-provisions. Use
  # `terraform state rm` + targeted rebuild if an intentional replacement is
  # ever needed.
  lifecycle {
    prevent_destroy = true
  }
}

resource "google_compute_security_policy" "platform_edge" {
  name        = "${local.name_prefix}-edge"
  project     = var.project_id
  description = "Baseline Cloud Armor policy for the public Shifter ingress"

  rule {
    action      = "deny(403)"
    priority    = 1000
    description = "Block common SQL injection requests"

    match {
      expr {
        expression = "evaluatePreconfiguredWaf('sqli-v33-stable', {'sensitivity': 4, 'opt_out_rule_ids': ['owasp-crs-v030301-id942421-sqli']})"
      }
    }
  }

  rule {
    action      = "deny(403)"
    priority    = 1010
    description = "Block common cross-site scripting requests"

    match {
      expr {
        expression = "evaluatePreconfiguredWaf('xss-v33-stable')"
      }
    }
  }

  rule {
    action      = "allow"
    priority    = 2147483647
    description = "Default allow"

    match {
      versioned_expr = "SRC_IPS_V1"

      config {
        src_ip_ranges = ["*"]
      }
    }
  }
}

resource "google_dns_managed_zone" "platform" {
  count = var.create_dns_managed_zone ? 1 : 0

  name        = var.dns_managed_zone_name
  project     = var.project_id
  dns_name    = var.dns_zone_dns_name
  description = "Public DNS zone for ${var.environment}"
  labels      = local.common_labels

  dnssec_config {
    state = "on"
  }

  depends_on = [google_project_service.required]
}

resource "google_dns_record_set" "platform_ingress" {
  count = local.normalized_public_hostname != "" && var.dns_managed_zone_name != "" ? 1 : 0

  project      = var.project_id
  managed_zone = var.dns_managed_zone_name
  name         = "${local.normalized_public_hostname}."
  type         = "A"
  ttl          = var.dns_record_ttl
  rrdatas      = [google_compute_global_address.platform_ingress.address]

  depends_on = [google_dns_managed_zone.platform]
}

resource "google_pubsub_topic" "platform_events" {
  name    = "${local.name_prefix}-events"
  project = var.project_id
  labels  = local.common_labels

  depends_on = [google_project_service.required]
}

resource "google_pubsub_subscription" "platform_events" {
  for_each = local.platform_event_subscriptions

  name                       = "${local.name_prefix}-${each.key}"
  project                    = var.project_id
  topic                      = google_pubsub_topic.platform_events.name
  ack_deadline_seconds       = 20
  message_retention_duration = "604800s"
  labels                     = merge(local.common_labels, { worker = each.key })
}

resource "google_identity_platform_config" "platform" {
  project = var.project_id

  authorized_domains = local.identity_authorized_domains

  sign_in {
    allow_duplicate_emails = false

    anonymous {
      enabled = false
    }

    email {
      enabled           = true
      password_required = true
    }

    phone_number {
      enabled = false
    }
  }

  client {
    permissions {
      disabled_user_deletion = true
      disabled_user_signup   = false
    }
  }

  # Blocking functions run on the Identity Platform request path. beforeCreate
  # gates registration and beforeSignIn re-gates every authentication, so a
  # user seeded outside the portal (Admin SDK, Firebase Console, bootstrap
  # tooling) still gets evaluated against the corporate allow-list.
  #
  # The Terraform google_identity_platform_config schema does not currently
  # expose a "fail-closed on blocking function error" toggle (Identity Platform
  # defaults to fail-open for availability). The Django IdentityPlatformBackend
  # in config/identity_platform.py enforces the same allow-list at session
  # exchange time and is the authoritative gate; a blocking function outage
  # would at worst let a disallowed user reach Firebase but could not produce a
  # usable portal session.
  blocking_functions {
    triggers {
      event_type   = "beforeCreate"
      function_uri = google_cloudfunctions2_function.identity_platform_before_create.url
    }

    triggers {
      event_type   = "beforeSignIn"
      function_uri = google_cloudfunctions2_function.identity_platform_before_sign_in.url
    }
  }

  # MFA stays at state=ENABLED rather than MANDATORY. MANDATORY would force
  # every authentication to include a second factor, and Google's schema
  # description does not guarantee first-time-enrollment semantics for users
  # that still need to scan the TOTP QR. The portal's
  # _assert_account_can_create_app_session in config/identity_platform.py
  # enforces "no session without an enrolled factor" on the server, so MFA is
  # effectively required to reach any authenticated page even though Firebase
  # is only in ENABLED mode.
  mfa {
    state = "ENABLED"

    provider_configs {
      state = "ENABLED"

      totp_provider_config {
        adjacent_intervals = 1
      }
    }
  }

  monitoring {
    request_logging {
      enabled = true
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret" "runtime" {
  for_each = local.runtime_secrets

  project   = var.project_id
  secret_id = "${local.name_prefix}-${each.key}"
  labels    = local.common_labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "random_password" "db_password" {
  length  = 32
  special = false
}

resource "random_password" "django_secret_key" {
  length  = 64
  special = false
}

resource "random_id" "field_encryption_key" {
  byte_length = 32
}

resource "random_password" "guacamole_db_password" {
  length  = 32
  special = false
}

resource "random_id" "guacamole_json_auth_secret" {
  byte_length = 16
}

resource "google_sql_database_instance" "platform" {
  name                = "${local.name_prefix}-pg"
  project             = var.project_id
  region              = var.region
  database_version    = var.cloud_sql_database_version
  deletion_protection = false

  settings {
    tier              = var.cloud_sql_tier
    availability_type = "ZONAL"
    disk_size         = var.cloud_sql_disk_size_gb
    disk_type         = "PD_SSD"

    backup_configuration {
      enabled = true
    }

    ip_configuration {
      ipv4_enabled                                  = false
      private_network                               = google_compute_network.platform.id
      enable_private_path_for_google_cloud_services = true
    }

    database_flags {
      name  = "log_connections"
      value = "on"
    }

    user_labels = local.common_labels
  }

  depends_on = [
    google_project_service.required,
    google_service_networking_connection.services,
  ]
}

resource "google_sql_database" "platform" {
  name     = var.cloud_sql_database_name
  project  = var.project_id
  instance = google_sql_database_instance.platform.name
}

resource "google_sql_database" "guacamole" {
  name     = "guacamole"
  project  = var.project_id
  instance = google_sql_database_instance.platform.name
}

resource "google_sql_user" "platform" {
  name     = var.cloud_sql_user_name
  project  = var.project_id
  instance = google_sql_database_instance.platform.name
  password = random_password.db_password.result
}

resource "google_sql_user" "guacamole" {
  name     = "guacamole_admin"
  project  = var.project_id
  instance = google_sql_database_instance.platform.name
  password = random_password.guacamole_db_password.result
}

resource "google_redis_instance" "platform" {
  name               = "${local.name_prefix}-redis"
  project            = var.project_id
  region             = var.region
  tier               = var.redis_tier
  memory_size_gb     = var.redis_memory_size_gb
  authorized_network = google_compute_network.platform.id
  connect_mode       = "PRIVATE_SERVICE_ACCESS"
  display_name       = "Shifter ${var.environment} Redis"
  labels             = local.common_labels

  depends_on = [
    google_project_service.required,
    google_service_networking_connection.services,
  ]
}

resource "google_secret_manager_secret_version" "runtime_seeded" {
  for_each = {
    app = jsonencode({
      django_secret_key    = random_password.django_secret_key.result
      field_encryption_key = random_id.field_encryption_key.b64_url
    })
    db = jsonencode({
      host     = google_sql_database_instance.platform.private_ip_address
      port     = 5432
      dbname   = google_sql_database.platform.name
      username = google_sql_user.platform.name
      password = random_password.db_password.result
    })
    "guacamole-db" = jsonencode({
      host     = google_sql_database_instance.platform.private_ip_address
      port     = 5432
      dbname   = google_sql_database.guacamole.name
      username = google_sql_user.guacamole.name
      password = random_password.guacamole_db_password.result
    })
    "guacamole-json-auth" = random_id.guacamole_json_auth_secret.hex
  }

  secret      = google_secret_manager_secret.runtime[each.key].id
  secret_data = each.value
}

locals {
  gke_master_authorized_effective_cidrs = distinct(
    concat(var.gke_master_authorized_cidrs, var.gke_master_authorized_ci_cidrs)
  )
}

resource "google_container_cluster" "platform" {
  name     = "${local.name_prefix}-gke"
  project  = var.project_id
  location = var.region

  network    = google_compute_network.platform.id
  subnetwork = google_compute_subnetwork.gke.id

  deletion_protection      = false
  remove_default_node_pool = true
  initial_node_count       = 1

  networking_mode = "VPC_NATIVE"

  ip_allocation_policy {
    cluster_secondary_range_name  = var.gke_pods_secondary_range_name
    services_secondary_range_name = var.gke_services_secondary_range_name
  }

  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = false
    master_ipv4_cidr_block  = var.gke_master_ipv4_cidr
  }

  dynamic "master_authorized_networks_config" {
    for_each = length(local.gke_master_authorized_effective_cidrs) == 0 ? [] : [1]

    content {
      dynamic "cidr_blocks" {
        for_each = local.gke_master_authorized_effective_cidrs

        content {
          cidr_block   = cidr_blocks.value
          display_name = "admin-${replace(replace(cidr_blocks.value, "/", "-"), ".", "-")}"
        }
      }
    }
  }

  release_channel {
    channel = var.gke_release_channel
  }

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  logging_config {
    enable_components = ["SYSTEM_COMPONENTS", "WORKLOADS"]
  }

  monitoring_config {
    enable_components = ["SYSTEM_COMPONENTS"]
  }

  resource_labels = local.common_labels

  depends_on = [
    google_project_service.required,
    google_service_networking_connection.services,
  ]
}

resource "google_container_node_pool" "web" {
  name       = "${local.name_prefix}-web"
  project    = var.project_id
  location   = var.region
  cluster    = google_container_cluster.platform.name
  node_count = var.web_node_count

  node_config {
    machine_type    = var.web_machine_type
    service_account = google_service_account.gke_nodes.email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    labels          = merge(local.common_labels, { role = "web" })
    tags            = ["shifter", "gke", "web"]

    metadata = {
      disable-legacy-endpoints = "true"
    }

    shielded_instance_config {
      enable_secure_boot          = true
      enable_integrity_monitoring = true
    }
  }
}

resource "google_project_iam_member" "node_roles" {
  for_each = local.node_roles

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.gke_nodes.email}"
}

resource "google_project_iam_member" "workload_roles" {
  for_each = merge([
    for account_name, roles in local.workload_roles : {
      for role in roles : "${account_name}:${role}" => {
        account_name = account_name
        role         = role
      }
    }
  ]...)

  project = var.project_id
  role    = each.value.role
  member  = "serviceAccount:${google_service_account.workload[each.value.account_name].email}"
}

resource "google_service_account_iam_member" "workload_identity" {
  for_each = local.workload_identity_members

  service_account_id = google_service_account.workload[each.key].name
  role               = "roles/iam.workloadIdentityUser"
  member             = each.value
}

resource "google_container_node_pool" "workers" {
  name       = "${local.name_prefix}-workers"
  project    = var.project_id
  location   = var.region
  cluster    = google_container_cluster.platform.name
  node_count = var.worker_node_count

  node_config {
    machine_type    = var.worker_machine_type
    service_account = google_service_account.gke_nodes.email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    labels          = merge(local.common_labels, { role = "workers" })
    tags            = ["shifter", "gke", "workers"]

    metadata = {
      disable-legacy-endpoints = "true"
    }

    shielded_instance_config {
      enable_secure_boot          = true
      enable_integrity_monitoring = true
    }
  }
}

resource "google_container_node_pool" "provisioner" {
  name       = "${local.name_prefix}-provisioner"
  project    = var.project_id
  location   = var.region
  cluster    = google_container_cluster.platform.name
  node_count = var.provisioner_node_count

  node_config {
    machine_type    = var.provisioner_machine_type
    service_account = google_service_account.gke_nodes.email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    labels          = merge(local.common_labels, { role = "provisioner" })
    tags            = ["shifter", "gke", "provisioner"]

    metadata = {
      disable-legacy-endpoints = "true"
    }

    shielded_instance_config {
      enable_secure_boot          = true
      enable_integrity_monitoring = true
    }
  }
}
