variable "project_id" {
  description = "GCP project ID for gcp-dev."
  type        = string
}

variable "environment" {
  description = "Environment name."
  type        = string
  default     = "gcp-dev"
}

variable "region" {
  description = "Primary GCP region."
  type        = string
}

variable "artifact_registry_location" {
  description = "Artifact Registry location."
  type        = string
}

variable "gke_release_channel" {
  description = "GKE release channel."
  type        = string
  default     = "REGULAR"
}

variable "gke_subnet_cidr" {
  description = "Primary subnet CIDR for GKE nodes."
  type        = string
}

variable "gke_pods_cidr" {
  description = "Secondary range for GKE pods."
  type        = string
}

variable "gke_services_cidr" {
  description = "Secondary range for GKE services."
  type        = string
}

variable "gke_master_ipv4_cidr" {
  description = "Private control-plane CIDR for GKE."
  type        = string
}

variable "gke_master_authorized_cidrs" {
  description = "CIDR blocks allowed to reach the public GKE control-plane endpoint."
  type        = list(string)
  default     = []
}

variable "range_network_cidr" {
  description = "Base CIDR reserved for per-range subnet allocation."
  type        = string
}

variable "web_machine_type" {
  description = "Machine type for the web node pool."
  type        = string
  default     = "e2-standard-4"
}

variable "worker_machine_type" {
  description = "Machine type for the worker node pool."
  type        = string
  default     = "e2-standard-4"
}

variable "provisioner_machine_type" {
  description = "Machine type for the provisioner node pool."
  type        = string
  default     = "n2-standard-8"
}

variable "web_node_count" {
  description = "Desired size for the web node pool."
  type        = number
  default     = 1
}

variable "worker_node_count" {
  description = "Desired size for the worker node pool."
  type        = number
  default     = 1
}

variable "provisioner_node_count" {
  description = "Desired size for the provisioner node pool."
  type        = number
  default     = 1
}

variable "cloud_sql_database_version" {
  description = "Cloud SQL PostgreSQL version for the control-plane database."
  type        = string
  default     = "POSTGRES_15"
}

variable "cloud_sql_tier" {
  description = "Cloud SQL machine tier for the control-plane database."
  type        = string
  default     = "db-custom-1-3840"
}

variable "cloud_sql_availability_type" {
  description = "Cloud SQL availability type. Keep ZONAL in dev to reduce cost."
  type        = string
  default     = "ZONAL"

  validation {
    condition     = contains(["REGIONAL", "ZONAL"], var.cloud_sql_availability_type)
    error_message = "cloud_sql_availability_type must be either REGIONAL or ZONAL."
  }
}

variable "cloud_sql_disk_size_gb" {
  description = "Cloud SQL disk size in GiB."
  type        = number
  default     = 20
}

variable "cloud_sql_database_name" {
  description = "Default PostgreSQL database name for the control plane."
  type        = string
  default     = "shifter"
}

variable "cloud_sql_user_name" {
  description = "Application PostgreSQL username for the control plane."
  type        = string
  default     = "shifter"
}

variable "redis_tier" {
  description = "Memorystore tier for the control-plane Redis instance. STANDARD_HA is the default production high-availability posture; AUTH and TLS are enforced unconditionally by the platform-core module regardless of tier (ADR-008-R6)."
  type        = string
  default     = "STANDARD_HA"
}

variable "redis_memory_size_gb" {
  description = "Memorystore capacity in GiB."
  type        = number
  default     = 1
}

variable "public_hostname" {
  description = "Public hostname for the GKE ingress. Required: the portal runtime renders SITE_URL=https://<public_hostname> and fails closed without one."
  type        = string

  validation {
    condition     = length(trimspace(var.public_hostname)) > 0
    error_message = "public_hostname must be non-empty for the gcp-dev environment."
  }
}

variable "enable_managed_tls" {
  description = "Whether the GKE ingress uses a Google-managed certificate for the hostname. Required true: the portal serves over HTTPS only."
  type        = bool

  validation {
    condition     = var.enable_managed_tls
    error_message = "enable_managed_tls must be true for the gcp-dev environment; the portal serves over HTTPS only and the runtime renderer fails closed without managed TLS."
  }
}

variable "create_dns_managed_zone" {
  description = "Whether to create a Cloud DNS managed zone for the configured public hostname."
  type        = bool
  default     = false
}

variable "dns_managed_zone_name" {
  description = "Name of the Cloud DNS managed zone to create or update."
  type        = string
  default     = ""
}

variable "dns_zone_dns_name" {
  description = "DNS suffix for the optional Cloud DNS managed zone, for example 'example.com.'."
  type        = string
  default     = ""
}

