# SSM Module Variables
#
# Parameters for SSM documents and Parameter Store configuration
# used for portal deployment via lifecycle hooks and CI/CD.

variable "environment" {
  description = "Environment name (dev, prod)"
  type        = string
}

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "cloud_provider" {
  # Backend identity published to Parameter Store so the deploy script's
  # migrate/run containers receive the same CLOUD_PROVIDER the ASG boot path
  # sets (portal/ec2 user_data). Rendered from shifter.yaml's settings.backend
  # by shifter-config render-runtime; must not be hardcoded or defaulted here.
  description = "Backend identity for the portal container's CLOUD_PROVIDER env var"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
}

# ------------------------------------------------------------------------------
# ECR Configuration
# ------------------------------------------------------------------------------

variable "ecr_registry" {
  description = "ECR registry URL (e.g., 123456789.dkr.ecr.us-east-2.amazonaws.com)"
  type        = string
}

variable "ecr_repository_name" {
  description = "ECR repository name (e.g., shifter-dev-portal)"
  type        = string
}

variable "initial_image_tag" {
  description = "Initial image tag to deploy (updated by CI/CD)"
  type        = string
  default     = "latest"
}

# ------------------------------------------------------------------------------
# Secrets Manager ARNs
# ------------------------------------------------------------------------------

variable "db_secret_arn" {
  description = "ARN of database credentials secret"
  type        = string
}

variable "app_secret_arn" {
  description = "ARN of application secret"
  type        = string
}

variable "cognito_secret_arn" {
  description = "ARN of Cognito secret"
  type        = string
}

variable "guacamole_secret_arn" {
  description = "ARN of Guacamole JSON auth secret for RDP integration"
  type        = string
  default     = ""
}

variable "dc_domain_password_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the prebaked DC Administrator password. The portal Django container resolves this at startup (entrypoint.sh) to populate the DC_DOMAIN_PASSWORD env var used by Windows-DC RDP credential display."
  type        = string
  default     = ""
}

variable "guacamole_base_url" {
  description = "Public base URL for Guacamole (browser URL, e.g., https://domain.com/guacamole)"
  type        = string
  default     = ""
}

variable "guacamole_api_base_url" {
  description = "Internal base URL for Guacamole API calls (e.g., http://guacamole-client.internal:8080/guacamole)"
  type        = string
  default     = ""
}

# ------------------------------------------------------------------------------
# Application Configuration
# ------------------------------------------------------------------------------

variable "domain_name" {
  description = "Portal domain name for Django settings"
  type        = string
}

variable "s3_bucket_name" {
  description = "S3 bucket name for user storage"
  type        = string
}

variable "ctfd_platform_url" {
  description = "Public URL for the standalone CTFd platform"
  type        = string
  default     = ""
}

# ------------------------------------------------------------------------------
# Engine Provisioner Configuration
# ------------------------------------------------------------------------------

variable "engine_ecs_cluster_arn" {
  description = "ARN of ECS cluster for engine provisioner"
  type        = string
}

variable "engine_task_definition_family" {
  description = "ECS task definition family name for engine provisioner"
  type        = string
}

variable "engine_ecs_security_group_id" {
  description = "Security group ID for engine ECS tasks"
  type        = string
}

variable "engine_private_subnet_ids" {
  description = "Comma-separated list of private subnet IDs for engine ECS"
  type        = string
}

# ------------------------------------------------------------------------------
# Messaging Configuration
# ------------------------------------------------------------------------------

variable "sqs_cms_url" {
  description = "SQS queue URL for CMS worker"
  type        = string
}

variable "sqs_engine_url" {
  description = "SQS queue URL for Engine worker"
  type        = string
}

variable "sqs_mc_url" {
  description = "SQS queue URL for Mission Control worker"
  type        = string
}

variable "redis_endpoint" {
  description = "Redis endpoint for Django Channels (empty string if not using Redis)"
  type        = string
  default     = ""
}

variable "enable_redis" {
  description = "Whether to create the Redis endpoint SSM parameter. Avoids writing an empty string which SSM rejects."
  type        = bool
  default     = false
}

variable "redis_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the Redis AUTH token (#938). Non-secret reference only; the token itself never enters Parameter Store. Empty on the plaintext single-node path."
  type        = string
  default     = ""
}

variable "redis_tls" {
  description = "Whether the Redis channel-layer connection uses in-transit encryption + AUTH (#938). Drives the REDIS_TLS env var consumed by config/_channels.py."
  type        = bool
  default     = false
}

variable "redis_ca_mode" {
  description = "TLS trust mode for the Redis server certificate (#938): 'system' (AWS ElastiCache public Amazon CA via the OS trust store) or 'pem' (bundled CA in REDIS_CA_PEM). Consumed by config/_channels.py as REDIS_CA_MODE."
  type        = string
  default     = "system"
}

variable "db_host_override" {
  description = "Override database host. If empty, uses RDS host from secret."
  type        = string
  default     = ""
}

variable "enable_db_host_override" {
  description = "Whether to create the DB host override SSM parameter. Use this instead of testing db_host_override to avoid count depending on unknown values."
  type        = bool
  default     = false
}

variable "log_level" {
  description = "Django log level (DEBUG, INFO, WARNING, ERROR). Use DEBUG in dev for detailed event tracing."
  type        = string
  default     = "INFO"
}

