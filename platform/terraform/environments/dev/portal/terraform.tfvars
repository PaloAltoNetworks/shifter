# terraform.tfvars — committed example.com baseline for OSS deployers.
# This file IS `terraform.tfvars` (committed). Deployment-specific overrides go in
# a sibling `local.auto.tfvars` (gitignored) — Terraform auto-loads
# `*.auto.tfvars` and the local values win. CI deploys render the overrides
# from GitHub secrets; see docs/dev/deploy-secrets.md.

# ------------------------------------------------------------------------------
# General
# ------------------------------------------------------------------------------

environment        = "dev"
aws_region         = "us-east-2"
log_retention_days = 365

tags = {
  Project     = "shifter"
  Environment = "dev"
  ManagedBy   = "terraform"
}

# ------------------------------------------------------------------------------
# VPC
# ------------------------------------------------------------------------------

vpc_cidr           = "10.0.0.0/16"
az_count           = 2
enable_nat_gateway = true

# CIDR of the EKS control-plane VPC (must match the eks root's vpc_cidr and be
# disjoint from vpc_cidr above + the range VPC). Allowed to reach RDS/Redis over
# the portal<->EKS peering; the portal app + provisioner run as EKS pods.
eks_vpc_cidr = "10.80.0.0/16"

# ------------------------------------------------------------------------------
# RDS
# ------------------------------------------------------------------------------

db_name                  = "shifter"
db_username              = "shifter_admin"
db_engine_version        = "16"
db_instance_class        = "db.t3.large"
db_allocated_storage     = 20
db_max_allocated_storage = 100
db_multi_az              = false
db_backup_retention_days = 7
db_deletion_protection   = false
db_skip_final_snapshot   = true
db_apply_immediately     = true

# ------------------------------------------------------------------------------
# EC2
# ------------------------------------------------------------------------------

# Standard AL2023 AMI (NOT ECS-optimized) - us-east-2
# Portal runtime capacity tunables (#930). t3.large has 2 vCPUs, so size the
# Gunicorn/Uvicorn pool to 2 workers (the image default of 4 oversubscribes a
# 2-vCPU host). Terminal caps are process-local; per-instance terminal ceiling =
# portal_web_workers * terminal_max_sessions = 2 * 200 = 400 sessions.
portal_web_workers             = 2
terminal_max_sessions          = 200
terminal_max_sessions_per_user = 10
terminal_idle_timeout_seconds  = 1800
terminal_max_session_seconds   = 28800
terminal_read_poll_seconds     = 30

# Standalone CTFd host in the portal VPC
enable_ctfd                 = true
ctfd_ami_id                 = "ami-xxxxxxxxxxxxxxxxx"
ctfd_instance_type          = "t3.xlarge"
ctfd_root_volume_size       = 50
ctfd_root_volume_type       = "gp3"
ctfd_root_volume_iops       = 3000
ctfd_root_volume_throughput = 125
ctfd_domain                 = "ctf.example.com"
ctfd_repo_url               = "https://github.com/CTFd/CTFd.git"
ctfd_git_ref                = "b5f0cf2b7f0e29f72c9227ea9bc08024230b4f06"
ctfd_docker_compose_version = "v5.1.0"
ctfd_docker_buildx_version  = "v0.21.2"
# REPLACE: paste your own SSH public key (an empty string disables CTFd SSH and
# the corresponding security-group rule); never commit a real private-key holder's
# public key into the example.
ctfd_ssh_public_key = ""
# REPLACE: per-operator /32 CIDRs from which you allow SSH to the CTFd host;
# leaving this empty disables CTFd SSH ingress.
ctfd_ssh_allowed_cidrs = {}

# ------------------------------------------------------------------------------
# ALB
# ------------------------------------------------------------------------------

# TODO: Update with your dev domain
domain_name = "dev.shifter.example.com"
# ------------------------------------------------------------------------------
# Cognito
# ------------------------------------------------------------------------------

cognito_domain_prefix = "shifter-dev-portal"
# REPLACE: the email domains permitted to self-register via Cognito pre-signup.
# Leaving this empty fails closed — no domain-wide self-signup. Add only domains
# your tenancy owns; do NOT ship a third-party domain in an example.
allowed_email_domains = []
allowed_emails        = []

# ------------------------------------------------------------------------------
# S3
# ------------------------------------------------------------------------------

# REPLACE: your S3 bucket name for user-uploaded artifacts. Convention is
# "shifter-<env>-user-storage-<account-id>" but the actual name is up to you.
user_storage_bucket = "shifter-dev-user-storage-REPLACE_WITH_ACCOUNT_ID"

# ------------------------------------------------------------------------------
# Provisioner
# ------------------------------------------------------------------------------

# AMI IDs are now managed via SSM Parameter Store (/shifter/ami/*)
# See shifter/packer/ for AMI build configuration

# ------------------------------------------------------------------------------
# Autoscaling
# ------------------------------------------------------------------------------

# Portal app-saturation autoscaling + observability (#940). dev runs a single
# instance (enable_autoscaling = false), so the ASG-scoped scaling policies and
# the PortalCapacity/CPU alarms + dashboard are not created; the ALB latency/5xx/
# rejected/unhealthy observability alarms still are. The app emitter is enabled
# in ASG-mode environments where the capacity alarms exist, so it stays off here.
portal_capacity_metrics_enabled = false
portal_worker_soft_concurrency  = 6
# Channel-layer backend (ADR-018, #849), decoupled from autoscaling above.
# The committed OSS baseline is single-instance and uses the in-memory channel
# layer. Event-sized deployments override this to true in local.auto.tfvars.
enable_redis = false

# ------------------------------------------------------------------------------
# Redis
# ------------------------------------------------------------------------------

redis_node_type          = "cache.t3.micro"
redis_engine_version     = "7.1"
redis_enable_replication = false
redis_apply_immediately  = true

# ------------------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------------------

log_level = "DEBUG"

# ------------------------------------------------------------------------------
# Log Aggregation
# ------------------------------------------------------------------------------

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

# dev: allow intentional teardown; apply once with this false before destroying
portal_inspection_delete_protection = false

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

# Database
# Autoscaling
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

django_secret_key_ci = "ci-test-key-dev-not-for-production"
