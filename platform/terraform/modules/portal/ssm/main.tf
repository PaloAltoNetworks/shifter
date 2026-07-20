# SSM Module - Portal Deployment
#
# Creates Parameter Store parameters for deployment configuration.
# These parameters are read by:
# - user_data.sh (ASG instance bootstrap)
# - CI/CD workflow inline deploy script

data "aws_caller_identity" "current" {}

locals {
  common_tags = merge(var.tags, {
    Module = "ssm"
  })

  # Parameter Store path prefix
  ps_prefix = "/shifter/${var.environment}/portal"

  # Django ENVIRONMENT value for the portal container. Mirrors
  # local.django_environment in the portal/ec2 module (which sets it on the
  # user_data boot path); the deploy script reads it from this parameter so
  # the deploy-time migrate/run sets the same ENVIRONMENT and
  # config.settings require_environment() does not fail closed (#948).
  # Keep the two mappings in sync.
  django_environment = (
    var.environment == "dev" ? "development" :
    var.environment == "prod" ? "production" :
    var.environment
  )
}

# ------------------------------------------------------------------------------
# Parameter Store - Deployment Configuration
# ------------------------------------------------------------------------------

resource "aws_ssm_parameter" "environment" {
  name        = "${local.ps_prefix}/environment"
  description = "Django ENVIRONMENT value for the portal container (config.settings)"
  type        = "String"
  value       = local.django_environment

  tags = local.common_tags
}

resource "aws_ssm_parameter" "cloud_provider" {
  name        = "${local.ps_prefix}/cloud-provider"
  description = "Backend identity for the portal container's CLOUD_PROVIDER env var (config._cloud.resolve_cloud_provider)"
  type        = "String"
  value       = var.cloud_provider

  tags = local.common_tags
}

