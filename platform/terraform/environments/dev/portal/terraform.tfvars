# terraform.tfvars — committed example.com baseline for OSS deployers.
# This file IS `terraform.tfvars` (committed). Deployment-specific overrides go in
# a sibling `local.auto.tfvars` (gitignored) — Terraform auto-loads
# `*.auto.tfvars` and the local values win. CI deploys render the overrides
# from GitHub secrets/repository variables; see docs/dev/deploy-secrets.md.


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

# ------------------------------------------------------------------------------
# RDS
# ------------------------------------------------------------------------------

db_name                  = "shifter"
db_username              = "shifter_admin"
db_engine_version        = "16"
db_instance_class        = "db.m5.large"
db_allocated_storage     = 20
db_max_allocated_storage = 50
db_multi_az              = true
db_backup_retention_days = 1
db_deletion_protection   = false
db_skip_final_snapshot   = true
db_apply_immediately     = true

# ------------------------------------------------------------------------------
# EC2
# ------------------------------------------------------------------------------

# Standard AL2023 AMI (NOT ECS-optimized) - us-east-2
ec2_ami_id           = "ami-00e428798e77d38d9"
ec2_instance_type    = "m5.xlarge"
ec2_root_volume_size = 30

# Standalone CTFd host in the portal VPC
enable_ctfd                 = true
ctfd_ami_id                 = "ami-0b0b78dcacbab728f"
ctfd_instance_type          = "t3.xlarge"
ctfd_root_volume_size       = 50
ctfd_root_volume_type       = "gp3"
ctfd_root_volume_iops       = 3000
ctfd_root_volume_throughput = 125
ctfd_domain                 = "polaris.example.com"
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
domain_name       = "dev.shifter.example.com"
app_port          = 8000
health_check_path = "/health"

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

victim_instance_type = "t3.large"
kali_instance_type   = "t3.large"

# ------------------------------------------------------------------------------
# Autoscaling
# ------------------------------------------------------------------------------

enable_autoscaling   = false
asg_min_size         = 1
asg_max_size         = 1
asg_desired_capacity = 1
scale_up_threshold   = 70
scale_down_threshold = 30

# Channel-layer backend (ADR-018, #849), decoupled from autoscaling above.
# Dev keeps the in-memory channel layer (Redis provisioned but unused). Flip to
# true to run the portal on Redis for event-representative websocket behavior;
# no change to enable_autoscaling is required.
enable_redis = false

# ------------------------------------------------------------------------------
# Redis
# ------------------------------------------------------------------------------

redis_node_type          = "cache.m6g.large"
redis_engine_version     = "7.1"
redis_enable_replication = true

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

enable_alb_access_logs = true
enable_vpc_flow_logs   = true
enable_rds_log_exports = true
enable_waf_logging     = true

# ------------------------------------------------------------------------------
# Portal east-west inspection (#122)
# ------------------------------------------------------------------------------

enable_portal_inspection    = true
firewall_log_retention_days = 365

# ------------------------------------------------------------------------------
# Engine Provisioner
# ------------------------------------------------------------------------------

engine_container_tag = "latest"

# Windows/DC AMIs also managed via SSM Parameter Store

dc_domain_name = "internal.shifter"
# Domain Controller Administrator password is sourced from
# aws_secretsmanager_secret.dc_domain_password (engine-provisioner module)
# at runtime; the value is managed out-of-band and is intentionally not
# present in Terraform configuration. See
# shifter/shifter_platform/documentation/docs/technical/dev/secrets.md.

# ------------------------------------------------------------------------------
# Guacamole
# ------------------------------------------------------------------------------

guacd_image_tag                = "1.5.5"
guacamole_client_image_tag     = "1.5.5"
guacd_cpu                      = 1024
guacd_memory                   = 2048
guacamole_client_cpu           = 1024
guacamole_client_memory        = 2048
guacd_desired_count            = 4
guacamole_client_desired_count = 3

# Database
guacamole_db_instance_class        = "db.m5.xlarge"
guacamole_db_allocated_storage     = 20
guacamole_db_max_allocated_storage = 50
guacamole_db_engine_version        = "16"
guacamole_db_multi_az              = false
guacamole_db_backup_retention_days = 7
guacamole_db_deletion_protection   = false
guacamole_db_skip_final_snapshot   = true
guacamole_db_apply_immediately     = true

# Autoscaling (disabled for initial testing)
guacamole_enable_autoscaling       = false
guacamole_autoscaling_min_capacity = 1
guacamole_autoscaling_max_capacity = 4
guacamole_autoscaling_cpu_target   = 70

# Secrets
guacamole_secrets_recovery_window_days = 0

# OIDC/Cognito authentication
guacamole_enable_oidc = true

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
