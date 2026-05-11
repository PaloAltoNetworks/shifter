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
    "experiments",
  ])

  runtime_secrets = {
    "app"                 = "Django runtime secret bundle (SECRET_KEY and field encryption key)."
    "db"                  = "Database connection secret bundle for the platform control plane."
    "guacamole-db"        = "Database connection secret bundle for the Guacamole client."
    "guacamole-json-auth" = "Guacamole JSON auth signing key."
    "redis"               = "Redis AUTH token for the platform control-plane cache (ADR-008-R6)."
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
    "binaryauthorization.googleapis.com",
    "compute.googleapis.com",
    "container.googleapis.com",
    "identitytoolkit.googleapis.com",
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

  # Dedicated pod range for the provisioner node pool (ADR-008-R4, #959).
  # Provisioner pods get IPs from this range; the
  # range-allow-platform-provisioner firewall rule sources from this
  # narrow CIDR only, so other platform pods (portal, workers,
  # guacamole-client) cannot reach range VMs on the admin ports.
  secondary_ip_range {
    range_name    = var.gke_provisioner_pods_secondary_range_name
    ip_cidr_range = var.gke_provisioner_pods_cidr
  }

  depends_on = [google_project_service.required]
}

resource "google_compute_router" "nat" {
  name    = "${local.name_prefix}-nat"
  project = var.project_id
  region  = var.region
  network = google_compute_network.platform.id
}

resource "google_compute_address" "nat" {
  name         = "${local.name_prefix}-nat-egress"
  project      = var.project_id
  region       = var.region
  address_type = "EXTERNAL"
}

