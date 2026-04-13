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
  assets_bucket_cors_allowed_origins = distinct(compact(concat(
    local.normalized_public_hostname != "" ? ["https://${local.normalized_public_hostname}"] : [],
    var.asset_bucket_cors_allowed_origins,
  )))

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
    "ctfd"                = "CTFd VM runtime secret bundle (MariaDB passwords + CTFd SECRET_KEY)."
  }

  # Range image URLs are declared here but populated out-of-band by the
  # Packer build/promote pipeline (a new secret_version per image rotation),
  # not by Terraform. The provisioner reads these at range-create time via
  # main.get_gdc_image_url, mirroring the AWS SSM-backed get_ami_id contract
  # so an image rotation does not require a portal redeploy.
  range_image_secrets = {
    "range-image-kali"     = "Range VM Runtime image URL for Kali assets."
    "range-image-ubuntu"   = "Range VM Runtime image URL for Ubuntu victim assets."
    "range-image-windows"  = "Range VM Runtime image URL for Windows victim assets."
    "range-image-dc"       = "Range VM Runtime image URL for Windows domain controller assets."
    "range-image-vmseries" = "Range VM Runtime image URL for Palo Alto VM-Series NGFW assets."
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
    "compute.googleapis.com",
    "container.googleapis.com",
    "iamcredentials.googleapis.com",
    "identitytoolkit.googleapis.com",
    "logging.googleapis.com",
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

  dynamic "cors" {
    for_each = length(local.assets_bucket_cors_allowed_origins) > 0 ? [1] : []
    content {
      origin = local.assets_bucket_cors_allowed_origins
      method = ["GET", "HEAD", "PUT"]
      response_header = [
        "Content-Disposition",
        "Content-Length",
        "Content-Type",
        "ETag",
        "x-goog-generation",
        "x-goog-hash",
      ]
      max_age_seconds = 3600
    }
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

  # Identity Platform ID tokens are base64 + '.'-separated JWTs. The OWASP CRS
  # SQLi preconfigured ruleset at sensitivity 4 flags those characters as
  # quoted-string terminators (rule 942260 and adjacent) and denies the POST
  # to /auth/identity/session/ before it ever reaches Django. The session
  # exchange view accepts only a strict JSON body, parses it with json.loads,
  # and cryptographically verifies the token via firebase_admin — there is no
  # SQL interpolation anywhere on that code path, so the WAF rules add no real
  # protection and must be bypassed for this endpoint only.
  rule {
    action      = "allow"
    priority    = 900
    description = "Bypass WAF for Identity Platform session exchange (JWT body trips SQLi rules; the view verifies the token cryptographically)."

    match {
      expr {
        expression = "request.path == \"/auth/identity/session/\""
      }
    }
  }

  # Authenticated Shifter write surfaces POST JSON/YAML/form bodies with
  # user-authored filenames, scenario definitions, experiment metadata, and
  # similar content. At CRS sensitivity 4, the SQLi ruleset has already denied
  # legitimate requests on rule 942200 before they reached Django. These
  # endpoints still sit behind Django session auth, CSRF, strict request
  # parsing, and subsystem-specific validation, so the WAF adds noise rather
  # than protection on these narrow authenticated write paths.
  rule {
    action      = "allow"
    priority    = 905
    description = "Bypass WAF for authenticated Mission Control upload initiate (false-positive on SQLi rule 942200; Django enforces session, CSRF, and upload validation)."

    match {
      expr {
        expression = "request.path == \"/mission-control/api/upload/initiate/\""
      }
    }
  }

  rule {
    action      = "allow"
    priority    = 906
    description = "Bypass WAF for authenticated Mission Control upload completion (false-positive on SQLi rule 942200; Django enforces session, CSRF, and upload validation)."

    match {
      expr {
        expression = "request.path == \"/mission-control/api/upload/complete/\""
      }
    }
  }

  rule {
    action      = "allow"
    priority    = 907
    description = "Bypass WAF for authenticated Mission Control upload cancel (false-positive on SQLi rule 942200; Django enforces session, token validation, and cleanup)."

    match {
      expr {
        expression = "request.path == \"/mission-control/api/upload/cancel/\""
      }
    }
  }

  rule {
    action      = "allow"
    priority    = 910
    description = "Bypass WAF for authenticated Mission Control range launch (false-positive on SQLi rule 942200; Django enforces session, CSRF, and range validation)."

    match {
      expr {
        expression = "request.path == \"/mission-control/api/range/launch/\""
      }
    }
  }

  rule {
    action      = "allow"
    priority    = 911
    description = "Bypass WAF for authenticated Mission Control range cancel (false-positive on SQLi rule 942200; Django enforces session, CSRF, and range validation)."

    match {
      expr {
        expression = "request.path == \"/mission-control/api/range/cancel/\""
      }
    }
  }

  rule {
    action      = "allow"
    priority    = 912
    description = "Bypass WAF for authenticated Mission Control range destroy (false-positive on SQLi rule 942200; Django enforces session, CSRF, and range validation)."

    match {
      expr {
        expression = "request.path == \"/mission-control/api/range/destroy/\""
      }
    }
  }

  rule {
    action      = "allow"
    priority    = 913
    description = "Bypass WAF for authenticated Mission Control range pause (false-positive on SQLi rule 942200; Django enforces session, CSRF, and range validation)."

    match {
      expr {
        expression = "request.path == \"/mission-control/api/range/pause/\""
      }
    }
  }

  rule {
    action      = "allow"
    priority    = 914
    description = "Bypass WAF for authenticated Mission Control range resume (false-positive on SQLi rule 942200; Django enforces session, CSRF, and range validation)."

    match {
      expr {
        expression = "request.path == \"/mission-control/api/range/resume/\""
      }
    }
  }

  rule {
    action      = "allow"
    priority    = 915
    description = "Bypass WAF for authenticated Scenario Editor POST surfaces (false-positive on SQLi rule 942200; Django enforces session, CSRF, and scenario validation)."

    match {
      expr {
        expression = "request.method == \"POST\" && request.path.startsWith(\"/scenario-editor/\")"
      }
    }
  }

  rule {
    action      = "allow"
    priority    = 916
    description = "Bypass WAF for authenticated Experiments POST surfaces (false-positive on SQLi rule 942200; Django enforces session, CSRF, and experiment validation)."

    match {
      expr {
        expression = "request.method == \"POST\" && request.path.startsWith(\"/mission-control/experiments/\")"
      }
    }
  }

  rule {
    action      = "allow"
    priority    = 917
    description = "Bypass WAF for authenticated NGFW API POST surfaces (false-positive on SQLi rule 942200; Django enforces session, CSRF, and request validation)."

    match {
      expr {
        expression = "request.method == \"POST\" && request.path.startsWith(\"/mission-control/api/ngfw/\")"
      }
    }
  }

  rule {
    action      = "allow"
    priority    = 918
    description = "Bypass WAF for authenticated credentials API POST surfaces (false-positive on SQLi rule 942200; Django enforces session, CSRF, and credential validation)."

    match {
      expr {
        expression = "request.method == \"POST\" && request.path.startsWith(\"/mission-control/api/credentials/\")"
      }
    }
  }

  rule {
    action      = "allow"
    priority    = 919
    description = "Bypass WAF for authenticated Guacamole API POST surfaces (false-positive on SQLi rule 942200; Django enforces session and request validation)."

    match {
      expr {
        expression = "request.method == \"POST\" && request.path.startsWith(\"/mission-control/api/guacamole/\")"
      }
    }
  }

  rule {
    action      = "allow"
    priority    = 920
    description = "Bypass WAF for authenticated files POST surfaces (false-positive on SQLi rule 942200; Django enforces session, CSRF, and file validation)."

    match {
      expr {
        expression = "request.method == \"POST\" && request.path.startsWith(\"/mission-control/files/\")"
      }
    }
  }

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

  # This org forbids the public unauthenticated invocation that Identity
  # Platform blocking hooks require. The live deployment therefore enforces the
  # corporate allow-list, verified-email requirement, and enrolled-MFA
  # requirement during Django session exchange in
  # config/identity_platform.py::_assert_account_can_create_app_session.

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

resource "google_logging_metric" "identity_platform_user_created_count" {
  name        = "${local.name_prefix}_identity_platform_user_created_count"
  project     = var.project_id
  description = "Count of Identity Platform users first created in Django session exchange."
  filter = join(
    "\n",
    [
      "resource.type=\"k8s_container\"",
      "resource.labels.namespace_name=\"shifter-platform\"",
      "severity>=WARNING",
      "(textPayload:\"security.auth.user_created provider=identity_platform\" OR jsonPayload.message:\"security.auth.user_created provider=identity_platform\")",
    ],
  )

  depends_on = [google_project_service.required]
}

resource "google_monitoring_notification_channel" "identity_platform_user_created_email" {
  count        = var.monitoring_alert_email != "" ? 1 : 0
  project      = var.project_id
  display_name = "Identity Platform user creation alerts (${var.environment})"
  type         = "email"

  labels = {
    email_address = var.monitoring_alert_email
  }

  user_labels = local.common_labels

  depends_on = [google_project_service.required]
}

resource "time_sleep" "identity_platform_user_created_metric_propagated" {
  create_duration = "600s"

  depends_on = [google_logging_metric.identity_platform_user_created_count]
}

resource "google_monitoring_alert_policy" "identity_platform_user_created_rate" {
  project               = var.project_id
  display_name          = "Identity Platform user creation rate spike"
  combiner              = "OR"
  enabled               = true
  notification_channels = google_monitoring_notification_channel.identity_platform_user_created_email[*].name

  documentation {
    mime_type = "text/markdown"
    content   = "Triggers when the rate of newly created Identity Platform-backed Django users exceeds the expected threshold. Review Shifter auth logs and audit entries for unexpected self-registration volume."
  }

  conditions {
    display_name = "Identity Platform user creation rate > threshold"

    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.identity_platform_user_created_count.name}\" AND resource.type=\"k8s_container\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.identity_user_creation_rate_threshold
      duration        = "0s"

      aggregations {
        alignment_period     = var.identity_user_creation_rate_window
        per_series_aligner   = "ALIGN_DELTA"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = []
      }

      trigger {
        count = 1
      }
    }
  }

  user_labels = local.common_labels

  depends_on = [
    google_project_service.required,
    time_sleep.identity_platform_user_created_metric_propagated,
  ]
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

# Range image URL secrets. Declared empty; the Packer build/promote pipeline
# publishes new secret_versions as it rotates images. The provisioner reads
# the latest version on every range create via main.get_gdc_image_url, so no
# portal redeploy is needed when an image rotates. Access is granted via the
# existing project-level roles/secretmanager.secretAccessor on the
# provisioner workload identity service account.
resource "google_secret_manager_secret" "range_image" {
  for_each = local.range_image_secrets

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

resource "random_password" "ctfd_mariadb_root_password" {
  length  = 32
  special = false
}

resource "random_password" "ctfd_mariadb_user_password" {
  length  = 32
  special = false
}

resource "random_password" "ctfd_secret_key" {
  length  = 64
  special = false
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
    "ctfd" = jsonencode({
      mariadb_root_password = random_password.ctfd_mariadb_root_password.result
      mariadb_user_password = random_password.ctfd_mariadb_user_password.result
      secret_key            = random_password.ctfd_secret_key.result
    })
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

resource "google_service_account_iam_member" "portal_self_token_creator" {
  service_account_id = google_service_account.workload["portal"].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.workload["portal"].email}"
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

# ---------------------------------------------------------------------------
# CTFd VM
#
# Standalone Compute Engine host inside the portal VPC, sized to run the
# official CTFd docker-compose stack (ctfd gunicorn app, mariadb 10.11, redis,
# nginx). CTFd's official docs list 4 vCPU / 2 GiB RAM as the "recommended"
# minimum; we default to e2-standard-8 (8 vCPU, 32 GiB) and 100 GiB pd-ssd so
# MariaDB warm-cache + uploads + logs never become the bottleneck during a
# multi-hundred-user event.
#
# The VM terminates public HTTP/S directly on its ephemeral-but-reserved IP.
# Operator SSH is only open when ctfd_ssh_source_cidrs is set; otherwise the
# expected admin path is `gcloud compute ssh --tunnel-through-iap`.
# ---------------------------------------------------------------------------

resource "google_compute_subnetwork" "ctfd" {
  count = var.ctfd_enabled ? 1 : 0

  name                     = "${local.name_prefix}-ctfd"
  project                  = var.project_id
  region                   = var.region
  network                  = google_compute_network.platform.id
  ip_cidr_range            = var.ctfd_subnet_cidr
  private_ip_google_access = true

  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

resource "google_compute_address" "ctfd_public" {
  count = var.ctfd_enabled ? 1 : 0

  name         = "${local.name_prefix}-ctfd-ip"
  project      = var.project_id
  region       = var.region
  address_type = "EXTERNAL"
  network_tier = "PREMIUM"

  # Static IP anchors any DNS the operator may point at the CTFd host.
  lifecycle {
    prevent_destroy = true
  }
}

resource "google_compute_firewall" "ctfd_public_http_https" {
  count = var.ctfd_enabled ? 1 : 0

  name        = "${local.name_prefix}-ctfd-public-http-https"
  project     = var.project_id
  network     = google_compute_network.platform.name
  description = "Allow public inbound HTTP/S to the CTFd VM."
  direction   = "INGRESS"

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["ctfd-public"]

  allow {
    protocol = "tcp"
    ports    = ["80", "443"]
  }
}

resource "google_compute_firewall" "ctfd_admin_ssh" {
  count = var.ctfd_enabled && length(var.ctfd_ssh_source_cidrs) > 0 ? 1 : 0

  name        = "${local.name_prefix}-ctfd-admin-ssh"
  project     = var.project_id
  network     = google_compute_network.platform.name
  description = "Allow operator SSH to the CTFd VM from the configured admin CIDRs."
  direction   = "INGRESS"

  source_ranges = var.ctfd_ssh_source_cidrs
  target_tags   = ["ctfd-public"]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_compute_firewall" "ctfd_iap_ssh" {
  count = var.ctfd_enabled ? 1 : 0

  name        = "${local.name_prefix}-ctfd-iap-ssh"
  project     = var.project_id
  network     = google_compute_network.platform.name
  description = "Allow Identity-Aware Proxy to reach the CTFd VM on TCP/22 for `gcloud ssh --tunnel-through-iap`."
  direction   = "INGRESS"

  # Google IAP tunnel source range, documented at
  # https://cloud.google.com/iap/docs/using-tcp-forwarding.
  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["ctfd-public"]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_service_account" "ctfd" {
  count = var.ctfd_enabled ? 1 : 0

  project      = var.project_id
  account_id   = "${replace(local.name_prefix, "-", "")}-ctfd"
  display_name = "Shifter ${var.environment} CTFd VM"
}

resource "google_project_iam_member" "ctfd_logging" {
  count = var.ctfd_enabled ? 1 : 0

  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.ctfd[0].email}"
}

resource "google_project_iam_member" "ctfd_monitoring" {
  count = var.ctfd_enabled ? 1 : 0

  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.ctfd[0].email}"
}

resource "google_project_iam_member" "ctfd_artifact_registry_reader" {
  count = var.ctfd_enabled ? 1 : 0

  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.ctfd[0].email}"
}

# Scoped Secret Manager access: the CTFd VM can read only its own runtime
# secret bundle, not the broader Django / Guacamole / Cloud SQL bundles that
# live under the same runtime_secrets collection.
resource "google_secret_manager_secret_iam_member" "ctfd_secret_accessor" {
  count = var.ctfd_enabled ? 1 : 0

  project   = var.project_id
  secret_id = google_secret_manager_secret.runtime["ctfd"].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.ctfd[0].email}"
}

