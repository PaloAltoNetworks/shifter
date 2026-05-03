# ------------------------------------------------------------------------------
# General
# ------------------------------------------------------------------------------

environment        = "dev"
aws_region         = "us-east-2"
log_retention_days = 30

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
ctfd_domain                 = "polaris.keplerops.com"
ctfd_repo_url               = "https://github.com/CTFd/CTFd.git"
ctfd_git_ref                = "b5f0cf2b7f0e29f72c9227ea9bc08024230b4f06"
ctfd_docker_compose_version = "v5.1.0"
ctfd_docker_buildx_version  = "v0.21.2"
ctfd_ssh_public_key         = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQC3byh0s9saNGhlaIscoH+sD0Zg2dEtSDOdh8BaCEOjGCF5mm2SHPYV7ipEz2cf5Wwx/LxMWGfOiSF2h6CGBf8KCi1syDyOYVmG41AQqubVFPES0Vf6rVDTgLVqQx7IowupLmfa4MZE75kFjvRqK12jrCkFE1W9zIUAVUTnVZ9bZnVONyTsPs2GvjqJMKo6gYVdB9Dlt67uYlYiIgjYgyOmPUhY4DPg6o/pjLABLwVMDogHFZ6GLhy/EnGyks+PnpfnmLzNE/RSM65fR2FTk7h9rpjEZASf89cw6kF8NsFjkcx9jsBra4KFsRQY8AGsH7I1nyBKBncx6pqvFvycaeo5lxE3BGZRVvvnMbo/vwuwPVLtBHpQJWVhOqk75u5ACIlbjD7TYysLOuhY2/dp9F5yC00CBjlCJ/X1Qv2MOhenj2ljDQO6eBpSKvk9U0prDTWcIysn9eT9kNh6bj4dFqGiZRG+DxpolqgVgGRxJLOfJPH0WW7z0R+F/efrpaaBVcB5xqBOJ3fP6ur+JforJEtvdjIG7Dmk0TKTMU4DS4ftwFIZVnL7nJn7DcFG8K51Bf4EyZOL2kqfB+4K+9dN5IaVO6EOyP4KeJYPoOhSnxHEJyMdAQwrCmS9NwPOeEwrYoOETWaZ8/yrkTbqMdGHi5vMpajmfNTQMtzWVvaIbihf3w== j.bradley.edwards@gmail.com"
ctfd_ssh_allowed_cidrs = {
  workstation = "173.181.31.170/32"
}

# ------------------------------------------------------------------------------
# ALB
# ------------------------------------------------------------------------------

# TODO: Update with your dev domain
domain_name       = "dev.shifter.keplerops.com"
app_port          = 8000
health_check_path = "/health"

# ------------------------------------------------------------------------------
# Cognito
# ------------------------------------------------------------------------------

cognito_domain_prefix = "shifter-dev-portal"
allowed_email_domains = ["paloaltonetworks.com"]
allowed_emails        = []

# ------------------------------------------------------------------------------
# S3
# ------------------------------------------------------------------------------

user_storage_bucket = "shifter-dev-user-storage-788327019743"

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

enable_autoscaling   = true
asg_min_size         = 6
asg_max_size         = 8
asg_desired_capacity = 6
scale_up_threshold   = 70
scale_down_threshold = 30

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

# Disabled for initial deployment - enable when ready for XDR integration
enable_log_aggregation = false

# ------------------------------------------------------------------------------
# Phase 5: Additional Log Sources
# ------------------------------------------------------------------------------

enable_alb_access_logs = true
enable_vpc_flow_logs   = true
enable_rds_log_exports = true
enable_waf_logging     = true

# ------------------------------------------------------------------------------
# Engine Provisioner
# ------------------------------------------------------------------------------

engine_container_tag = "latest"

# Windows/DC AMIs also managed via SSM Parameter Store

dc_domain_name = "internal.shifter"
# nosec B105 - Ephemeral isolated range, not a production credential
dc_domain_password = "Sh1fterDC2026" # pragma: allowlist secret

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
guacamole_db_instance_class        = "db.t3.small"
guacamole_db_allocated_storage     = 20
guacamole_db_max_allocated_storage = 50
guacamole_db_engine_version        = "16"
guacamole_db_multi_az              = false
guacamole_db_backup_retention_days = 7
guacamole_db_deletion_protection   = false
guacamole_db_skip_final_snapshot   = true

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

ses_domain     = "keplerops.com"
email_backend  = "django_ses.SESBackend"
ctf_from_email = "ctf@keplerops.com"

# ------------------------------------------------------------------------------
# Alerting
# ------------------------------------------------------------------------------

alarm_email = "bedwards@paloaltonetworks.com"

# ------------------------------------------------------------------------------
# Bedrock Logging
# ------------------------------------------------------------------------------

enable_bedrock_logging = true

# ------------------------------------------------------------------------------
# CI Testing (not used by Terraform, extracted by quality.yml workflow)
# ------------------------------------------------------------------------------

django_secret_key_ci = "ci-test-key-dev-not-for-production"
