# terraform.tfvars — committed example.com baseline for OSS deployers.
# This file IS `terraform.tfvars` (committed). Deployment-specific overrides go in
# a sibling `local.auto.tfvars` (gitignored) — Terraform auto-loads
# `*.auto.tfvars` and the local values win. CI deploys render the overrides
# from GitHub secrets; see docs/dev/deploy-secrets.md.


# ------------------------------------------------------------------------------
# General
# ------------------------------------------------------------------------------

environment        = "prod"
aws_region         = "us-east-2"
log_retention_days = 365

tags = {
  Project     = "shifter"
  Environment = "prod"
  ManagedBy   = "terraform"
}

# ------------------------------------------------------------------------------
# VPC
# ------------------------------------------------------------------------------

vpc_cidr = "10.0.0.0/16"

# CIDR of the EKS control-plane VPC (must match the eks root vpc_cidr; disjoint
# from vpc_cidr + range). Portal app/provisioner run as EKS pods reaching RDS/Redis
# over the portal<->EKS peering.
eks_vpc_cidr       = "10.80.0.0/16"
az_count           = 2
enable_nat_gateway = true

# ------------------------------------------------------------------------------
# RDS
# ------------------------------------------------------------------------------

db_name                  = "shifter"
db_username              = "shifter_admin"
db_engine_version        = "16"
db_instance_class        = "db.t3.large"
db_allocated_storage     = 20
db_max_allocated_storage = 100
db_multi_az              = true
db_backup_retention_days = 7
db_deletion_protection   = true
db_skip_final_snapshot   = false
db_apply_immediately     = false

# ------------------------------------------------------------------------------
# EC2
# ------------------------------------------------------------------------------

# Standard AL2023 AMI (NOT ECS-optimized) - us-east-2
# Portal runtime capacity tunables (#930). t3.xlarge has 4 vCPUs, so the
# Gunicorn/Uvicorn pool is 4 workers. Terminal caps are process-local;
# per-instance terminal ceiling = portal_web_workers * terminal_max_sessions =
# 4 * 200 = 800 sessions.
portal_web_workers             = 4
terminal_max_sessions          = 200
terminal_max_sessions_per_user = 10
terminal_idle_timeout_seconds  = 1800
terminal_max_session_seconds   = 28800
terminal_read_poll_seconds     = 30

# ------------------------------------------------------------------------------
# ALB
# ------------------------------------------------------------------------------

domain_name = "shifter.example.com"
# ------------------------------------------------------------------------------
# Cognito
# ------------------------------------------------------------------------------

cognito_domain_prefix = "shifter-portal"
# REPLACE: the email domains permitted to self-register via Cognito pre-signup.
# Leaving this empty fails closed — no domain-wide self-signup. Add only domains
# your tenancy owns; do NOT ship a third-party domain in an example.
allowed_email_domains = []
allowed_emails        = []

# ------------------------------------------------------------------------------
# S3
# ------------------------------------------------------------------------------

# REPLACE: your S3 bucket name for user-uploaded artifacts.
user_storage_bucket = "shifter-user-storage-REPLACE_WITH_ACCOUNT_ID"

# ------------------------------------------------------------------------------
# Provisioner
# ------------------------------------------------------------------------------

# AMI IDs are now managed via SSM Parameter Store (/shifter/ami/*)
# See shifter/packer/ for AMI build configuration

# ------------------------------------------------------------------------------
# Autoscaling
# ------------------------------------------------------------------------------

# Portal app-saturation autoscaling + observability (#940). prod runs the ASG,
# so scale-out tracks ALB request-path saturation (RequestCountPerTarget +
# TargetResponseTime) and the additive worker-busy-ratio scale-out; the app
# emitter is enabled so the PortalCapacity alarms/dashboard have a live series.
# portal_web_workers = 4 here, so soft concurrency 8 ~ 2x the ~4-request baseline.
portal_capacity_metrics_enabled = true
portal_worker_soft_concurrency  = 8
# Channel-layer backend (ADR-018, #849), decoupled from autoscaling above.
# Prod runs the portal on Redis (CHANNEL_LAYER_BACKEND=redis), as before.
enable_redis = true