resource "google_compute_instance" "ctfd" {
  count = var.ctfd_enabled ? 1 : 0

  name         = "${local.name_prefix}-ctfd"
  project      = var.project_id
  zone         = "${var.region}-a"
  machine_type = var.ctfd_machine_type
  tags         = ["ctfd-public"]
  labels       = merge(local.common_labels, { role = "ctfd" })

  allow_stopping_for_update = true

  boot_disk {
    auto_delete = true
    initialize_params {
      image = var.ctfd_vm_image
      size  = var.ctfd_disk_size_gb
      type  = "pd-ssd"
    }
  }

  network_interface {
    network    = google_compute_network.platform.id
    subnetwork = google_compute_subnetwork.ctfd[0].id

    access_config {
      nat_ip       = google_compute_address.ctfd_public[0].address
      network_tier = "PREMIUM"
    }
  }

  service_account {
    email  = google_service_account.ctfd[0].email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_integrity_monitoring = true
    enable_vtpm                 = true
  }

  metadata = {
    enable-oslogin           = "TRUE"
    block-project-ssh-keys   = "TRUE"
    disable-legacy-endpoints = "TRUE"
  }

  # Bootstrap: install docker + compose v2, clone the official CTFd repo at
  # main, pull the Secret Manager runtime bundle to replace the stock compose's
  # hardcoded MariaDB credentials + SECRET_KEY, and bring the stack up so nginx
  # is serving on :80 by first boot. The override is written to
  # /opt/CTFd/docker-compose.override.yml so the base compose file stays
  # unmodified and `git pull && docker compose up -d` keeps working for future
  # CTFd upgrades. The startup script is idempotent via a marker file so a
  # reboot or instance resume does not double-clone or rotate secrets in place.
  metadata_startup_script = <<-EOT
    #!/usr/bin/env bash
    set -euxo pipefail

    export DEBIAN_FRONTEND=noninteractive
    MARKER=/var/lib/ctfd-bootstrap.done
    CTFD_SECRET_ID="${google_secret_manager_secret.runtime["ctfd"].secret_id}"
    PROJECT_ID="${var.project_id}"

    if [ -f "$${MARKER}" ]; then
      echo "ctfd bootstrap already completed"
      exit 0
    fi

    apt-get update
    apt-get install -y ca-certificates curl gnupg git jq

    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    . /etc/os-release
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $${VERSION_CODENAME} stable" \
      > /etc/apt/sources.list.d/docker.list

    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    # google-cloud-sdk is pre-installed on the google-provided Ubuntu LTS image
    # family under /snap/bin; fall back to the official apt package if gcloud
    # is not on PATH.
    if ! command -v gcloud >/dev/null 2>&1; then
      echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
        > /etc/apt/sources.list.d/google-cloud-sdk.list
      curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /etc/apt/keyrings/cloud.google.gpg
      apt-get update
      apt-get install -y google-cloud-cli
    fi

    systemctl enable --now docker

    install -d -m 0755 /opt
    if [ ! -d /opt/CTFd/.git ]; then
      git clone --depth=1 https://github.com/CTFd/CTFd.git /opt/CTFd
    fi

    # Fetch the CTFd runtime bundle from Secret Manager and write a
    # docker-compose override that replaces the stock hardcoded credentials.
    SECRET_JSON=$(gcloud secrets versions access latest \
      --secret="$${CTFD_SECRET_ID}" \
      --project="$${PROJECT_ID}")
    MARIADB_ROOT_PASSWORD=$(echo "$${SECRET_JSON}" | jq -r .mariadb_root_password)
    MARIADB_USER_PASSWORD=$(echo "$${SECRET_JSON}" | jq -r .mariadb_user_password)
    CTFD_SECRET_KEY=$(echo "$${SECRET_JSON}" | jq -r .secret_key)

    umask 077
    cat > /opt/CTFd/docker-compose.override.yml <<YAML
    services:
      ctfd:
        environment:
          - UPLOAD_FOLDER=/var/uploads
          - DATABASE_URL=mysql+pymysql://ctfd:$${MARIADB_USER_PASSWORD}@db/ctfd
          - REDIS_URL=redis://cache:6379
          - WORKERS=1
          - LOG_FOLDER=/var/log/CTFd
          - ACCESS_LOG=-
          - ERROR_LOG=-
          - REVERSE_PROXY=true
          - SECRET_KEY=$${CTFD_SECRET_KEY}
      db:
        environment:
          - MARIADB_ROOT_PASSWORD=$${MARIADB_ROOT_PASSWORD}
          - MARIADB_USER=ctfd
          - MARIADB_PASSWORD=$${MARIADB_USER_PASSWORD}
          - MARIADB_DATABASE=ctfd
          - MARIADB_AUTO_UPGRADE=1
    YAML
    chmod 600 /opt/CTFd/docker-compose.override.yml
    umask 022

    cd /opt/CTFd
    docker compose up -d --wait

    touch "$${MARKER}"
  EOT

  depends_on = [
    google_project_service.required,
    google_secret_manager_secret_version.runtime_seeded,
    google_secret_manager_secret_iam_member.ctfd_secret_accessor,
  ]
}