resource "google_compute_router_nat" "nat" {
  name                               = "${local.name_prefix}-nat"
  project                            = var.project_id
  region                             = var.region
  router                             = google_compute_router.nat.name
  nat_ip_allocate_option             = "MANUAL_ONLY"
  nat_ips                            = [google_compute_address.nat.self_link]
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

resource "google_compute_router" "range_nat" {
  name    = "${local.name_prefix}-range-nat"
  project = var.project_id
  region  = var.region
  network = google_compute_network.range.id
}

resource "google_compute_address" "range_nat" {
  name         = "${local.name_prefix}-range-nat-egress"
  project      = var.project_id
  region       = var.region
  address_type = "EXTERNAL"
}

resource "google_compute_router_nat" "range_nat" {
  name                               = "${local.name_prefix}-range-nat"
  project                            = var.project_id
  region                             = var.region
  router                             = google_compute_router.range_nat.name
  nat_ip_allocate_option             = "MANUAL_ONLY"
  nat_ips                            = [google_compute_address.range_nat.self_link]
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

# ------------------------------------------------------------------------------
# VPC firewall policy (ADR-008-R4, #959)
# ------------------------------------------------------------------------------
#
# Both the platform and range VPCs use custom networks (auto_create_subnetworks
# = false), so they inherit GCP's implicit-allow-internal-on-custom-VPC and
# implicit-deny-ingress baseline rather than the permissive
# default-network rules. These resources make the documented policy explicit:
#
# - Range VPC: deny-by-default on ingress; only an explicit
#   platform-provisioner allow rule (sourced from local.portal_network_cidrs)
#   reaches range VMs. Optional direct break-glass admin SSH is gated
#   on operator_admin_cidrs (direct-access source CIDRs at the VPC
#   firewall layer — these are NOT IAP TCP forwarding rules, which would
#   source from Google's 35.235.240.0/20 proxy range and are handled
#   via IAM / OS Login instead).
# - Platform VPC: explicit deny on world-open SSH/RDP, explicit allow for
#   Google LB health-check ranges to the GKE nodes (tag-scoped). No
#   broad "platform internal" catch-all — node-tag scoping keeps the
#   existing implicit-allow-internal behavior intact.
#
# Priorities: numerically lower priority = higher precedence (GCP convention).

# Range VPC — deny all external ingress as a low-precedence catch-all.
resource "google_compute_firewall" "range_deny_ingress_all" {
  name        = "${local.name_prefix}-range-deny-ingress-all"
  project     = var.project_id
  network     = google_compute_network.range.name
  description = "ADR-008-R4: range VPC ingress is denied by default; explicit allow rules ride higher precedence."
  direction   = "INGRESS"
  priority    = 65000

  source_ranges = ["0.0.0.0/0"]

  deny {
    protocol = "all"
  }
}

# Range VPC — allow the platform provisioner to reach range VMs on documented
# protocols only. Sourced from the dedicated provisioner pod CIDR
# (`var.gke_provisioner_pods_cidr`), not the shared platform pod range, so a
# compromised non-provisioner pod (portal, workers, guacamole-client) cannot
# satisfy this rule (ADR-008-R4, #959).
resource "google_compute_firewall" "range_allow_platform_provisioner" {
  name        = "${local.name_prefix}-range-allow-platform-provisioner"
  project     = var.project_id
  network     = google_compute_network.range.name
  description = "ADR-008-R4: provisioner-pod traffic (dedicated GKE pod range) into range VMs on documented ports only."
  direction   = "INGRESS"
  priority    = 1000

  source_ranges = [var.gke_provisioner_pods_cidr]

  allow {
    protocol = "tcp"
    ports    = [for p in var.range_provisioner_ports : tostring(p)]
  }
}

# Range VPC — optional direct break-glass admin SSH, gated on
# operator_admin_cidrs. Empty in dev, so the resource compiles to zero
# instances and no SSH rule lands. When set, the named CIDRs reach
# range VMs on port 22 directly; world-open CIDRs are rejected by
# variable validation. This rule is intentionally NOT named "iap" —
# IAP TCP forwarding presents traffic from Google's fixed proxy range
# (35.235.240.0/20), not from the operator workstation's public IP, so
# the source CIDRs here are operator-source CIDRs for direct admin
# access, not IAP traffic. IAP-based SSH onto these VPCs is handled
# via IAM / OS Login / bootstrap; if a future change adds a Terraform
# IAP firewall rule, it must source from the IAP TCP forwarding range
# and is a separate resource from this one.
resource "google_compute_firewall" "range_allow_operator_admin_ssh" {
  count = length(var.operator_admin_cidrs) > 0 ? 1 : 0

  name        = "${local.name_prefix}-range-allow-operator-admin-ssh"
  project     = var.project_id
  network     = google_compute_network.range.name
  description = "ADR-008-R4: break-glass direct SSH into range VMs from the operator-admin CIDR allowlist (not IAP)."
  direction   = "INGRESS"
  # Priority strictly higher (numerically lower) than the broad SSH/RDP
  # deny on the platform VPC and the deny-ingress-all (65000) on the
  # range VPC, so the allowlist actually opens SSH for the named CIDRs.
  priority = 800

  source_ranges = var.operator_admin_cidrs

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

# Platform VPC — explicit deny on world-open SSH/RDP. The platform VPC is
# private-cluster-only today, but this rule is an audit anchor: if a future
# resource accidentally exposes an external IP, the rule still blocks SSH/RDP.
resource "google_compute_firewall" "platform_deny_external_ssh_rdp" {
  name        = "${local.name_prefix}-platform-deny-external-ssh-rdp"
  project     = var.project_id
  network     = google_compute_network.platform.name
  description = "ADR-008-R4: SSH/RDP from 0.0.0.0/0 is never allowed into the platform VPC."
  direction   = "INGRESS"
  priority    = 900

  source_ranges = ["0.0.0.0/0"]

  deny {
    protocol = "tcp"
    ports    = ["22", "3389"]
  }
}

# Platform VPC — allow Google LB health-check sources to reach GKE nodes.
# These are the same CIDRs the bootstrap helm bridge sets in
# `gclbSourceRanges`; expressing them at the Terraform layer keeps the
# firewall policy auditable independent of the chart values.
resource "google_compute_firewall" "platform_allow_gke_health_checks" {
  name        = "${local.name_prefix}-platform-allow-gke-health-checks"
  project     = var.project_id
  network     = google_compute_network.platform.name
  description = "ADR-008-R4: Google LB health-check ranges reach GKE nodes; required for backend probes."
  direction   = "INGRESS"
  priority    = 1000

  source_ranges = [
    # Google Cloud Load Balancer health-check / proxy ranges.
    "35.191.0.0/16",
    "130.211.0.0/22",
  ]

  target_tags = ["gke"]

  allow {
    protocol = "tcp"
    # NodePort range probes plus common backend ports the platform exposes
    # behind the ingress (matches the existing portal/guacamole services).
    ports = ["80", "443", "8000", "8080", "30000-32767"]
  }
}

# Platform VPC — optional direct break-glass admin SSH onto GKE nodes,
# gated on operator_admin_cidrs. Empty in dev. Same direct-access (NOT
# IAP) semantics as range_allow_operator_admin_ssh; see that resource's
# header comment for why the rule is not named "iap".
resource "google_compute_firewall" "platform_allow_operator_admin_ssh" {
  count = length(var.operator_admin_cidrs) > 0 ? 1 : 0

  name        = "${local.name_prefix}-platform-allow-operator-admin-ssh"
  project     = var.project_id
  network     = google_compute_network.platform.name
  description = "ADR-008-R4: break-glass direct SSH onto GKE platform nodes from the operator-admin CIDR allowlist (not IAP)."
  direction   = "INGRESS"
  # Strictly higher precedence (lower number) than the broad
  # platform_deny_external_ssh_rdp (priority 900). At equal priority,
  # GCP gives deny rules precedence — the allow would be shadowed.
  priority = 800

  source_ranges = var.operator_admin_cidrs
  target_tags   = ["gke"]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
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

data "archive_file" "identity_platform_before_create" {
  type        = "zip"
  source_dir  = "${path.module}/functions/identity-platform"
  output_path = "${path.root}/.terraform/${local.name_prefix}-identity-platform-before-create.zip"
}

resource "google_storage_bucket_object" "identity_platform_before_create" {
  name   = "identity-platform/identity-platform-before-create-${data.archive_file.identity_platform_before_create.output_md5}.zip"
  bucket = google_storage_bucket.assets.name
  source = data.archive_file.identity_platform_before_create.output_path
}

resource "google_cloudfunctions_function" "identity_platform_before_create" {
  name                  = "${local.name_prefix}-identity-before-create"
  project               = var.project_id
  region                = var.region
  runtime               = "nodejs18"
  available_memory_mb   = 128
  timeout               = 10
  source_archive_bucket = google_storage_bucket.assets.name
  source_archive_object = google_storage_bucket_object.identity_platform_before_create.name
  trigger_http          = true
  entry_point           = "beforeCreate"

  environment_variables = {
    ALLOWED_EMAIL_DOMAIN = var.identity_allowed_email_domain
    ALLOWED_EMAILS       = join(",", var.identity_allowed_emails)
  }

  depends_on = [google_project_service.required]
}

resource "google_cloudfunctions_function_iam_member" "identity_platform_before_create_invoker" {
  project        = var.project_id
  region         = var.region
  cloud_function = google_cloudfunctions_function.identity_platform_before_create.name
  role           = "roles/cloudfunctions.invoker"
  member         = "allUsers"
}

resource "google_compute_global_address" "platform_ingress" {
  name    = "${local.name_prefix}-platform-ip"
  project = var.project_id
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

  blocking_functions {
    triggers {
      event_type   = "beforeCreate"
      function_uri = google_cloudfunctions_function.identity_platform_before_create.https_trigger_url
    }
  }

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
  special = true
}

resource "random_password" "django_secret_key" {
  length  = 64
  special = true
}

resource "random_id" "field_encryption_key" {
  byte_length = 32
}

resource "random_password" "guacamole_db_password" {
  length  = 32
  special = true
}

resource "random_id" "guacamole_json_auth_secret" {
  byte_length = 32
}

resource "google_sql_database_instance" "platform" {
  name             = "${local.name_prefix}-pg"
  project          = var.project_id
  region           = var.region
  database_version = var.cloud_sql_database_version
  # ADR-008 (#960): the platform Cloud SQL instance is durable control-plane
  # state. Deletion protection defaults to true on the module; environments
  # that genuinely need to tear the instance down can override via
  # var.cloud_sql_deletion_protection, but the secure default is preserved.
  deletion_protection = var.cloud_sql_deletion_protection

  settings {
    tier              = var.cloud_sql_tier
    availability_type = var.cloud_sql_availability_type
    disk_size         = var.cloud_sql_disk_size_gb
    disk_type         = "PD_SSD"

    # GCP exposes two deletion-protection surfaces (#960):
    # - `google_sql_database_instance.deletion_protection` (top-level) is
    #   Terraform's plan-time guard: `terraform destroy` is refused.
    # - `settings.deletion_protection_enabled` is the Cloud SQL API-level
    #   guard: Console / gcloud / direct API delete calls are refused.
    # Both need to be set or the protection is incomplete; we drive both
    # from the same input so the secure default applies on every surface.
    deletion_protection_enabled = var.cloud_sql_deletion_protection

    backup_configuration {
      enabled = true
    }

    ip_configuration {
      ipv4_enabled                                  = false
      private_network                               = google_compute_network.platform.id
      enable_private_path_for_google_cloud_services = true
      # Require TLS for every Cloud SQL connection. The google provider (>= 6.0) removed
      # the legacy ``require_ssl`` argument in favor of ``ssl_mode``; ``ENCRYPTED_ONLY``
      # is the server-TLS-required mode (client uses ``sslmode=verify-ca`` against the
      # Cloud SQL server CA — no mTLS).
      ssl_mode = "ENCRYPTED_ONLY"
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

  # ADR-008-R6 (#963): Memorystore runs with AUTH and server-side TLS.
  # The provider-generated auth_string is wired into Secret Manager
  # (`runtime_seeded["redis"]`) and hydrated by `entrypoint.sh`; it never
  # touches the runtime ConfigMap, generated env files, or process argv.
  auth_enabled            = true
  transit_encryption_mode = "SERVER_AUTHENTICATION"

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
    # Redis AUTH bundle (ADR-008-R6, #963). The provider-generated auth_string
    # is the secret field; the Memorystore server CA PEM is non-secret on its
    # own (it identifies the GCP-managed server cert, not a client credential)
    # but is delivered together with the password because Django Channels
    # needs it on the same hydration timeline to verify the server certificate
    # when negotiating SERVER_AUTHENTICATION TLS. Memorystore exposes the
    # TLS endpoint on a different port than plaintext (typically 6378) —
    # `google_redis_instance.platform.port` already returns the TLS port
    # when transit_encryption_mode is set, so render_runtime_env.py picks
    # it up via the existing `cache["port"]` field.
    redis = jsonencode({
      password       = google_redis_instance.platform.auth_string
      server_ca_cert = google_redis_instance.platform.server_ca_certs[0].cert
    })
  }

  secret      = google_secret_manager_secret.runtime[each.key].id
  secret_data = each.value
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

    # Declare the provisioner-only pod range as an additional pod range
    # available to node pools on this cluster. The provisioner node pool
    # opts into it via `network_config.pod_range` so its pods get IPs
    # from the dedicated range; web/worker pools continue to draw from
    # the default cluster_secondary_range_name (ADR-008-R4, #959).
    additional_pod_ranges_config {
      pod_range_names = [var.gke_provisioner_pods_secondary_range_name]
    }
  }

  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = false
    master_ipv4_cidr_block  = var.gke_master_ipv4_cidr
  }

  dynamic "master_authorized_networks_config" {
    for_each = length(var.gke_master_authorized_cidrs) == 0 ? [] : [1]

    content {
      dynamic "cidr_blocks" {
        for_each = var.gke_master_authorized_cidrs

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

  binary_authorization {
    evaluation_mode = "PROJECT_SINGLETON_POLICY_ENFORCE"
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

  # ADR-008-R4 (#959): the provisioner pool draws pod IPs from a
  # dedicated secondary range (declared on the GKE subnet and on the
  # cluster's ip_allocation_policy.additional_pod_ranges_config). The
  # range-VPC firewall sources only this CIDR for the
  # range-allow-platform-provisioner rule, so a compromised non-
  # provisioner pod elsewhere on the cluster cannot reach range VMs on
  # the admin ports.
  network_config {
    create_pod_range = false
    pod_range        = var.gke_provisioner_pods_secondary_range_name
  }

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