# ------------------------------------------------------------------------------
# Redis
# ------------------------------------------------------------------------------

redis_node_type          = "cache.t3.medium"
redis_engine_version     = "7.1"
redis_enable_replication = true
redis_apply_immediately  = false

# ------------------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------------------

log_level = "INFO"

# ------------------------------------------------------------------------------
# Log Aggregation
# ------------------------------------------------------------------------------

# Disabled for initial deployment - enable when ready for XDR integration
# Enabled so portal Network Firewall FLOW / ALERT logs reach the existing
# CloudWatch -> Firehose -> S3 / SQS pipeline (#122 fail-closed contract).
enable_log_aggregation = true

# ------------------------------------------------------------------------------
# Phase 5: Additional Log Sources
# ------------------------------------------------------------------------------

enable_alb_access_logs = false
enable_vpc_flow_logs   = true
enable_rds_log_exports = true
enable_waf_logging     = true

# ------------------------------------------------------------------------------
# Portal east-west inspection (#122)
# ------------------------------------------------------------------------------

# Default-off baseline (#932). Enabling inspection removes the direct
# private->NAT default route, so a misconfigured firewall endpoint blackholes
# egress. A deploy opts in via the TF_VARS_*_PORTAL secret (local.auto.tfvars);
# the post-apply assertion (scripts/assert_portal_inspection) then fails the
# deploy if the route/endpoint wiring is unhealthy instead of shipping a
# blackhole.
enable_portal_inspection    = false
firewall_log_retention_days = 365

# prod: secure default; flip false + apply before any intentional destroy
portal_inspection_delete_protection = true

# ------------------------------------------------------------------------------
# Engine Provisioner
# ------------------------------------------------------------------------------

# Windows/DC AMIs also managed via SSM Parameter Store

# Domain Controller Administrator password is sourced from
# aws_secretsmanager_secret.dc_domain_password (engine-provisioner module)
# at runtime; the value is managed out-of-band and is intentionally not
# present in Terraform configuration. See
# shifter/shifter_platform/documentation/docs/technical/dev/secrets.md.

# ------------------------------------------------------------------------------
# Guacamole
# ------------------------------------------------------------------------------

# Single guacamole-client task: tokens are minted and served from task-local
# process memory, so N>1 client tasks break first-click RDP (#928). Scale guacd
# for capacity, not the client.
# Database (production settings)
# Autoscaling (disabled for initial testing)
# Secrets
# OIDC/Cognito authentication
# ------------------------------------------------------------------------------
# Messaging (SNS/SQS)
# ------------------------------------------------------------------------------

messaging_consumers                  = ["cms", "engine", "mc"]
messaging_visibility_timeout_seconds = 60
messaging_message_retention_seconds  = 86400

# Dead Letter Queue
messaging_enable_dlq                    = true
messaging_dlq_max_receive_count         = 3
messaging_dlq_message_retention_seconds = 1209600 # 14 days

# CloudWatch Alarms
messaging_enable_alarms               = true
messaging_alarm_queue_depth_threshold = 100
messaging_alarm_message_age_threshold = 300 # 5 minutes
messaging_alarm_dlq_threshold         = 1
messaging_alarm_actions               = [] # Populated by main.tf from shared SNS topic

# ------------------------------------------------------------------------------
# SES
# ------------------------------------------------------------------------------

ses_domain     = "example.com"
email_backend  = "django_ses.SESBackend"
ctf_from_email = "ctf@example.com"

# ------------------------------------------------------------------------------
# Alerting
# ------------------------------------------------------------------------------

alarm_email = "admin@example.com"

# ------------------------------------------------------------------------------
# Bedrock Logging
# ------------------------------------------------------------------------------

enable_bedrock_logging = true

# ------------------------------------------------------------------------------
# CI Testing (not used by Terraform, extracted by quality.yml workflow)
# ------------------------------------------------------------------------------

django_secret_key_ci = "ci-test-key-prod-not-for-production"