variable "dns_record_ttl" {
  description = "TTL in seconds for the optional ingress A record. 300s is acceptable for dev; use 60s for production to enable fast failover."
  type        = number
  default     = 300
}

variable "identity_allowed_email_domain" {
  description = "Corporate email domain allowed to self-register in Identity Platform."
  type        = string
  default     = "paloaltonetworks.com"
}

variable "identity_allowed_emails" {
  description = "Explicit non-domain email addresses allowed to self-register in Identity Platform."
  type        = list(string)
  default     = []
}

variable "enable_identity_blocking_function" {
  description = <<-EOT
    Deploy the gen1 beforeCreate blocking function enforcing the sign-up domain
    allowlist at the Identity Platform layer. It requires an `allUsers` Cloud
    Functions invoker binding, which a Domain Restricted Sharing org policy
    forbids; set to false in such projects (the portal app still enforces the
    allowlist fail-closed at login).
  EOT
  type        = bool
  # gcp-dev runs under a Domain Restricted Sharing org policy that forbids the
  # required `allUsers` invoker binding, so the blocking function is disabled
  # here; the portal enforces the same allowlist fail-closed at session creation.
  default = false
}

# Transactional email (PLAT-002, #671). Optional: leave email_backend empty for
# the console fallback. When set, an unseeded ESP API-key Secret Manager secret
# is created for the operator to populate (never committed). See gcp/README.md.
variable "email_backend" {
  description = "Django EMAIL_BACKEND for GCP; empty = console fallback (no email secret created)."
  type        = string
  default     = ""
}

variable "email_from_address" {
  description = "DEFAULT_FROM_EMAIL for outbound mail when email_backend is set."
  type        = string
  default     = ""
}

variable "email_sender_domain" {
  description = "Mailgun sender domain (MAILGUN_SENDER_DOMAIN); ignored for SendGrid."
  type        = string
  default     = ""
}

# ------------------------------------------------------------------------------
# Range Egress (PLAT-220)
# ------------------------------------------------------------------------------

variable "range_egress_mode" {
  description = "Range egress policy mode (bridge for shifter.yaml settings.range_egress.mode). One of status-quo, deny-all, allowlist."
  type        = string
  default     = "status-quo"

  validation {
    condition     = contains(["status-quo", "deny-all", "allowlist"], var.range_egress_mode)
    error_message = "range_egress_mode must be one of: status-quo, deny-all, allowlist."
  }
}

variable "range_egress_allowed_cidrs" {
  description = "IP CIDR allowlist for range egress (bridge for shifter.yaml settings.range_egress.allowed_cidrs)."
  type        = list(string)
  default     = []
}

variable "github_org" {
  description = "GitHub organization allowed to federate into the packer build service account."
  type        = string
  default     = "Brad-Edwards"
}

variable "github_repo" {
  description = "GitHub repository allowed to federate into the packer build service account."
  type        = string
  default     = "shifter"
}

# ------------------------------------------------------------------------------
# Messaging DLQ / Retry / Alerting
# ------------------------------------------------------------------------------

variable "messaging_enable_dlq" {
  description = "Enable dead-letter topic and policy for platform event subscriptions."
  type        = bool
  default     = true
}

variable "messaging_max_delivery_attempts" {
  description = "Max delivery attempts before a message moves to the dead-letter topic (GCP minimum 5)."
  type        = number
  default     = 5
}

variable "messaging_dlq_retention" {
  description = "Message retention duration for the dead-letter subscription (e.g. '1209600s' = 14 days)."
  type        = string
  default     = "1209600s"
}

variable "messaging_retry_min_backoff" {
  description = "Minimum backoff for the subscription retry policy (e.g. '10s')."
  type        = string
  default     = "10s"
}

variable "messaging_retry_max_backoff" {
  description = "Maximum backoff for the subscription retry policy (e.g. '600s')."
  type        = string
  default     = "600s"
}

variable "messaging_enable_alarms" {
  description = "Enable Cloud Monitoring alert policies for event subscription monitoring."
  type        = bool
  default     = false
}

variable "messaging_alarm_queue_depth_threshold" {
  description = "Alert threshold for num_undelivered_messages on source subscriptions."
  type        = number
  default     = 100
}

variable "messaging_alarm_message_age_threshold" {
  description = "Alert threshold in seconds for oldest_unacked_message_age on source subscriptions."
  type        = number
  default     = 300
}

variable "messaging_alarm_dlq_threshold" {
  description = "Alert threshold for messages visible in the dead-letter subscription."
  type        = number
  default     = 1
}

variable "messaging_notification_channels" {
  description = "Cloud Monitoring notification channel resource IDs for messaging alerts."
  type        = list(string)
  default     = []
}