variable "email_backend" {
  description = "Django email backend (e.g., django_ses.SESBackend)"
  type        = string
  default     = "django.core.mail.backends.console.EmailBackend"
}

variable "ctf_from_email" {
  description = "From address for CTF emails"
  type        = string
  default     = "ctf@example.com"
}

variable "range_events_topic_id" {
  description = "SNS topic ARN for range events (RANGE_EVENTS_TOPIC_ID). The outbox drainer and reconciler fail closed without it."
  type        = string
}

# ------------------------------------------------------------------------------
# ASG Lifecycle Hook Configuration
# ------------------------------------------------------------------------------

variable "lifecycle_hook_name" {
  description = "Name of the ASG lifecycle hook (empty if not using lifecycle hooks)"
  type        = string
  default     = ""
}

variable "asg_name" {
  description = "Name of the Auto Scaling Group (empty if single instance mode)"
  type        = string
  default     = ""
}

# ------------------------------------------------------------------------------
# Portal Runtime Capacity Tunables (#930)
# ------------------------------------------------------------------------------
# Non-secret integer knobs published to Parameter Store so the portal worker
# count and terminal-websocket caps/timeouts can be retuned without an image
# rebuild (update the parameter, then converge/restart the container).
#
# The terminal caps are process-local (one TerminalSessionRegistry per Gunicorn
# worker), so the real per-instance ceiling is:
#   per-instance cap = portal_web_workers * terminal_max_sessions
# Keep deployed values positive: a <= 0 terminal cap disables that limit in the
# app, which is a deliberate break-glass, not a steady-state posture, so the
# validations below reject it.

variable "portal_web_workers" {
  description = "Gunicorn/Uvicorn worker processes per portal instance (PORTAL_WEB_WORKERS). Size to the instance vCPU budget."
  type        = number
  default     = 4

  validation {
    condition     = var.portal_web_workers >= 1 && floor(var.portal_web_workers) == var.portal_web_workers
    error_message = "portal_web_workers must be a positive integer."
  }
}

variable "terminal_max_sessions" {
  description = "Active terminal SSH sessions per worker process (TERMINAL_MAX_SESSIONS). Per-instance cap = portal_web_workers * this."
  type        = number
  default     = 200

  validation {
    condition     = var.terminal_max_sessions >= 1 && floor(var.terminal_max_sessions) == var.terminal_max_sessions
    error_message = "terminal_max_sessions must be a positive integer (a <= 0 disable is a deliberate break-glass, not a deployed value)."
  }
}

variable "terminal_max_sessions_per_user" {
  description = "Active terminal SSH sessions per user, per worker process (TERMINAL_MAX_SESSIONS_PER_USER)."
  type        = number
  default     = 10

  validation {
    condition     = var.terminal_max_sessions_per_user >= 1 && floor(var.terminal_max_sessions_per_user) == var.terminal_max_sessions_per_user
    error_message = "terminal_max_sessions_per_user must be a positive integer."
  }
}

variable "terminal_idle_timeout_seconds" {
  description = "Close an idle terminal session after this many seconds (TERMINAL_IDLE_TIMEOUT_SECONDS)."
  type        = number
  default     = 1800

  validation {
    condition     = var.terminal_idle_timeout_seconds >= 1 && floor(var.terminal_idle_timeout_seconds) == var.terminal_idle_timeout_seconds
    error_message = "terminal_idle_timeout_seconds must be a positive integer."
  }
}

variable "terminal_max_session_seconds" {
  description = "Hard ceiling on a single terminal session's lifetime in seconds (TERMINAL_MAX_SESSION_SECONDS)."
  type        = number
  default     = 28800

  validation {
    condition     = var.terminal_max_session_seconds >= 1 && floor(var.terminal_max_session_seconds) == var.terminal_max_session_seconds
    error_message = "terminal_max_session_seconds must be a positive integer."
  }
}

variable "terminal_read_poll_seconds" {
  description = "How often an idle terminal read loop wakes to enforce timeouts (TERMINAL_READ_POLL_SECONDS). Does not bound output latency."
  type        = number
  default     = 30

  validation {
    condition     = var.terminal_read_poll_seconds >= 1 && floor(var.terminal_read_poll_seconds) == var.terminal_read_poll_seconds
    error_message = "terminal_read_poll_seconds must be a positive integer."
  }
}

# ------------------------------------------------------------------------------
# Portal web capacity metrics (#940)
# ------------------------------------------------------------------------------

variable "portal_capacity_metrics_enabled" {
  description = "Enable the per-worker Shifter/PortalCapacity metrics emitter (PORTAL_CAPACITY_METRICS_ENABLED). Enable in ASG-mode environments where the capacity alarms/dashboard exist."
  type        = bool
  default     = false
}

variable "portal_worker_soft_concurrency" {
  description = "Busy-ratio denominator: the soft concurrent in-flight HTTP request target per portal web worker (PORTAL_WORKER_SOFT_CONCURRENCY)."
  type        = number
  default     = 6

  validation {
    condition     = var.portal_worker_soft_concurrency >= 1 && floor(var.portal_worker_soft_concurrency) == var.portal_worker_soft_concurrency
    error_message = "portal_worker_soft_concurrency must be a positive integer."
  }
}