resource "aws_ssm_parameter" "image_tag" {
  name        = "${local.ps_prefix}/image-tag"
  description = "Current Docker image tag for portal deployment"
  type        = "String"
  value       = var.initial_image_tag

  tags = local.common_tags

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "ecr_registry" {
  name        = "${local.ps_prefix}/ecr-registry"
  description = "ECR registry URL"
  type        = "String"
  value       = var.ecr_registry

  tags = local.common_tags
}

resource "aws_ssm_parameter" "ecr_repository" {
  name        = "${local.ps_prefix}/ecr-repository"
  description = "ECR repository name"
  type        = "String"
  value       = var.ecr_repository_name

  tags = local.common_tags
}

resource "aws_ssm_parameter" "domain_name" {
  name        = "${local.ps_prefix}/domain-name"
  description = "Portal domain name"
  type        = "String"
  value       = var.domain_name

  tags = local.common_tags
}

resource "aws_ssm_parameter" "s3_bucket" {
  name        = "${local.ps_prefix}/s3-bucket"
  description = "S3 bucket for user storage"
  type        = "String"
  value       = var.s3_bucket_name

  tags = local.common_tags
}

resource "aws_ssm_parameter" "db_secret_arn" {
  name        = "${local.ps_prefix}/db-secret-arn"
  description = "Database credentials secret ARN"
  type        = "String"
  value       = var.db_secret_arn

  tags = local.common_tags
}

resource "aws_ssm_parameter" "app_secret_arn" {
  name        = "${local.ps_prefix}/app-secret-arn"
  description = "Application secret ARN"
  type        = "String"
  value       = var.app_secret_arn

  tags = local.common_tags
}

resource "aws_ssm_parameter" "cognito_secret_arn" {
  name        = "${local.ps_prefix}/cognito-secret-arn"
  description = "Cognito secret ARN"
  type        = "String"
  value       = var.cognito_secret_arn

  tags = local.common_tags
}

resource "aws_ssm_parameter" "guacamole_secret_arn" {
  name        = "${local.ps_prefix}/guacamole-secret-arn"
  description = "Guacamole JSON auth secret ARN for RDP integration"
  type        = "String"
  value       = var.guacamole_secret_arn

  tags = local.common_tags
}

resource "aws_ssm_parameter" "dc_domain_password_secret_arn" {
  name        = "${local.ps_prefix}/dc-domain-password-secret-arn"
  description = "ARN of the Secrets Manager secret holding the prebaked DC Administrator password (resolved at portal startup)"
  type        = "String"
  value       = var.dc_domain_password_secret_arn

  tags = local.common_tags
}

resource "aws_ssm_parameter" "guacamole_base_url" {
  name        = "${local.ps_prefix}/guacamole-base-url"
  description = "Guacamole public URL for browser (e.g., https://domain.com/guacamole)"
  type        = "String"
  value       = var.guacamole_base_url

  tags = local.common_tags
}

resource "aws_ssm_parameter" "guacamole_api_base_url" {
  name        = "${local.ps_prefix}/guacamole-api-base-url"
  description = "Guacamole internal URL for API calls (e.g., http://guacamole-client.internal:8080/guacamole)"
  type        = "String"
  value       = var.guacamole_api_base_url

  tags = local.common_tags
}

# Engine SSM parameters
resource "aws_ssm_parameter" "engine_ecs_cluster_arn" {
  name        = "${local.ps_prefix}/engine-ecs-cluster-arn"
  description = "ECS cluster ARN for engine provisioner"
  type        = "String"
  value       = var.engine_ecs_cluster_arn

  tags = local.common_tags
}

resource "aws_ssm_parameter" "engine_task_definition_arn" {
  name        = "${local.ps_prefix}/engine-task-definition-arn"
  description = "ECS task definition family for engine provisioner"
  type        = "String"
  value       = var.engine_task_definition_family

  tags = local.common_tags
}

resource "aws_ssm_parameter" "engine_ecs_security_group_id" {
  name        = "${local.ps_prefix}/engine-ecs-security-group-id"
  description = "Security group ID for engine ECS tasks"
  type        = "String"
  value       = var.engine_ecs_security_group_id

  tags = local.common_tags
}

resource "aws_ssm_parameter" "engine_private_subnet_ids" {
  name        = "${local.ps_prefix}/engine-private-subnet-ids"
  description = "Private subnet IDs for engine ECS tasks"
  type        = "String"
  value       = var.engine_private_subnet_ids

  tags = local.common_tags
}

resource "aws_ssm_parameter" "sqs_cms_url" {
  name        = "${local.ps_prefix}/sqs-cms-url"
  description = "SQS queue URL for CMS worker"
  type        = "String"
  value       = var.sqs_cms_url

  tags = local.common_tags
}

resource "aws_ssm_parameter" "sqs_engine_url" {
  name        = "${local.ps_prefix}/sqs-engine-url"
  description = "SQS queue URL for Engine worker"
  type        = "String"
  value       = var.sqs_engine_url

  tags = local.common_tags
}

resource "aws_ssm_parameter" "sqs_mc_url" {
  name        = "${local.ps_prefix}/sqs-mc-url"
  description = "SQS queue URL for Mission Control worker"
  type        = "String"
  value       = var.sqs_mc_url

  tags = local.common_tags
}

resource "aws_ssm_parameter" "redis_endpoint" {
  count = var.enable_redis ? 1 : 0

  name        = "${local.ps_prefix}/redis-endpoint"
  description = "Redis endpoint for Django Channels"
  type        = "String"
  value       = var.redis_endpoint

  tags = local.common_tags
}

# Explicit channel-layer backend posture (ADR-018, #849). Always written with a
# non-empty value so the runtime is unambiguous and independent of whether the
# redis-endpoint write succeeded: a "redis" posture without a reachable endpoint
# makes Django fail closed at startup instead of silently using in-memory.
# Decoupled from enable_autoscaling — this is wiring posture, not compute topology.
resource "aws_ssm_parameter" "channel_layer_backend" {
  name        = "${local.ps_prefix}/channel-layer-backend"
  description = "Django Channels backend posture (redis | in_memory)"
  type        = "String"
  value       = var.enable_redis ? "redis" : "in_memory"

  tags = local.common_tags
}

# Redis AUTH + in-transit encryption wiring (#938). Written only when Redis is
# the active backend AND the secure path is enabled. These carry non-secret
# references and flags only: the AUTH token stays in Secrets Manager and is
# hydrated into REDIS_PASSWORD by entrypoint.sh, never via Parameter Store.
resource "aws_ssm_parameter" "redis_secret_arn" {
  count = var.enable_redis && var.redis_tls ? 1 : 0

  name        = "${local.ps_prefix}/redis-secret-arn"
  description = "ARN of the Secrets Manager secret holding the Redis AUTH token (resolved to REDIS_PASSWORD at portal startup)"
  type        = "String"
  value       = var.redis_secret_arn

  tags = local.common_tags
}

resource "aws_ssm_parameter" "redis_tls" {
  count = var.enable_redis && var.redis_tls ? 1 : 0

  name        = "${local.ps_prefix}/redis-tls"
  description = "Whether the Redis channel-layer connection uses in-transit encryption + AUTH (REDIS_TLS)"
  type        = "String"
  value       = "true"

  tags = local.common_tags
}

resource "aws_ssm_parameter" "redis_ca_mode" {
  count = var.enable_redis && var.redis_tls ? 1 : 0

  name        = "${local.ps_prefix}/redis-ca-mode"
  description = "TLS trust mode for the Redis server certificate (REDIS_CA_MODE): system | pem"
  type        = "String"
  value       = var.redis_ca_mode

  tags = local.common_tags
}

resource "aws_ssm_parameter" "db_host_override" {
  count = var.enable_db_host_override ? 1 : 0

  name        = "${local.ps_prefix}/db-host-override"
  description = "Database host override"
  type        = "String"
  value       = var.db_host_override

  tags = local.common_tags
}

resource "aws_ssm_parameter" "email_backend" {
  name        = "${local.ps_prefix}/email-backend"
  description = "Django email backend class"
  type        = "String"
  value       = var.email_backend

  tags = local.common_tags
}

resource "aws_ssm_parameter" "ctf_from_email" {
  name        = "${local.ps_prefix}/ctf-from-email"
  description = "From address for CTF emails"
  type        = "String"
  value       = var.ctf_from_email

  tags = local.common_tags
}

resource "aws_ssm_parameter" "range_events_topic_id" {
  name        = "${local.ps_prefix}/range-events-topic-id"
  description = "SNS topic ARN for range events (outbox drainer / reconciler publish target)"
  type        = "String"
  value       = var.range_events_topic_id

  tags = local.common_tags
}

resource "aws_ssm_parameter" "ctfd_platform_url" {
  count = var.ctfd_platform_url != "" ? 1 : 0

  name        = "${local.ps_prefix}/ctfd-platform-url"
  description = "Public URL for the standalone CTFd platform"
  type        = "String"
  value       = var.ctfd_platform_url

  tags = local.common_tags
}

# ------------------------------------------------------------------------------
# Parameter Store - Portal Runtime Capacity Tunables (#930)
# ------------------------------------------------------------------------------
# Non-secret integers read by both container hydration paths (user_data.sh on
# first boot, scripts/portal-deploy/deploy_portal.sh on SSM redeploy) and mapped
# 1:1 onto the matching Docker env var. Updating a value retunes the running
# fleet on the next converge/restart, with no image rebuild. Caps are
# process-local: per-instance cap = portal_web_workers * terminal_max_sessions.

resource "aws_ssm_parameter" "portal_web_workers" {
  name        = "${local.ps_prefix}/portal-web-workers"
  description = "Gunicorn/Uvicorn worker processes per portal instance (PORTAL_WEB_WORKERS), sized to instance vCPUs"
  type        = "String"
  value       = tostring(var.portal_web_workers)

  tags = local.common_tags
}

resource "aws_ssm_parameter" "terminal_max_sessions" {
  name        = "${local.ps_prefix}/terminal-max-sessions"
  description = "Terminal SSH sessions per worker process (TERMINAL_MAX_SESSIONS); per-instance cap = workers * this"
  type        = "String"
  value       = tostring(var.terminal_max_sessions)

  tags = local.common_tags
}

resource "aws_ssm_parameter" "terminal_max_sessions_per_user" {
  name        = "${local.ps_prefix}/terminal-max-sessions-per-user"
  description = "Terminal SSH sessions per user, per worker process (TERMINAL_MAX_SESSIONS_PER_USER)"
  type        = "String"
  value       = tostring(var.terminal_max_sessions_per_user)

  tags = local.common_tags
}

resource "aws_ssm_parameter" "terminal_idle_timeout_seconds" {
  name        = "${local.ps_prefix}/terminal-idle-timeout-seconds"
  description = "Idle terminal session timeout in seconds (TERMINAL_IDLE_TIMEOUT_SECONDS)"
  type        = "String"
  value       = tostring(var.terminal_idle_timeout_seconds)

  tags = local.common_tags
}

resource "aws_ssm_parameter" "terminal_max_session_seconds" {
  name        = "${local.ps_prefix}/terminal-max-session-seconds"
  description = "Hard ceiling on a terminal session lifetime in seconds (TERMINAL_MAX_SESSION_SECONDS)"
  type        = "String"
  value       = tostring(var.terminal_max_session_seconds)

  tags = local.common_tags
}

resource "aws_ssm_parameter" "terminal_read_poll_seconds" {
  name        = "${local.ps_prefix}/terminal-read-poll-seconds"
  description = "Idle terminal read-loop poll interval in seconds (TERMINAL_READ_POLL_SECONDS); does not bound output latency"
  type        = "String"
  value       = tostring(var.terminal_read_poll_seconds)

  tags = local.common_tags
}

# Portal web capacity metrics (#940). Read by both the first-boot user_data and
# the SSM-redeploy deploy_portal.sh hydration paths, like the #930 terminal
# tunables, so an operator can toggle the emitter or retune the busy-ratio
# denominator on a running fleet without an image rebuild.
resource "aws_ssm_parameter" "portal_capacity_metrics_enabled" {
  name        = "${local.ps_prefix}/portal-capacity-metrics-enabled"
  description = "Enable the per-worker Shifter/PortalCapacity metrics emitter (PORTAL_CAPACITY_METRICS_ENABLED): true|false"
  type        = "String"
  value       = tostring(var.portal_capacity_metrics_enabled)

  tags = local.common_tags
}

resource "aws_ssm_parameter" "portal_worker_soft_concurrency" {
  name        = "${local.ps_prefix}/portal-worker-soft-concurrency"
  description = "Busy-ratio denominator: soft concurrent-request target per portal web worker (PORTAL_WORKER_SOFT_CONCURRENCY)"
  type        = "String"
  value       = tostring(var.portal_worker_soft_concurrency)

  tags = local.common_tags
}
